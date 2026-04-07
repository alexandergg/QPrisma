from unittest.mock import MagicMock, patch

import pytest

from core.azure_credentials import (
    build_openai_client_kwargs,
    create_blob_service_client,
    uses_managed_identity_storage,
)


@pytest.mark.unit
class TestBuildOpenAIClientKwargs:
    def test_returns_api_key_kwargs_when_api_key_present(self):
        result = build_openai_client_kwargs(
            endpoint="https://example.openai.azure.com",
            api_key="test-key",
            api_version="2024-08-01-preview",
            use_managed_identity=False,
        )

        assert result == {
            "api_version": "2024-08-01-preview",
            "azure_endpoint": "https://example.openai.azure.com",
            "api_key": "test-key",
        }

    def test_returns_none_when_no_auth_path_is_configured(self):
        result = build_openai_client_kwargs(
            endpoint="https://example.openai.azure.com",
            api_key=None,
            api_version="2024-08-01-preview",
            use_managed_identity=False,
        )

        assert result is None


@pytest.mark.unit
class TestManagedIdentityStorage:
    def test_requires_account_url_without_connection_string(self):
        assert (
            uses_managed_identity_storage(
                use_managed_identity=True,
                storage_account_url="https://storage.blob.core.windows.net",
                storage_connection_string=None,
            )
            is True
        )
        assert (
            uses_managed_identity_storage(
                use_managed_identity=True,
                storage_account_url="https://storage.blob.core.windows.net",
                storage_connection_string="UseDevelopmentStorage=true",
            )
            is False
        )


@pytest.mark.unit
class TestCreateBlobServiceClient:
    def test_uses_connection_string_when_available(self):
        mock_client = MagicMock()

        with patch(
            "core.azure_credentials.BlobServiceClient.from_connection_string",
            return_value=mock_client,
        ) as mock_from_connection_string:
            result = create_blob_service_client(
                storage_connection_string="UseDevelopmentStorage=true",
                storage_account_url=None,
                use_managed_identity=True,
            )

        assert result is mock_client
        mock_from_connection_string.assert_called_once_with("UseDevelopmentStorage=true")

    def test_returns_none_without_storage_auth(self):
        assert (
            create_blob_service_client(
                storage_connection_string=None,
                storage_account_url=None,
                use_managed_identity=False,
            )
            is None
        )
