"""
Tests for services/entra_auth_service.py

Covers Entra ID JWT token validation with mocked JWKS.
"""

from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from models.user import EntraTokenData

# =============================================================================
# EntraAuthService Audience Derivation
# =============================================================================


@pytest.mark.unit
class TestEntraAuthServiceAudienceDerivation:
    """Tests for audience list construction from api_scope."""

    def _make_service(self, client_id: str, api_scope: str):  # noqa: ANN202
        from services.entra_auth_service import EntraAuthService

        svc = EntraAuthService.__new__(EntraAuthService)
        svc.__init__(
            tenant_id="test-tenant-id",
            client_id=client_id,
            api_scope=api_scope,
        )
        return svc

    def test_scope_with_path(self):
        """api://<id>/access_as_user → audiences include both GUID and URI."""
        svc = self._make_service("cid", "api://cid/access_as_user")
        assert svc._audiences == ["cid", "api://cid"]

    def test_bare_uri_without_scope_path(self):
        """api://<id> (no trailing scope) → URI preserved, not truncated."""
        svc = self._make_service("cid", "api://cid")
        assert svc._audiences == ["cid", "api://cid"]

    def test_empty_scope(self):
        """Empty api_scope → only bare client ID."""
        svc = self._make_service("cid", "")
        assert svc._audiences == ["cid"]

    def test_scope_matching_client_id(self):
        """If URI equals client_id, no duplicate added."""
        svc = self._make_service("api://cid", "api://cid/scope")
        assert svc._audiences == ["api://cid"]


# =============================================================================
# EntraAuthService Token Validation
# =============================================================================


