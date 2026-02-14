"""
Authentication Module for ToolDock.

Provides multiple authentication methods:
- Bearer token authentication (for API clients)
- HTTP Basic authentication (for browser access)

Security best practices:
- Constant-time token comparison to prevent timing attacks
- Configurable public paths
- Middleware for blanket authentication
"""

from __future__ import annotations

import base64
import hmac
import logging
import os
import secrets
from typing import Optional, Set

from fastapi import Header, HTTPException, Depends
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)

# HTTP Basic Auth security instance
http_basic = HTTPBasic(auto_error=False)

# Default admin username (can be overridden via environment)
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")


def get_bearer_token() -> Optional[str]:
    """
    Get the configured bearer token from environment.

    Returns None if no token is configured (auth disabled).
    """
    token = os.getenv("BEARER_TOKEN", "").strip()
    return token or None


def is_auth_enabled() -> bool:
    """Check if authentication is enabled."""
    return get_bearer_token() is not None


def _constant_time_compare(a: str, b: str) -> bool:
    """
    Compare two strings in constant time to prevent timing attacks.

    Uses hmac.compare_digest which is designed for this purpose.
    """
    # Encode to bytes for hmac.compare_digest
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


# ==================== Bearer Token Auth ====================

async def verify_token(authorization: Optional[str] = Header(None)) -> str:
    """
    FastAPI dependency to verify bearer token.

    Uses constant-time comparison to prevent timing attacks.

    Returns the token if valid, raises HTTPException if invalid.
    """
    if not is_auth_enabled():
        return ""

    if not authorization:
        raise HTTPException(
            status_code=401,
            detail="Authorization header required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=401,
            detail="Invalid authorization header format. Use: Bearer <token>",
            headers={"WWW-Authenticate": "Bearer"},
        )

    provided = authorization.split(" ", 1)[1].strip()
    expected = get_bearer_token()

    if not expected or not _constant_time_compare(provided, expected):
        raise HTTPException(
            status_code=401,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return provided


def _extract_bearer(header_value: str) -> Optional[str]:
    """Extract bearer token from Authorization header."""
    if not header_value:
        return None
    parts = header_value.split(" ", 1)
    if len(parts) != 2:
        return None
    if parts[0].lower() != "bearer":
        return None
    return parts[1].strip() or None


# ==================== HTTP Basic Auth ====================

async def verify_basic_auth(
    credentials: Optional[HTTPBasicCredentials] = Depends(http_basic),
) -> str:
    """
    FastAPI dependency to verify HTTP Basic authentication.

    Username: 'admin' (or ADMIN_USERNAME env var)
    Password: The BEARER_TOKEN value

    Returns the username if valid, raises HTTPException if invalid.
    """
    if not is_auth_enabled():
        return "anonymous"

    expected_password = get_bearer_token()

    if not credentials:
        raise HTTPException(
            status_code=401,
            detail="Authentication required",
            headers={"WWW-Authenticate": 'Basic realm="ToolDock"'},
        )

    # Constant-time comparison for both username and password
    username_valid = _constant_time_compare(credentials.username, ADMIN_USERNAME)
    password_valid = _constant_time_compare(credentials.password, expected_password or "")

    if not (username_valid and password_valid):
        raise HTTPException(
            status_code=401,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": 'Basic realm="ToolDock"'},
        )

    return credentials.username


# ==================== Combined Auth (Bearer OR Basic) ====================

async def verify_token_or_basic(
    authorization: Optional[str] = Header(None),
    credentials: Optional[HTTPBasicCredentials] = Depends(http_basic),
) -> str:
    """
    FastAPI dependency that accepts either Bearer token OR HTTP Basic auth.

    Useful for endpoints that need to support both API clients (Bearer)
    and browser access (Basic).

    Returns the authenticated identity (token or username).
    """
    if not is_auth_enabled():
        return "anonymous"

    expected_token = get_bearer_token()

    # Try Bearer token first
    if authorization and authorization.lower().startswith("bearer "):
        provided = authorization.split(" ", 1)[1].strip()
        if expected_token and _constant_time_compare(provided, expected_token):
            return "bearer-auth"

    # Try Basic auth
    if credentials:
        username_valid = _constant_time_compare(credentials.username, ADMIN_USERNAME)
        password_valid = _constant_time_compare(credentials.password, expected_token or "")
        if username_valid and password_valid:
            return credentials.username

    # Neither worked - return appropriate auth challenge
    # Prefer Basic for browser compatibility
    raise HTTPException(
        status_code=401,
        detail="Authentication required",
        headers={"WWW-Authenticate": 'Basic realm="ToolDock"'},
    )


# ==================== Middleware ====================

class BearerAuthMiddleware:
    """
    Middleware for bearer token authentication.

    Applies to all routes except those in public_paths.
    Uses constant-time comparison for token validation.
    """

    def __init__(self, app, public_paths: Optional[Set[str]] = None):
        self.app = app
        self.public_paths = public_paths or set()

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive)
        # Skip auth if disabled
        if not is_auth_enabled():
            await self.app(scope, receive, send)
            return

        # Allow public paths
        if request.url.path in self.public_paths:
            await self.app(scope, receive, send)
            return

        # Also allow paths that start with any public path (for path params)
        for public_path in self.public_paths:
            if request.url.path.startswith(public_path):
                await self.app(scope, receive, send)
                return

        token = get_bearer_token()
        auth_header = request.headers.get("authorization", "")
        provided = _extract_bearer(auth_header)

        # Use constant-time comparison
        if not provided or not token or not _constant_time_compare(provided, token):
            response = Response(
                content="Unauthorized",
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)


