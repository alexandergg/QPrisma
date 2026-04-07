"""
Tests for api/dependencies.py

Covers authentication dependencies (get_current_user, get_current_user_optional),
get_media_or_404, singleton service getters, and storage helpers.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from azure.storage.blob import BlobSasPermissions
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from api.dependencies import (
    build_blob_sas_url,
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
            patch(
                "api.dependencies.create_blob_service_client", return_value=mock_blob_service
            ) as mock_create_blob_service_client,
        ):
            mock_settings.azure.storage_connection_string = None
            mock_settings.azure.storage_account_url = "https://storage.blob.core.windows.net"
            mock_settings.azure.use_managed_identity = True
            result = get_blob_service()

        assert result is mock_blob_service
        mock_create_blob_service_client.assert_called_once_with(
            storage_connection_string=None,
            storage_account_url="https://storage.blob.core.windows.net",
            use_managed_identity=True,
            max_single_put_size=256 * 1024 * 1024,
            max_block_size=100 * 1024 * 1024,
            max_concurrency=8,
        )

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


@pytest.mark.unit
class TestBuildBlobSasUrl:
    def test_uses_user_delegation_key_for_managed_identity(self):
        permission = BlobSasPermissions(read=True)
        start = datetime(2024, 1, 1, 12, 0, tzinfo=UTC)
        expiry = start + timedelta(hours=1)
        mock_blob_service = MagicMock()
        mock_blob_client = MagicMock(
            account_name="mediaaccount",
            url="https://mediaaccount.blob.core.windows.net/media/test.mp4",
        )
        mock_blob_service.get_blob_client.return_value = mock_blob_client
        mock_user_delegation_key = object()
        mock_blob_service.get_user_delegation_key.return_value = mock_user_delegation_key

        with (
            patch("api.dependencies.get_blob_service", return_value=mock_blob_service),
            patch("api.dependencies.get_storage_container_name", return_value="media"),
            patch("api.dependencies.uses_managed_identity_storage", return_value=True),
            patch("api.dependencies.generate_blob_sas", return_value="mi-sas") as mock_generate,
        ):
            result = build_blob_sas_url(
                "test.mp4",
                permission=permission,
                expiry=expiry,
                start=start,
            )

        assert result == "https://mediaaccount.blob.core.windows.net/media/test.mp4?mi-sas"
        mock_blob_service.get_user_delegation_key.assert_called_once_with(
            key_start_time=start,
            key_expiry_time=expiry,
        )
        kwargs = mock_generate.call_args.kwargs
        assert kwargs["account_name"] == "mediaaccount"
        assert kwargs["container_name"] == "media"
        assert kwargs["blob_name"] == "test.mp4"
        assert kwargs["user_delegation_key"] is mock_user_delegation_key
        assert kwargs["permission"] is permission
        assert kwargs["start"] == start
        assert kwargs["expiry"] == expiry
        assert "account_key" not in kwargs

    def test_uses_clock_skew_start_time_for_account_key_fallback(self):
        permission = BlobSasPermissions(read=True)
        expiry = datetime.now(UTC) + timedelta(hours=1)
        mock_blob_service = MagicMock()
        mock_blob_client = MagicMock(
            url="https://mediaaccount.blob.core.windows.net/media/test.mp4"
        )
        mock_blob_service.get_blob_client.return_value = mock_blob_client
        before = datetime.now(UTC)

        with (
            patch("api.dependencies.get_blob_service", return_value=mock_blob_service),
            patch("api.dependencies.get_storage_container_name", return_value="media"),
            patch("api.dependencies.uses_managed_identity_storage", return_value=False),
            patch(
                "api.dependencies.get_storage_account_info",
                return_value=("mediaaccount", "secret-key", "media"),
            ),
            patch(
                "api.dependencies.generate_blob_sas", return_value="fallback-sas"
            ) as mock_generate,
        ):
            result = build_blob_sas_url(
                "test.mp4",
                permission=permission,
                expiry=expiry,
            )
        after = datetime.now(UTC)

        assert result == "https://mediaaccount.blob.core.windows.net/media/test.mp4?fallback-sas"
        kwargs = mock_generate.call_args.kwargs
        assert kwargs["account_name"] == "mediaaccount"
        assert kwargs["account_key"] == "secret-key"
        assert kwargs["container_name"] == "media"
        assert kwargs["blob_name"] == "test.mp4"
        assert kwargs["permission"] is permission
        assert kwargs["expiry"] == expiry
        assert kwargs["start"] is not None
        assert before - timedelta(minutes=6) <= kwargs["start"] <= after - timedelta(minutes=4)
        mock_blob_service.get_user_delegation_key.assert_not_called()

    def test_returns_none_without_blob_service(self):
        permission = BlobSasPermissions(read=True)
        expiry = datetime.now(UTC) + timedelta(hours=1)

        with patch("api.dependencies.get_blob_service", return_value=None):
            result = build_blob_sas_url(
                "test.mp4",
                permission=permission,
                expiry=expiry,
            )

        assert result is None

    def test_returns_none_without_local_signing_credentials(self):
        permission = BlobSasPermissions(read=True)
        expiry = datetime.now(UTC) + timedelta(hours=1)
        mock_blob_service = MagicMock()
        mock_blob_service.get_blob_client.return_value = MagicMock(
            url="https://mediaaccount.blob.core.windows.net/media/test.mp4"
        )

        with (
            patch("api.dependencies.get_blob_service", return_value=mock_blob_service),
            patch("api.dependencies.get_storage_container_name", return_value="media"),
            patch("api.dependencies.uses_managed_identity_storage", return_value=False),
            patch("api.dependencies.get_storage_account_info", return_value=None),
            patch("api.dependencies.generate_blob_sas") as mock_generate,
        ):
            result = build_blob_sas_url(
                "test.mp4",
                permission=permission,
                expiry=expiry,
            )

        assert result is None
        mock_generate.assert_not_called()
