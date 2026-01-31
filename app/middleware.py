"""
Custom Middleware for OmniMCP.

Provides middleware for:
- Adding trailing newlines to JSON responses (for better CLI output)
- Logging HTTP requests to the in-memory log buffer
"""

from __future__ import annotations

import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


class TrailingNewlineMiddleware:
    """
    Middleware that adds a trailing newline to JSON responses.

    This improves the terminal experience when using curl or other CLI tools,
    as the response won't run into the next shell prompt.

    Note: Uses raw ASGI interface instead of BaseHTTPMiddleware to avoid
    Content-Length issues with response body modification.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Collect response parts
        response_started = False
        initial_message = None
        body_parts = []

        async def send_wrapper(message):
            nonlocal response_started, initial_message, body_parts

            if message["type"] == "http.response.start":
                initial_message = message
                response_started = True
            elif message["type"] == "http.response.body":
                body = message.get("body", b"")
                more_body = message.get("more_body", False)

                if more_body:
                    # Streaming response - pass through without modification
                    if initial_message:
                        await send(initial_message)
                        initial_message = None
                    await send(message)
                else:
                    # Final chunk - collect and modify if JSON
                    body_parts.append(body)

        await self.app(scope, receive, send_wrapper)

        # If we collected body parts, send them now with modification
        if initial_message and body_parts:
            headers = dict(initial_message.get("headers", []))
            content_type = headers.get(b"content-type", b"").decode("utf-8", errors="ignore")

            full_body = b"".join(body_parts)

            # Add newline to JSON responses
            if "application/json" in content_type and full_body and not full_body.endswith(b"\n"):
                full_body = full_body + b"\n"

            # Update content-length header
            new_headers = [
                (k, v) for k, v in initial_message.get("headers", [])
                if k.lower() != b"content-length"
            ]
            new_headers.append((b"content-length", str(len(full_body)).encode()))

            await send({
                "type": "http.response.start",
                "status": initial_message["status"],
                "headers": new_headers,
            })
            await send({
                "type": "http.response.body",
                "body": full_body,
            })


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """
    Middleware that logs HTTP requests to the in-memory log buffer.

    Logs method, path, status code, and response time for each request.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        start_time = time.time()

        response = await call_next(request)

        # Calculate duration
        duration_ms = (time.time() - start_time) * 1000

        # Log the request (skip health checks to reduce noise)
        if request.url.path != "/health":
            try:
                from app.web.routes.admin import log_request
                log_request(
                    method=request.method,
                    path=request.url.path,
                    status_code=response.status_code,
                    duration_ms=duration_ms,
                )
            except ImportError:
                pass  # Log buffer not available

        return response