class BasicAuthMiddleware:
    """
    Middleware for HTTP Basic authentication with Bearer token support for API paths.

    Applies to all routes except those in public_paths.
    - HTML pages: Require Basic Auth (for browser login prompt)
    - /api/* paths: Accept either Basic Auth OR Bearer token

    Useful for web GUI where browser needs to prompt for login,
    but API endpoints also need to work with Bearer tokens.
    """

    def __init__(
        self,
        app,
        public_paths: Optional[Set[str]] = None,
        bearer_paths: Optional[Set[str]] = None,
    ):
        self.app = app
        self.public_paths = public_paths or set()
        # Paths that also accept Bearer token (in addition to Basic)
        self.bearer_paths = bearer_paths or {"/api/"}

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive)
        # Skip auth if disabled
        if not is_auth_enabled():
            await self.app(scope, receive, send)
            return

        # Allow public paths
        path = request.url.path
        if path in self.public_paths:
            await self.app(scope, receive, send)
            return

        for public_path in self.public_paths:
            if path.startswith(public_path):
                await self.app(scope, receive, send)
                return

        auth_header = request.headers.get("authorization", "")
        expected_token = get_bearer_token()

        # Check if this path allows Bearer token
        allows_bearer = any(path.startswith(bp) for bp in self.bearer_paths)

        # Try Bearer token first for API paths
        if allows_bearer and auth_header.lower().startswith("bearer "):
            provided = _extract_bearer(auth_header)
            if provided and expected_token and _constant_time_compare(provided, expected_token):
                await self.app(scope, receive, send)
                return
            # Invalid bearer token
            response = Response(
                content='{"detail": "Invalid Bearer token"}',
                status_code=401,
                media_type="application/json",
                headers={"WWW-Authenticate": "Bearer"},
            )
            await response(scope, receive, send)
            return

        # Check for Basic auth header
        if not auth_header.lower().startswith("basic "):
            # For API paths, indicate both auth methods are accepted
            if allows_bearer:
                response = Response(
                    content='{"detail": "Authorization required. Use Bearer token or Basic Auth."}',
                    status_code=401,
                    media_type="application/json",
                    headers={"WWW-Authenticate": 'Bearer, Basic realm="ToolDock"'},
                )
                await response(scope, receive, send)
                return
            response = Response(
                content="Authentication required",
                status_code=401,
                headers={"WWW-Authenticate": 'Basic realm="ToolDock"'},
            )
            await response(scope, receive, send)
            return

        # Decode and verify Basic credentials
        try:
            encoded = auth_header.split(" ", 1)[1]
            decoded = base64.b64decode(encoded).decode("utf-8")
            username, password = decoded.split(":", 1)
        except Exception:
            response = Response(
                content="Invalid authorization header",
                status_code=401,
                headers={"WWW-Authenticate": 'Basic realm="ToolDock"'},
            )
            await response(scope, receive, send)
            return

        # Constant-time comparison
        username_valid = _constant_time_compare(username, ADMIN_USERNAME)
        password_valid = _constant_time_compare(password, expected_token or "")

        if not (username_valid and password_valid):
            response = Response(
                content="Invalid credentials",
                status_code=401,
                headers={"WWW-Authenticate": 'Basic realm="ToolDock"'},
            )
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)
