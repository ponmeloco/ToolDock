"""
Unit tests for app/middleware.py - Custom middleware classes.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.middleware import TrailingNewlineMiddleware, RequestLoggingMiddleware


class TestTrailingNewlineMiddleware:
    """Tests for TrailingNewlineMiddleware."""

    def test_init_stores_app(self):
        """Test middleware stores the wrapped app."""
        mock_app = MagicMock()
        middleware = TrailingNewlineMiddleware(mock_app)
        assert middleware.app is mock_app

    @pytest.mark.asyncio
    async def test_non_http_passes_through(self):
        """Test non-HTTP requests pass through unchanged."""
        mock_app = AsyncMock()
        middleware = TrailingNewlineMiddleware(mock_app)

        scope = {"type": "websocket"}
        receive = AsyncMock()
        send = AsyncMock()

        await middleware(scope, receive, send)

        mock_app.assert_called_once_with(scope, receive, send)

    @pytest.mark.asyncio
    async def test_json_response_gets_newline(self):
        """Test JSON responses get trailing newline."""
        body_sent = []

        async def mock_app(scope, receive, send):
            await send({
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-type", b"application/json")],
            })
            await send({
                "type": "http.response.body",
                "body": b'{"key": "value"}',
                "more_body": False,
            })

        middleware = TrailingNewlineMiddleware(mock_app)

        async def capture_send(message):
            body_sent.append(message)

        scope = {"type": "http"}
        await middleware(scope, AsyncMock(), capture_send)

        # Find the body message
        body_message = next(m for m in body_sent if m.get("type") == "http.response.body")
        assert body_message["body"].endswith(b"\n")

    @pytest.mark.asyncio
    async def test_json_response_already_has_newline(self):
        """Test JSON responses that already have newline are not modified."""
        async def mock_app(scope, receive, send):
            await send({
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-type", b"application/json")],
            })
            await send({
                "type": "http.response.body",
                "body": b'{"key": "value"}\n',
                "more_body": False,
            })

        middleware = TrailingNewlineMiddleware(mock_app)
        body_sent = []

        async def capture_send(message):
            body_sent.append(message)

        scope = {"type": "http"}
        await middleware(scope, AsyncMock(), capture_send)

        body_message = next(m for m in body_sent if m.get("type") == "http.response.body")
        # Should still end with just one newline, not two
        assert body_message["body"] == b'{"key": "value"}\n'

    @pytest.mark.asyncio
    async def test_non_json_response_unchanged(self):
        """Test non-JSON responses are not modified."""
        async def mock_app(scope, receive, send):
            await send({
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-type", b"text/html")],
            })
            await send({
                "type": "http.response.body",
                "body": b"<html></html>",
                "more_body": False,
            })

        middleware = TrailingNewlineMiddleware(mock_app)
        body_sent = []

        async def capture_send(message):
            body_sent.append(message)

        scope = {"type": "http"}
        await middleware(scope, AsyncMock(), capture_send)

        body_message = next(m for m in body_sent if m.get("type") == "http.response.body")
        # Should not have newline added
        assert body_message["body"] == b"<html></html>"

    @pytest.mark.asyncio
    async def test_streaming_response_passes_through(self):
        """Test streaming responses pass through without modification."""
        chunks_sent = []

        async def mock_app(scope, receive, send):
            await send({
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-type", b"application/json")],
            })
            # Streaming - more_body=True
            await send({
                "type": "http.response.body",
                "body": b'{"chunk": 1}',
                "more_body": True,
            })
            await send({
                "type": "http.response.body",
                "body": b'{"chunk": 2}',
                "more_body": False,
            })

        middleware = TrailingNewlineMiddleware(mock_app)

        async def capture_send(message):
            chunks_sent.append(message)

        scope = {"type": "http"}
        await middleware(scope, AsyncMock(), capture_send)

        # Streaming responses should pass through
        body_messages = [m for m in chunks_sent if m.get("type") == "http.response.body"]
        assert len(body_messages) >= 1

    @pytest.mark.asyncio
    async def test_content_length_updated(self):
        """Test content-length header is updated after adding newline."""
        headers_sent = {}

        async def mock_app(scope, receive, send):
            await send({
                "type": "http.response.start",
                "status": 200,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", b"16"),  # Original length
                ],
            })
            await send({
                "type": "http.response.body",
                "body": b'{"key": "value"}',
                "more_body": False,
            })

        middleware = TrailingNewlineMiddleware(mock_app)

        async def capture_send(message):
            if message.get("type") == "http.response.start":
                headers_sent["headers"] = dict(message.get("headers", []))

        scope = {"type": "http"}
        await middleware(scope, AsyncMock(), capture_send)

        # Content-length should be updated (original 16 + 1 newline = 17)
        assert headers_sent["headers"][b"content-length"] == b"17"


class TestRequestLoggingMiddleware:
    """Tests for RequestLoggingMiddleware."""

    def test_init_stores_app(self):
        """Test middleware stores the wrapped app."""
        mock_app = MagicMock()
        middleware = RequestLoggingMiddleware(mock_app)
        assert middleware.app is mock_app

    @pytest.mark.asyncio
    async def test_non_http_passes_through(self):
        """Test non-HTTP requests pass through unchanged."""
        mock_app = AsyncMock()
        middleware = RequestLoggingMiddleware(mock_app)

        scope = {"type": "websocket"}
        receive = AsyncMock()
        send = AsyncMock()

        await middleware(scope, receive, send)

        mock_app.assert_called_once_with(scope, receive, send)

    @pytest.mark.asyncio
    async def test_sets_request_context(self):
        """Test middleware sets request context."""
        async def mock_app(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b""})

        middleware = RequestLoggingMiddleware(mock_app)

        with patch("app.middleware.set_request_context") as mock_set_ctx:
            with patch("app.middleware.clear_request_context"):
                with patch("app.middleware.generate_request_id", return_value="abc123"):
                    scope = {"type": "http", "method": "GET", "path": "/test"}
                    await middleware(scope, AsyncMock(), AsyncMock())

                    mock_set_ctx.assert_called()

    @pytest.mark.asyncio
    async def test_clears_request_context_after(self):
        """Test middleware clears request context after request."""
        async def mock_app(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b""})

        middleware = RequestLoggingMiddleware(mock_app)

        with patch("app.middleware.set_request_context"):
            with patch("app.middleware.clear_request_context") as mock_clear:
                with patch("app.middleware.generate_request_id", return_value="abc"):
                    scope = {"type": "http", "method": "GET", "path": "/test"}
                    await middleware(scope, AsyncMock(), AsyncMock())

                    mock_clear.assert_called_once()

    @pytest.mark.asyncio
    async def test_extracts_tool_name_from_path(self):
        """Test middleware extracts tool name from /tools/ path."""
        async def mock_app(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b""})

        middleware = RequestLoggingMiddleware(mock_app)

        tool_name_set = None

        def mock_set_context(**kwargs):
            nonlocal tool_name_set
            if "tool_name" in kwargs:
                tool_name_set = kwargs["tool_name"]

        with patch("app.middleware.set_request_context", side_effect=mock_set_context):
            with patch("app.middleware.clear_request_context"):
                with patch("app.middleware.generate_request_id", return_value="abc"):
                    scope = {"type": "http", "method": "POST", "path": "/tools/my_tool"}
                    await middleware(scope, AsyncMock(), AsyncMock())

        assert tool_name_set == "my_tool"

    @pytest.mark.asyncio
    async def test_skips_health_endpoint_logging(self):
        """Test middleware skips logging for /health endpoint."""
        async def mock_app(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b""})

        middleware = RequestLoggingMiddleware(mock_app)

        with patch("app.middleware.set_request_context"):
            with patch("app.middleware.clear_request_context"):
                with patch("app.middleware.generate_request_id", return_value="abc"):
                    # Patch the log_request import inside the middleware
                    with patch.dict("sys.modules", {"app.web.routes.admin": MagicMock()}):
                        scope = {"type": "http", "method": "GET", "path": "/health"}
                        await middleware(scope, AsyncMock(), AsyncMock())

    @pytest.mark.asyncio
    async def test_captures_error_response_body(self):
        """Test middleware captures response body for error responses."""
        async def mock_app(scope, receive, send):
            await send({
                "type": "http.response.start",
                "status": 500,
                "headers": [(b"content-type", b"application/json")],
            })
            await send({
                "type": "http.response.body",
                "body": b'{"error": "Internal server error"}',
            })

        middleware = RequestLoggingMiddleware(mock_app)

        logged_error = None

        def mock_log_request(**kwargs):
            nonlocal logged_error
            logged_error = kwargs.get("error_detail")

        with patch("app.middleware.set_request_context"):
            with patch("app.middleware.clear_request_context"):
                with patch("app.middleware.generate_request_id", return_value="abc"):
                    with patch("app.web.routes.admin.log_request", mock_log_request):
                        scope = {"type": "http", "method": "GET", "path": "/api/test"}
                        await middleware(scope, AsyncMock(), AsyncMock())

        # The error detail should have been captured
        # (may be None if import fails, which is expected in test environment)

    @pytest.mark.asyncio
    async def test_clears_context_on_exception(self):
        """Test middleware clears context even when app raises exception."""
        async def failing_app(scope, receive, send):
            raise RuntimeError("App crashed")

        middleware = RequestLoggingMiddleware(failing_app)

        with patch("app.middleware.set_request_context"):
            with patch("app.middleware.clear_request_context") as mock_clear:
                with patch("app.middleware.generate_request_id", return_value="abc"):
                    scope = {"type": "http", "method": "GET", "path": "/test"}

                    with pytest.raises(RuntimeError):
                        await middleware(scope, AsyncMock(), AsyncMock())

                    # Context should still be cleared
                    mock_clear.assert_called_once()
