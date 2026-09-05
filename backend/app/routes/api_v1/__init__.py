"""Versioned v1 REST API routers.

These routers expose a clean, resource-oriented API and share a single response
envelope (see :mod:`app.core.responses`). Legacy flat routers in
``app.routes`` remain mounted for backward compatibility; this package is the
canonical public surface going forward.
"""
