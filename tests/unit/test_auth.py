"""
Unit tests for app.auth module.
"""

from __future__ import annotations

import base64

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from fastapi import FastAPI

from app.auth import (
    _constant_time_compare,
    get_bearer_token,
    is_auth_enabled,
    verify_token,
    verify_basic_auth,
    verify_token_or_basic,
    BearerAuthMiddleware,
    BasicAuthMiddleware,
    ADMIN_USERNAME,
)


# ==================== Constant Time Compare Tests ====================


class TestConstantTimeCompare:
    """Tests for _constant_time_compare function."""

    def test_equal_strings(self):
        """Test comparing equal strings returns True."""
        assert _constant_time_compare("secret", "secret") is True
        assert _constant_time_compare("", "") is True
        assert _constant_time_compare("a" * 100, "a" * 100) is True

    def test_unequal_strings(self):
        """Test comparing unequal strings returns False."""
        assert _constant_time_compare("secret", "wrong") is False
        assert _constant_time_compare("", "something") is False
        assert _constant_time_compare("abc", "abd") is False

    def test_similar_length_strings(self):
        """Test strings of same length but different content."""
        assert _constant_time_compare("password1", "password2") is False

    def test_unicode_strings(self):
        """Test comparing unicode strings."""
        assert _constant_time_compare("tökën", "tökën") is True
        assert _constant_time_compare("tökën", "token") is False


# ==================== Auth Configuration Tests ====================


