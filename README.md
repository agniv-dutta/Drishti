# Drishti

Drishti is an AI revenue recovery backend built with FastAPI. The service includes API routes for payments, recovery workflows, audit logging, and metrics, plus support for PostgreSQL, Redis, and local ML utilities.

## Project Layout

- `backend/` - FastAPI app, tests, scripts, and supporting modules
- `backend/app/` - application code
- `backend/tests/` - unit, integration, and end-to-end tests
- `backend/notebooks/` - experimentation and analysis notebooks
- `backend/docker-compose.yml` - local PostgreSQL, Redis, and API stack

## Local Development

1. Install dependencies from `backend/requirements.txt`.
2. Configure environment variables for the API, database, and cache.
3. Start the app with Uvicorn from the `backend/` directory.
4. Or use Docker Compose from `backend/` to bring up PostgreSQL, Redis, and the API together.

## API

- Health check: `/health`
- Interactive docs: `/docs`
- ReDoc: `/redoc`

## Testing

Run the backend test suite from the `backend/` directory with `pytest`.

