"""
OpenAPI App - Backward Compatibility Module

This module provides backward compatibility with the original openapi_app.py.
For new code, import from app.transports.openapi_server instead.

Usage (legacy):
    uvicorn openapi_app:app --host 0.0.0.0 --port 8000
"""

from app.transports.openapi_server import app, create_openapi_app, create_legacy_openapi_app

__all__ = ["app", "create_openapi_app", "create_legacy_openapi_app"]
