"""
Tests for api/dependencies.py

Covers authentication dependencies (get_current_user, get_current_user_optional),
get_media_or_404, singleton service getters, and storage helpers.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from api.dependencies import (
    get_blob_service,
    get_current_user,
    get_current_user_optional,
    get_graph_node_media_or_404,
    get_media_or_404,
    get_openai_client,
    get_storage_account_info,
    get_storage_container_name,
    get_user_media_ids,
)
from models.user import EntraTokenData

# =============================================================================
# get_current_user
# =============================================================================


@pytest.mark.unit
class TestGetCurrentUser:
    async def test_valid_entra_token(self, test_user):
        """Valid Entra ID token should return provisioned user."""
        token_data = EntraTokenData(oid="oid-123", email="test@example.com", name="Test")
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="valid.entra.token")

        mock_entra = MagicMock()
        mock_entra.verify_token = AsyncMock(return_value=token_data)

        mock_provisioning = MagicMock()
        mock_provisioning.ensure_user_exists.return_value = test_user

        with (
            patch("services.entra_auth_service.get_entra_auth_service", return_value=mock_entra),
            patch(
                "services.user_provisioning_service.get_user_provisioning_service",
                return_value=mock_provisioning,
            ),
        ):
            user = await get_current_user(credentials)

        assert user.id == test_user.id

    async def test_invalid_token_raises_401(self):
        """Invalid token should raise 401."""
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="bad.token")

        mock_entra = MagicMock()
        mock_entra.verify_token = AsyncMock(
            side_effect=HTTPException(status_code=401, detail="Invalid token")
        )

        with patch("services.entra_auth_service.get_entra_auth_service", return_value=mock_entra):
            with pytest.raises(HTTPException) as exc_info:
                await get_current_user(credentials)
            assert exc_info.value.status_code == 401


# =============================================================================
# get_current_user_optional
# =============================================================================


@pytest.mark.unit
class TestGetCurrentUserOptional:
    async def test_valid_token(self, test_user):
        token_data = EntraTokenData(oid="oid-123", email="test@example.com")
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="valid.entra.token")

        mock_entra = MagicMock()
        mock_entra.verify_token = AsyncMock(return_value=token_data)

        mock_provisioning = MagicMock()
        mock_provisioning.ensure_user_exists.return_value = test_user

        with (
            patch("services.entra_auth_service.get_entra_auth_service", return_value=mock_entra),
            patch(
                "services.user_provisioning_service.get_user_provisioning_service",
                return_value=mock_provisioning,
            ),
        ):
            user = await get_current_user_optional(credentials)

        assert user is not None
        assert user.id == test_user.id

    async def test_no_credentials_returns_none(self):
        user = await get_current_user_optional(None)
        assert user is None

    async def test_invalid_token_returns_none(self):
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="bad.token")

        mock_entra = MagicMock()
        mock_entra.verify_token = AsyncMock(side_effect=Exception("Bad token"))

        with patch("services.entra_auth_service.get_entra_auth_service", return_value=mock_entra):
            user = await get_current_user_optional(credentials)

        assert user is None


# =============================================================================
# get_media_or_404
# =============================================================================


@pytest.mark.unit
class TestGetMediaOr404:
    def test_existing_owned_media(self, test_user):
        mock_media = MagicMock()
        mock_media.user_id = test_user.id

        mock_db = MagicMock()
        mock_db.get_media.return_value = mock_media

        with patch("api.dependencies.get_database_service", return_value=mock_db):
            result = get_media_or_404("media_123", test_user)

        assert result is mock_media

    def test_not_found_raises_404(self, test_user):
        mock_db = MagicMock()
        mock_db.get_media.return_value = None

        with patch("api.dependencies.get_database_service", return_value=mock_db):
            with pytest.raises(HTTPException) as exc_info:
                get_media_or_404("nonexistent", test_user)
            assert exc_info.value.status_code == 404

    def test_forbidden_raises_403(self, test_user):
        mock_media = MagicMock()
        mock_media.user_id = "other_user_id"

        mock_db = MagicMock()
        mock_db.get_media.return_value = mock_media

        with patch("api.dependencies.get_database_service", return_value=mock_db):
            with pytest.raises(HTTPException) as exc_info:
                get_media_or_404("media_123", test_user)
            assert exc_info.value.status_code == 403

    def test_superuser_can_access_others_media(self, superuser):
        mock_media = MagicMock()
        mock_media.user_id = "other_user_id"

        mock_db = MagicMock()
        mock_db.get_media.return_value = mock_media

        with patch("api.dependencies.get_database_service", return_value=mock_db):
            result = get_media_or_404("media_123", superuser, allow_superuser=True)

        assert result is mock_media

    def test_superuser_denied_when_allow_superuser_false(self, superuser):
        mock_media = MagicMock()
        mock_media.user_id = "other_user_id"

        mock_db = MagicMock()
        mock_db.get_media.return_value = mock_media

        with patch("api.dependencies.get_database_service", return_value=mock_db):
            with pytest.raises(HTTPException) as exc_info:
                get_media_or_404("media_123", superuser, allow_superuser=False)
            assert exc_info.value.status_code == 403


@pytest.mark.unit
class TestGetUserMediaIds:
    def test_filters_to_processed_media_when_requested(self, test_user):
        mock_db = MagicMock()
        mock_db.get_user_media_ids.return_value = ["vid-1"]

        with patch("api.dependencies.get_database_service", return_value=mock_db):
            result = get_user_media_ids(test_user, processed_only=True)

        assert result == ["vid-1"]
        mock_db.get_user_media_ids.assert_called_once_with(test_user.id, processed_only=True)


@pytest.mark.unit
class TestGetGraphNodeMediaOr404:
    def test_resolves_node_to_media_and_enforces_ownership(self, test_user):
        mock_graph = MagicMock()
        mock_graph.get_node_video_id.return_value = "media_123"

        mock_media = MagicMock()
        mock_media.user_id = test_user.id

        with (
            patch("api.dependencies.get_knowledge_graph_service", return_value=mock_graph),
            patch("api.dependencies.get_media_or_404", return_value=mock_media) as mock_get_media,
        ):
            result = get_graph_node_media_or_404("node-1", test_user)

        assert result is mock_media
        mock_get_media.assert_called_once_with("media_123", test_user, allow_superuser=True)

    def test_raises_404_when_node_is_unknown(self, test_user):
        mock_graph = MagicMock()
        mock_graph.get_node_video_id.return_value = None

        with (
            patch("api.dependencies.get_knowledge_graph_service", return_value=mock_graph),
            pytest.raises(HTTPException) as exc_info,
        ):
            get_graph_node_media_or_404("missing-node", test_user)

        assert exc_info.value.status_code == 404


# =============================================================================
# Singleton Getters
# =============================================================================


@pytest.mark.unit
class TestSingletonGetters:
    def test_blob_service_none_without_config(self):
        import api.dependencies as deps

        deps._blob_service = None
        with patch("api.dependencies.settings") as mock_settings:
            mock_settings.azure.storage_connection_string = None
            mock_settings.azure.storage_account_url = None
            mock_settings.azure.use_managed_identity = False
            result = get_blob_service()
        assert result is None

    def test_openai_client_none_without_config(self):
        import api.dependencies as deps

        deps._openai_client = None
        with patch("api.dependencies.settings") as mock_settings:
            mock_settings.azure.openai_endpoint = None
            mock_settings.azure.openai_api_key = None
            mock_settings.azure.use_managed_identity = False
            mock_settings.azure.openai_api_version = "2024-08-01-preview"
            result = get_openai_client()
        assert result is None

    def test_blob_service_uses_managed_identity_account_url(self):
        import api.dependencies as deps

        deps._blob_service = None
        mock_blob_service = MagicMock()

        with (
            patch("api.dependencies.settings") as mock_settings,
            patch("api.dependencies.create_blob_service_client", return_value=mock_blob_service),
        ):
            mock_settings.azure.storage_connection_string = None
            mock_settings.azure.storage_account_url = "https://storage.blob.core.windows.net"
            mock_settings.azure.use_managed_identity = True
            result = get_blob_service()

        assert result is mock_blob_service

    def test_openai_client_uses_managed_identity(self):
        import api.dependencies as deps

        deps._openai_client = None
        mock_client = MagicMock()

        with (
            patch("api.dependencies.settings") as mock_settings,
            patch("api.dependencies.AzureOpenAI", return_value=mock_client) as mock_ctor,
            patch("api.dependencies.build_openai_client_kwargs") as mock_kwargs_builder,
        ):
            mock_settings.azure.openai_endpoint = "https://foo.openai.azure.com"
            mock_settings.azure.openai_api_key = None
            mock_settings.azure.use_managed_identity = True
            mock_settings.azure.openai_api_version = "2024-08-01-preview"
            mock_kwargs_builder.return_value = {
                "azure_endpoint": "https://foo.openai.azure.com",
                "api_version": "2024-08-01-preview",
                "azure_ad_token_provider": object(),
            }

            result = get_openai_client()

        assert result is mock_client
        mock_ctor.assert_called_once()

    def test_storage_container_name(self):
        name = get_storage_container_name()
        assert isinstance(name, str)
        assert len(name) > 0


# =============================================================================
# get_storage_account_info
# =============================================================================


@pytest.mark.unit
class TestGetStorageAccountInfo:
    def test_parses_connection_string(self):
        conn = "DefaultEndpointsProtocol=https;AccountName=myaccount;AccountKey=mykey==;EndpointSuffix=core.windows.net"
        with patch("api.dependencies.settings") as mock_settings:
            mock_settings.azure.storage_connection_string = conn
            mock_settings.azure.storage_container_name = "media"
            result = get_storage_account_info()

        assert result is not None
        assert result[0] == "myaccount"
        assert result[1] == "mykey=="
        assert result[2] == "media"

    def test_returns_none_on_missing(self):
        with patch("api.dependencies.settings") as mock_settings:
            mock_settings.azure.storage_connection_string = None
            result = get_storage_account_info()

        assert result is None

    def test_returns_none_on_malformed(self):
        with patch("api.dependencies.settings") as mock_settings:
            mock_settings.azure.storage_connection_string = "garbage_string"
            result = get_storage_account_info()

        assert result is None