class TestAuthConfiguration:
    """Tests for auth configuration functions."""

    def test_is_auth_enabled_with_token(self, monkeypatch: pytest.MonkeyPatch):
        """Test auth is enabled when BEARER_TOKEN is set."""
        monkeypatch.setenv("BEARER_TOKEN", "my_secret_token")

        assert is_auth_enabled() is True
        assert get_bearer_token() == "my_secret_token"

    def test_is_auth_disabled_without_token(self, monkeypatch: pytest.MonkeyPatch):
        """Test auth is disabled when BEARER_TOKEN is not set."""
        monkeypatch.delenv("BEARER_TOKEN", raising=False)

        assert is_auth_enabled() is False
        assert get_bearer_token() is None

    def test_is_auth_disabled_with_empty_token(self, monkeypatch: pytest.MonkeyPatch):
        """Test auth is disabled when BEARER_TOKEN is empty."""
        monkeypatch.setenv("BEARER_TOKEN", "")

        assert is_auth_enabled() is False
        assert get_bearer_token() is None

    def test_is_auth_disabled_with_whitespace_token(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """Test auth is disabled when BEARER_TOKEN is whitespace."""
        monkeypatch.setenv("BEARER_TOKEN", "   ")

        assert is_auth_enabled() is False


# ==================== Bearer Token Verification Tests ====================


class TestVerifyToken:
    """Tests for verify_token dependency."""

    @pytest.mark.asyncio
    async def test_valid_bearer_token(self, monkeypatch: pytest.MonkeyPatch):
        """Test valid bearer token is accepted."""
        monkeypatch.setenv("BEARER_TOKEN", "valid_token")

        result = await verify_token("Bearer valid_token")

        assert result == "valid_token"

    @pytest.mark.asyncio
    async def test_invalid_bearer_token(self, monkeypatch: pytest.MonkeyPatch):
        """Test invalid bearer token is rejected."""
        monkeypatch.setenv("BEARER_TOKEN", "correct_token")

        with pytest.raises(HTTPException) as exc_info:
            await verify_token("Bearer wrong_token")

        assert exc_info.value.status_code == 401
        assert exc_info.value.detail == "Invalid token"

    @pytest.mark.asyncio
    async def test_missing_authorization_header(self, monkeypatch: pytest.MonkeyPatch):
        """Test missing authorization header raises error."""
        monkeypatch.setenv("BEARER_TOKEN", "some_token")

        with pytest.raises(HTTPException) as exc_info:
            await verify_token(None)

        assert exc_info.value.status_code == 401
        assert "Authorization header required" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_invalid_header_format(self, monkeypatch: pytest.MonkeyPatch):
        """Test non-Bearer authorization header is rejected."""
        monkeypatch.setenv("BEARER_TOKEN", "some_token")

        with pytest.raises(HTTPException) as exc_info:
            await verify_token("Basic dXNlcjpwYXNz")

        assert exc_info.value.status_code == 401
        assert "Invalid authorization header format" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_auth_disabled_accepts_anything(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """Test that when auth is disabled, any token works."""
        monkeypatch.delenv("BEARER_TOKEN", raising=False)

        result = await verify_token(None)
        assert result == ""

        result = await verify_token("Bearer whatever")
        assert result == ""


# ==================== Basic Auth Verification Tests ====================


class TestVerifyBasicAuth:
    """Tests for verify_basic_auth dependency."""

    @pytest.mark.asyncio
    async def test_valid_basic_auth(self, monkeypatch: pytest.MonkeyPatch):
        """Test valid basic auth credentials are accepted."""
        monkeypatch.setenv("BEARER_TOKEN", "my_password")

        # Create mock credentials
        from fastapi.security import HTTPBasicCredentials

        credentials = HTTPBasicCredentials(username="admin", password="my_password")

        result = await verify_basic_auth(credentials)

        assert result == "admin"

    @pytest.mark.asyncio
    async def test_invalid_username(self, monkeypatch: pytest.MonkeyPatch):
        """Test invalid username is rejected."""
        monkeypatch.setenv("BEARER_TOKEN", "my_password")

        from fastapi.security import HTTPBasicCredentials

        credentials = HTTPBasicCredentials(username="wrong_user", password="my_password")

        with pytest.raises(HTTPException) as exc_info:
            await verify_basic_auth(credentials)

        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_invalid_password(self, monkeypatch: pytest.MonkeyPatch):
        """Test invalid password is rejected."""
        monkeypatch.setenv("BEARER_TOKEN", "correct_password")

        from fastapi.security import HTTPBasicCredentials

        credentials = HTTPBasicCredentials(username="admin", password="wrong_password")

        with pytest.raises(HTTPException) as exc_info:
            await verify_basic_auth(credentials)

        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_missing_credentials(self, monkeypatch: pytest.MonkeyPatch):
        """Test missing credentials raises error."""
        monkeypatch.setenv("BEARER_TOKEN", "my_password")

        with pytest.raises(HTTPException) as exc_info:
            await verify_basic_auth(None)

        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_auth_disabled_returns_anonymous(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """Test that when auth is disabled, returns anonymous."""
        monkeypatch.delenv("BEARER_TOKEN", raising=False)

        result = await verify_basic_auth(None)

        assert result == "anonymous"


# ==================== Combined Auth Tests ====================


class TestVerifyTokenOrBasic:
    """Tests for verify_token_or_basic dependency."""

    @pytest.mark.asyncio
    async def test_accepts_bearer_token(self, monkeypatch: pytest.MonkeyPatch):
        """Test that bearer token is accepted."""
        monkeypatch.setenv("BEARER_TOKEN", "my_token")

        result = await verify_token_or_basic("Bearer my_token", None)

        assert result == "bearer-auth"

    @pytest.mark.asyncio
    async def test_accepts_basic_auth(self, monkeypatch: pytest.MonkeyPatch):
        """Test that basic auth is accepted."""
        monkeypatch.setenv("BEARER_TOKEN", "my_password")

        from fastapi.security import HTTPBasicCredentials

        credentials = HTTPBasicCredentials(username="admin", password="my_password")

        result = await verify_token_or_basic(None, credentials)

        assert result == "admin"

    @pytest.mark.asyncio
    async def test_bearer_takes_precedence(self, monkeypatch: pytest.MonkeyPatch):
        """Test that bearer token takes precedence over basic auth."""
        monkeypatch.setenv("BEARER_TOKEN", "my_token")

        from fastapi.security import HTTPBasicCredentials

        # Provide both (basic auth has different password)
        credentials = HTTPBasicCredentials(username="admin", password="different")

        result = await verify_token_or_basic("Bearer my_token", credentials)

        assert result == "bearer-auth"

    @pytest.mark.asyncio
    async def test_rejects_both_invalid(self, monkeypatch: pytest.MonkeyPatch):
        """Test that invalid credentials for both methods are rejected."""
        monkeypatch.setenv("BEARER_TOKEN", "correct_token")

        from fastapi.security import HTTPBasicCredentials

        credentials = HTTPBasicCredentials(username="admin", password="wrong")

        with pytest.raises(HTTPException) as exc_info:
            await verify_token_or_basic("Bearer wrong_token", credentials)

        assert exc_info.value.status_code == 401


# ==================== Middleware Tests ====================


class TestBearerAuthMiddleware:
    """Tests for BearerAuthMiddleware."""

    def test_allows_public_paths(self, monkeypatch: pytest.MonkeyPatch):
        """Test that public paths don't require auth."""
        monkeypatch.setenv("BEARER_TOKEN", "secret")

        app = FastAPI()
        app.add_middleware(BearerAuthMiddleware, public_paths={"/health"})

        @app.get("/health")
        async def health():
            return {"status": "ok"}

        @app.get("/protected")
        async def protected():
            return {"data": "secret"}

        client = TestClient(app)

        # Public path should work without auth
        response = client.get("/health")
        assert response.status_code == 200

        # Protected path should require auth
        response = client.get("/protected")
        assert response.status_code == 401

    def test_allows_valid_bearer_token(self, monkeypatch: pytest.MonkeyPatch):
        """Test that valid bearer token grants access."""
        monkeypatch.setenv("BEARER_TOKEN", "valid_token")

        app = FastAPI()
        app.add_middleware(BearerAuthMiddleware, public_paths=set())

        @app.get("/protected")
        async def protected():
            return {"data": "secret"}

        client = TestClient(app)

        response = client.get(
            "/protected", headers={"Authorization": "Bearer valid_token"}
        )
        assert response.status_code == 200

    def test_rejects_invalid_bearer_token(self, monkeypatch: pytest.MonkeyPatch):
        """Test that invalid bearer token is rejected."""
        monkeypatch.setenv("BEARER_TOKEN", "valid_token")

        app = FastAPI()
        app.add_middleware(BearerAuthMiddleware, public_paths=set())

        @app.get("/protected")
        async def protected():
            return {"data": "secret"}

        client = TestClient(app)

        response = client.get(
            "/protected", headers={"Authorization": "Bearer wrong_token"}
        )
        assert response.status_code == 401

    def test_no_auth_when_disabled(self, monkeypatch: pytest.MonkeyPatch):
        """Test that auth is skipped when BEARER_TOKEN is not set."""
        monkeypatch.delenv("BEARER_TOKEN", raising=False)

        app = FastAPI()
        app.add_middleware(BearerAuthMiddleware, public_paths=set())

        @app.get("/protected")
        async def protected():
            return {"data": "secret"}

        client = TestClient(app)

        # Should work without auth header
        response = client.get("/protected")
        assert response.status_code == 200


class TestBasicAuthMiddleware:
    """Tests for BasicAuthMiddleware."""

    def test_allows_public_paths(self, monkeypatch: pytest.MonkeyPatch):
        """Test that public paths don't require auth."""
        monkeypatch.setenv("BEARER_TOKEN", "secret")

        app = FastAPI()
        app.add_middleware(BasicAuthMiddleware, public_paths={"/health"})

        @app.get("/health")
        async def health():
            return {"status": "ok"}

        client = TestClient(app)

        response = client.get("/health")
        assert response.status_code == 200

    def test_allows_valid_basic_auth(self, monkeypatch: pytest.MonkeyPatch):
        """Test that valid basic auth grants access."""
        monkeypatch.setenv("BEARER_TOKEN", "my_password")

        app = FastAPI()
        app.add_middleware(BasicAuthMiddleware, public_paths=set())

        @app.get("/protected")
        async def protected():
            return {"data": "secret"}

        client = TestClient(app)

        # Encode credentials
        credentials = base64.b64encode(b"admin:my_password").decode("utf-8")

        response = client.get(
            "/protected", headers={"Authorization": f"Basic {credentials}"}
        )
        assert response.status_code == 200

    def test_allows_bearer_on_api_paths(self, monkeypatch: pytest.MonkeyPatch):
        """Test that bearer token works on /api/* paths."""
        monkeypatch.setenv("BEARER_TOKEN", "my_token")

        app = FastAPI()
        app.add_middleware(
            BasicAuthMiddleware,
            public_paths=set(),
            bearer_paths={"/api/"},
        )

        @app.get("/api/data")
        async def api_data():
            return {"data": "from api"}

        client = TestClient(app)

        response = client.get(
            "/api/data", headers={"Authorization": "Bearer my_token"}
        )
        assert response.status_code == 200

    def test_rejects_invalid_credentials(self, monkeypatch: pytest.MonkeyPatch):
        """Test that invalid credentials are rejected."""
        monkeypatch.setenv("BEARER_TOKEN", "correct_password")

        app = FastAPI()
        app.add_middleware(BasicAuthMiddleware, public_paths=set())

        @app.get("/protected")
        async def protected():
            return {"data": "secret"}

        client = TestClient(app)

        credentials = base64.b64encode(b"admin:wrong_password").decode("utf-8")

        response = client.get(
            "/protected", headers={"Authorization": f"Basic {credentials}"}
        )
        assert response.status_code == 401
