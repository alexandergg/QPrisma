"""
Tests for api/dependencies.py

Covers authentication dependencies (get_current_user, get_current_user_optional),
get_media_or_404, singleton service getters, and storage helpers.
"""

from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from api.dependencies import (
    get_auth_service,
    get_blob_service,
    get_current_user,
    get_current_user_optional,
    get_media_or_404,
    get_openai_client,
    get_storage_account_info,
    get_storage_container_name,
)

# =============================================================================
# get_current_user
# =============================================================================


@pytest.mark.unit
class TestGetCurrentUser:
    async def test_valid_token(self, auth_service, test_user):
        token = auth_service.create_access_token(
            {"sub": test_user.id, "email": test_user.email}
        )
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

        with patch("api.dependencies.get_auth_service", return_value=auth_service):
            user = await get_current_user(credentials)

        assert user.id == test_user.id
        assert user.email == test_user.email

    async def test_expired_token_raises_401(self, auth_service):
        from datetime import timedelta

        from freezegun import freeze_time

        with freeze_time("2024-01-01"):
            token = auth_service.create_access_token(
                {"sub": "user_123"}, expires_delta=timedelta(seconds=1)
            )

        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

        with (
            freeze_time("2024-01-02"),
            patch("api.dependencies.get_auth_service", return_value=auth_service),
            pytest.raises(HTTPException) as exc_info,
        ):
            await get_current_user(credentials)
        assert exc_info.value.status_code == 401

    async def test_invalid_token_raises_401(self, auth_service):
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="garbage.token.here")

        with patch("api.dependencies.get_auth_service", return_value=auth_service):
            with pytest.raises(HTTPException) as exc_info:
                await get_current_user(credentials)
            assert exc_info.value.status_code == 401


# =============================================================================
# get_current_user_optional
# =============================================================================


@pytest.mark.unit
class TestGetCurrentUserOptional:
    async def test_valid_token(self, auth_service, test_user):
        token = auth_service.create_access_token(
            {"sub": test_user.id, "email": test_user.email}
        )
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

        with patch("api.dependencies.get_auth_service", return_value=auth_service):
            user = await get_current_user_optional(credentials)

        assert user is not None
        assert user.id == test_user.id

    async def test_no_credentials_returns_none(self):
        user = await get_current_user_optional(None)
        assert user is None

    async def test_invalid_token_returns_none(self, auth_service):
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="bad.token")

        with patch("api.dependencies.get_auth_service", return_value=auth_service):
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
            result = get_blob_service()
        assert result is None

    def test_openai_client_none_without_config(self):
        import api.dependencies as deps

        deps._openai_client = None
        with patch("api.dependencies.settings") as mock_settings:
            mock_settings.azure.openai_endpoint = None
            mock_settings.azure.openai_api_key = None
            result = get_openai_client()
        assert result is None

    def test_auth_service_returns_instance(self):
        import api.dependencies as deps

        deps._auth_service = None
        service = get_auth_service()
        assert service is not None
        # Calling again returns same instance
        assert get_auth_service() is service

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
