"""Anchorum Prem Main FastAPI application entry point."""

from interface.anchorum_api import app, create_app

__all__ = ["app", "create_app"]
