"""Convenience module exposing application settings at the backend root.

The real implementation lives in ``app/core/config.py``. This shim keeps
``from config import settings`` working for scripts, notebooks and shells
started from the ``backend/`` directory.
"""

from app.core.config import Settings, get_settings

settings = get_settings()

__all__ = ["Settings", "get_settings", "settings"]