@pytest.mark.unit
class TestEntraAuthServiceVerifyToken:
    """Tests for EntraAuthService.verify_token()."""

    @pytest.fixture
    def entra_service(self):
        """Create an EntraAuthService with mocked JWKS client."""
        from services.entra_auth_service import EntraAuthService

        service = EntraAuthService.__new__(EntraAuthService)
        service._tenant_id = "test-tenant-id"
        service._client_id = "test-client-id"
        service._issuers = [
            "https://login.microsoftonline.com/test-tenant-id/v2.0",
            "https://sts.windows.net/test-tenant-id/",
        ]
        service._audiences = ["test-client-id", "api://test-client-id"]
        service._jwks_client = MagicMock()
        return service

    @pytest.mark.asyncio
    async def test_valid_token_returns_entra_data(self, entra_service):
        """Valid Entra ID token should return EntraTokenData."""
        mock_key = MagicMock()
        mock_key.key = "test-signing-key"
        entra_service._jwks_client.get_signing_key_from_jwt.return_value = mock_key

        payload = {
            "oid": "entra-oid-123",
            "preferred_username": "user@example.com",
            "name": "Test User",
            "iss": entra_service._issuers[0],
            "aud": entra_service._client_id,
            "exp": 9999999999,
        }

        with patch("services.entra_auth_service.jwt.decode", return_value=payload):
            result = await entra_service.verify_token("valid.token.here")

        assert isinstance(result, EntraTokenData)
        assert result.oid == "entra-oid-123"
        assert result.email == "user@example.com"
        assert result.name == "Test User"

    @pytest.mark.asyncio
    async def test_expired_token_raises_401(self, entra_service):
        """Expired token should raise 401."""
        import jwt as pyjwt

        mock_key = MagicMock()
        mock_key.key = "test-signing-key"
        entra_service._jwks_client.get_signing_key_from_jwt.return_value = mock_key

        with patch(
            "services.entra_auth_service.jwt.decode",
            side_effect=pyjwt.ExpiredSignatureError("Token expired"),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await entra_service.verify_token("expired.token.here")
            assert exc_info.value.status_code == 401
            assert "expired" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_invalid_token_raises_401(self, entra_service):
        """Invalid/tampered token should raise 401."""
        import jwt as pyjwt

        mock_key = MagicMock()
        mock_key.key = "test-signing-key"
        entra_service._jwks_client.get_signing_key_from_jwt.return_value = mock_key

        with patch(
            "services.entra_auth_service.jwt.decode",
            side_effect=pyjwt.InvalidTokenError("Bad token"),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await entra_service.verify_token("bad.token.here")
            assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_email_fallback_to_email_claim(self, entra_service):
        """When preferred_username is missing, fall back to email claim."""
        mock_key = MagicMock()
        mock_key.key = "test-signing-key"
        entra_service._jwks_client.get_signing_key_from_jwt.return_value = mock_key

        payload = {
            "oid": "entra-oid-456",
            "email": "fallback@example.com",
            "iss": entra_service._issuers[0],
            "aud": entra_service._client_id,
            "exp": 9999999999,
        }

        with patch("services.entra_auth_service.jwt.decode", return_value=payload):
            result = await entra_service.verify_token("valid.token.here")

        assert result.email == "fallback@example.com"


# =============================================================================
# UserProvisioningService
# =============================================================================


@pytest.mark.unit
class TestUserProvisioningService:
    """Tests for auto-provisioning users from Entra ID tokens."""

    @pytest.fixture
    def provisioning_service(self):
        from services.user_provisioning_service import UserProvisioningService

        return UserProvisioningService()

    def test_existing_user_by_entra_oid(self, provisioning_service):
        """User with matching entra_oid should be returned directly."""
        from datetime import UTC, datetime

        mock_user = MagicMock()
        mock_user.id = "user_existing"
        mock_user.email = "existing@example.com"
        mock_user.full_name = "Existing"
        mock_user.is_active = True
        mock_user.is_superuser = False
        mock_user.created_at = datetime(2024, 1, 1, tzinfo=UTC)
        mock_user.updated_at = datetime(2024, 1, 1, tzinfo=UTC)

        mock_db = MagicMock()
        mock_db.get_user_by_entra_oid.return_value = mock_user

        token_data = EntraTokenData(oid="known-oid", email="existing@example.com")

        with patch("services.user_provisioning_service.get_database_service", return_value=mock_db):
            user = provisioning_service.ensure_user_exists(token_data)

        assert user.id == "user_existing"
        mock_db.get_user_by_email.assert_not_called()

    def test_email_match_links_entra_oid(self, provisioning_service):
        """Existing user matched by email should get linked to Entra OID."""
        from datetime import UTC, datetime

        mock_user = MagicMock()
        mock_user.id = "user_local"
        mock_user.email = "local@example.com"
        mock_user.full_name = "Local User"
        mock_user.is_active = True
        mock_user.is_superuser = False
        mock_user.created_at = datetime(2024, 1, 1, tzinfo=UTC)
        mock_user.updated_at = datetime(2024, 1, 1, tzinfo=UTC)

        mock_db = MagicMock()
        mock_db.get_user_by_entra_oid.return_value = None
        mock_db.get_user_by_email.return_value = mock_user

        token_data = EntraTokenData(oid="new-oid", email="local@example.com", name="Local User")

        with patch("services.user_provisioning_service.get_database_service", return_value=mock_db):
            user = provisioning_service.ensure_user_exists(token_data)

        assert user.id == "user_local"
        mock_db.update_user_entra_oid.assert_called_once_with("user_local", "new-oid")

    def test_new_user_auto_provisioned(self, provisioning_service):
        """Unknown user should be auto-created."""
        from datetime import UTC, datetime

        mock_created = MagicMock()
        mock_created.id = "user_new"
        mock_created.email = "new@example.com"
        mock_created.full_name = "New User"
        mock_created.is_active = True
        mock_created.is_superuser = False
        mock_created.created_at = datetime(2024, 1, 1, tzinfo=UTC)
        mock_created.updated_at = datetime(2024, 1, 1, tzinfo=UTC)

        mock_db = MagicMock()
        mock_db.get_user_by_entra_oid.return_value = None
        mock_db.get_user_by_email.return_value = None
        mock_db.create_user.return_value = mock_created

        token_data = EntraTokenData(oid="brand-new-oid", email="new@example.com", name="New User")

        with patch("services.user_provisioning_service.get_database_service", return_value=mock_db):
            user = provisioning_service.ensure_user_exists(token_data)

        assert user.id == "user_new"
        mock_db.create_user.assert_called_once_with(
            email="new@example.com",
            full_name="New User",
            entra_oid="brand-new-oid",
        )

    def test_inactive_user_raises_403(self, provisioning_service):
        """Deactivated user should get 403."""
        mock_user = MagicMock()
        mock_user.is_active = False

        mock_db = MagicMock()
        mock_db.get_user_by_entra_oid.return_value = mock_user

        token_data = EntraTokenData(oid="inactive-oid", email="inactive@example.com")

        with patch("services.user_provisioning_service.get_database_service", return_value=mock_db):
            with pytest.raises(HTTPException) as exc_info:
                provisioning_service.ensure_user_exists(token_data)
            assert exc_info.value.status_code == 403
