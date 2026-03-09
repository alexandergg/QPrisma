"""
Tests for JWT token revocation (logout) functionality.

Covers revoke_token, is_token_revoked, verify_token with revocation,
Redis failure handling (fail-open), and backward compatibility with
tokens that lack a JTI claim.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from freezegun import freeze_time
from jose import jwt as jose_jwt

# =============================================================================
# Token Revocation — Unit Tests (mocked Redis)
# =============================================================================


@pytest.mark.unit
class TestRevokeToken:
    async def test_revoke_stores_jti_in_redis(self, auth_service):
        """Revoking a token stores its JTI in Redis with correct TTL."""
        token = auth_service.create_access_token({"sub": "user_123", "email": "a@b.com"})

        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock(return_value=True)

        with patch.object(auth_service, "_get_redis", return_value=mock_redis):
            result = await auth_service.revoke_token(token)

        assert result is True
        mock_redis.set.assert_called_once()
        call_args = mock_redis.set.call_args
        key = call_args[0][0]
        assert key.startswith("revoked:")
        # TTL should be positive and roughly match token expiry
        ttl = call_args[1]["ex"]
        assert ttl > 0

    async def test_revoke_ttl_matches_token_expiry(self, auth_service):
        """TTL of the Redis key should match time until token expires."""
        token = auth_service.create_access_token(
            {"sub": "user_123"}, expires_delta=timedelta(minutes=30)
        )

        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock(return_value=True)

        with patch.object(auth_service, "_get_redis", return_value=mock_redis):
            await auth_service.revoke_token(token)

        ttl = mock_redis.set.call_args[1]["ex"]
        # Should be close to 30 minutes (1800s), allow a few seconds margin
        assert 1790 <= ttl <= 1800

    async def test_revoke_already_expired_token(self, auth_service):
        """Revoking an already-expired token succeeds without Redis call."""
        with freeze_time("2024-01-01"):
            token = auth_service.create_access_token(
                {"sub": "user_123"}, expires_delta=timedelta(seconds=1)
            )

        mock_redis = AsyncMock()

        with (
            freeze_time("2024-01-02"),
            patch.object(auth_service, "_get_redis", return_value=mock_redis),
        ):
            result = await auth_service.revoke_token(token)

        assert result is True
        mock_redis.set.assert_not_called()

    async def test_revoke_returns_false_without_jti(self, auth_service):
        """Tokens without JTI cannot be revoked (backward compat)."""
        # Manually create a token without JTI
        payload = {
            "sub": "user_123",
            "exp": datetime.now(UTC) + timedelta(hours=1),
            "iat": datetime.now(UTC),
            "type": "access",
        }
        token = jose_jwt.encode(payload, auth_service.secret_key, algorithm=auth_service.algorithm)

        result = await auth_service.revoke_token(token)
        assert result is False

    async def test_revoke_returns_false_when_redis_unavailable(self, auth_service):
        """If Redis is unavailable, revocation fails gracefully."""
        token = auth_service.create_access_token({"sub": "user_123"})

        with patch.object(auth_service, "_get_redis", return_value=None):
            result = await auth_service.revoke_token(token)

        assert result is False

    async def test_revoke_returns_false_on_invalid_token(self, auth_service):
        """Invalid/tampered token returns False, no crash."""
        result = await auth_service.revoke_token("not.a.valid.jwt")
        assert result is False

    async def test_revoke_handles_redis_error_gracefully(self, auth_service):
        """Redis exceptions during revocation are caught (fail open)."""
        token = auth_service.create_access_token({"sub": "user_123"})

        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock(side_effect=ConnectionError("Redis down"))

        with patch.object(auth_service, "_get_redis", return_value=mock_redis):
            result = await auth_service.revoke_token(token)

        assert result is False


# =============================================================================
# Token Revocation Check
# =============================================================================


@pytest.mark.unit
class TestIsTokenRevoked:
    async def test_revoked_token_detected(self, auth_service):
        """is_token_revoked returns True when JTI exists in Redis."""
        mock_redis = AsyncMock()
        mock_redis.exists = AsyncMock(return_value=1)

        with patch.object(auth_service, "_get_redis", return_value=mock_redis):
            assert await auth_service.is_token_revoked("some-jti") is True

        mock_redis.exists.assert_called_once_with("revoked:some-jti")

    async def test_non_revoked_token(self, auth_service):
        """is_token_revoked returns False when JTI is not in Redis."""
        mock_redis = AsyncMock()
        mock_redis.exists = AsyncMock(return_value=0)

        with patch.object(auth_service, "_get_redis", return_value=mock_redis):
            assert await auth_service.is_token_revoked("some-jti") is False

    async def test_fails_open_when_redis_unavailable(self, auth_service):
        """If Redis is unavailable, token is treated as NOT revoked."""
        with patch.object(auth_service, "_get_redis", return_value=None):
            assert await auth_service.is_token_revoked("some-jti") is False

    async def test_fails_open_on_redis_error(self, auth_service):
        """Redis errors during check are caught — token treated as valid."""
        mock_redis = AsyncMock()
        mock_redis.exists = AsyncMock(side_effect=ConnectionError("Redis down"))

        with patch.object(auth_service, "_get_redis", return_value=mock_redis):
            assert await auth_service.is_token_revoked("some-jti") is False


# =============================================================================
# verify_token with Revocation
# =============================================================================


@pytest.mark.unit
class TestVerifyTokenRevocation:
    async def test_revoked_token_raises_401(self, auth_service):
        """A revoked token should raise 401 with 'Token has been revoked'."""
        token = auth_service.create_access_token({"sub": "user_123", "email": "a@b.com"})

        with patch.object(auth_service, "is_token_revoked", return_value=True):
            with pytest.raises(HTTPException) as exc_info:
                await auth_service.verify_token(token)
            assert exc_info.value.status_code == 401
            assert "revoked" in exc_info.value.detail.lower()

    async def test_non_revoked_token_passes(self, auth_service):
        """A valid, non-revoked token should pass verification."""
        token = auth_service.create_access_token({"sub": "user_123", "email": "a@b.com"})

        with patch.object(auth_service, "is_token_revoked", return_value=False):
            data = await auth_service.verify_token(token)
            assert data.user_id == "user_123"

    async def test_token_without_jti_still_works(self, auth_service):
        """Tokens without JTI (pre-revocation) should still be accepted."""
        payload = {
            "sub": "user_123",
            "email": "a@b.com",
            "exp": datetime.now(UTC) + timedelta(hours=1),
            "iat": datetime.now(UTC),
            "type": "access",
        }
        token = jose_jwt.encode(payload, auth_service.secret_key, algorithm=auth_service.algorithm)

        # is_token_revoked should NOT be called since there's no JTI
        with patch.object(auth_service, "is_token_revoked") as mock_check:
            data = await auth_service.verify_token(token)
            assert data.user_id == "user_123"
            mock_check.assert_not_called()


# =============================================================================
# Redis Lazy Initialization
# =============================================================================


@pytest.mark.unit
class TestRedisLazyInit:
    async def test_get_redis_returns_none_without_library(self, auth_service):
        """If redis.asyncio is not importable, _get_redis returns None."""
        with patch("services.auth_service.REDIS_AVAILABLE", False):
            result = await auth_service._get_redis()
            assert result is None

    async def test_get_redis_creates_client_lazily(self, auth_service):
        """Redis client is created on first call and reused."""
        mock_client = AsyncMock()

        with (
            patch("services.auth_service.REDIS_AVAILABLE", True),
            patch("services.auth_service.aioredis") as mock_aioredis,
        ):
            mock_aioredis.from_url.return_value = mock_client
            auth_service._redis = None

            client1 = await auth_service._get_redis()
            client2 = await auth_service._get_redis()

        assert client1 is mock_client
        assert client2 is mock_client
        mock_aioredis.from_url.assert_called_once()

    async def test_get_redis_handles_creation_error(self, auth_service):
        """If Redis client creation fails, returns None gracefully."""
        with (
            patch("services.auth_service.REDIS_AVAILABLE", True),
            patch("services.auth_service.aioredis") as mock_aioredis,
        ):
            mock_aioredis.from_url.side_effect = Exception("Connection refused")
            auth_service._redis = None

            result = await auth_service._get_redis()
            assert result is None
