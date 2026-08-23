"""Drishti - AI Revenue Recovery agent system.

FastAPI application entry point.

Run locally:
    uvicorn main:app --reload
"""

from __future__ import annotations

import time
import uuid
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.core.logging_config import configure_logging, get_logger
from app.database.session import dispose_db, init_db
from app.utils.formatters import error_response
from app.routes import audit, dashboard, health, metrics, payment, razorpay, recovery, verity


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Startup/shutdown hooks: logging, DB tables, graceful teardown."""
    settings = get_settings()
    logger = get_logger("drishti.main")
    logger.info(
        "startup.begin",
        app=settings.app_name,
        environment=settings.environment,
        version=settings.version,
    )
    init_db()
    logger.info("startup.complete", docs_url="/docs")
    yield
    dispose_db()
    logger.info("shutdown.complete")


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging()
    logger = get_logger("drishti.main")

    application = FastAPI(
        title=settings.app_name,
        description=settings.app_description,
        version=settings.version,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
    )

    origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
    application.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @application.middleware("http")
    async def attach_request_context(request: Request, call_next):
        request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
        structlog.contextvars.bind_contextvars(request_id=request_id)
        started = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            structlog.contextvars.clear_contextvars()
        elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Process-Time-Ms"] = str(elapsed_ms)
        logger.info(
            "http.request",
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=elapsed_ms,
        )
        return response

    @application.exception_handler(RequestValidationError)
    async def validation_error_handler(_: Request, exc: RequestValidationError):
        details = [
            {
                "field": ".".join(str(loc) for loc in err.get("loc", [])),
                "message": err.get("msg"),
                "type": err.get("type"),
            }
            for err in exc.errors()
        ]
        return JSONResponse(status_code=422, content=error_response("VALIDATION_ERROR", "Request payload failed validation.", details))

    @application.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, exc: Exception):  # pragma: no cover
        logger.error(
            "http.unhandled_exception",
            method=request.method,
            path=request.url.path,
            error=str(exc),
            exc_info=True,
        )
        return JSONResponse(
            status_code=500,
            content=error_response("INTERNAL_ERROR", "An unexpected error occurred."),
        )

    api = settings.api_v1_prefix
    application.include_router(health.router)
    application.include_router(payment.router, prefix=api)
    application.include_router(razorpay.router, prefix=api)
    application.include_router(recovery.router, prefix=api)
    application.include_router(dashboard.router, prefix=api)
    application.include_router(verity.router, prefix=api)
    application.include_router(audit.router, prefix=api)
    application.include_router(metrics.router, prefix=api)

    logger.info("app.created", routes=len(application.routes))
    return application


app = create_app()


if __name__ == "__main__":
    import uvicorn

    cfg = get_settings()
    uvicorn.run(
        "main:app",
        host=cfg.host,
        port=cfg.port,
        reload=cfg.debug and not cfg.is_production,
        log_config=None,
    )
