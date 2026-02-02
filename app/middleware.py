"""
Custom Middleware for ToolDock.

Provides middleware for:
- Adding trailing newlines to JSON responses (for better CLI output)
- Logging HTTP requests to the in-memory log buffer
- Request context tracking (correlation IDs)
"""

from __future__ import annotations

import time


from app.utils import generate_request_id, set_request_context, clear_request_context, get_request_id
from app.metrics_store import get_metrics_store


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


class RequestLoggingMiddleware:
    """
    Middleware that logs HTTP requests to the in-memory log buffer.

    Logs method, path, status code, response time, and error details.
    Also sets up request context for correlation IDs.

    Uses raw ASGI interface to capture response body for error logging.
    """

    def __init__(self, app, service_name: str | None = None):
        self.app = app
        self.service_name = service_name

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Generate and set request ID for correlation
        request_id = generate_request_id()
        set_request_context(request_id=request_id)

        # Extract request info
        method = scope.get("method", "")
        path = scope.get("path", "")

        # Extract tool name from path if it's a tool call
        tool_name = None
        if path.startswith("/tools/") and method == "POST":
            tool_name = path.split("/tools/", 1)[1].split("/")[0]
            set_request_context(tool_name=tool_name)

        start_time = time.time()

        # Capture response info
        status_code = 0
        response_body_parts = []
        content_type = ""

        async def send_wrapper(message):
            nonlocal status_code, content_type

            if message["type"] == "http.response.start":
                status_code = message.get("status", 0)
                headers = dict(message.get("headers", []))
                content_type = headers.get(b"content-type", b"").decode("utf-8", errors="ignore")

            elif message["type"] == "http.response.body":
                # Capture body for error responses (4xx, 5xx)
                if status_code >= 400:
                    body = message.get("body", b"")
                    if body:
                        response_body_parts.append(body)

            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            # Calculate duration
            duration_ms = (time.time() - start_time) * 1000

            # Log the request (skip health checks to reduce noise)
            if path != "/health":
                try:
                    from app.web.routes.admin import log_request

                    # Extract error detail for 4xx/5xx responses
                    error_detail = None
                    if status_code >= 400 and response_body_parts:
                        try:
                            full_body = b"".join(response_body_parts)
                            # Limit error detail to 1000 chars
                            error_detail = full_body.decode("utf-8", errors="replace")[:1000]
                        except Exception:
                            pass

                    log_request(
                        method=method,
                        path=path,
                        status_code=status_code,
                        duration_ms=duration_ms,
                        tool_name=tool_name,
                        service_name=self.service_name,
                        request_id=request_id,
                        error_detail=error_detail,
                    )
                    metrics_store = get_metrics_store()
                    if metrics_store and self.service_name:
                        metrics_store.record(self.service_name, status_code, tool_name)
                except ImportError:
                    pass  # Log buffer not available

            # Always clear context after request
            clear_request_context()
