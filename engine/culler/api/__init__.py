"""Local HTTP API for the desktop app. Binds to 127.0.0.1 only."""

from .app import create_app

__all__ = ["create_app"]
