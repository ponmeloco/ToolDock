"""
Custom Middleware for OmniMCP.

Provides middleware for:
- Adding trailing newlines to JSON responses (for better CLI output)
"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


class TrailingNewlineMiddleware(BaseHTTPMiddleware):
    """
    Middleware that adds a trailing newline to JSON responses.

    This improves the terminal experience when using curl or other CLI tools,
    as the response won't run into the next shell prompt.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)

        # Only modify JSON responses
        content_type = response.headers.get("content-type", "")
        if "application/json" not in content_type:
            return response

        # For streaming responses, we can't modify them easily
        if hasattr(response, "body_iterator"):
            # StreamingResponse - wrap the iterator to add newline at end
            original_body_iterator = response.body_iterator

            async def body_with_newline():
                async for chunk in original_body_iterator:
                    yield chunk
                yield b"\n"

            response.body_iterator = body_with_newline()
            return response

        # For regular responses, read body and add newline
        if hasattr(response, "body"):
            body = response.body
            if body and not body.endswith(b"\n"):
                new_body = body + b"\n"
                # Create new response with modified body
                return Response(
                    content=new_body,
                    status_code=response.status_code,
                    headers=dict(response.headers),
                    media_type=response.media_type,
                )

        return response
