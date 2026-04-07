"""Shared Azure credential helpers for runtime service clients."""

import logging
from functools import lru_cache
from typing import Any

from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from azure.storage.blob import BlobServiceClient

logger = logging.getLogger(__name__)

_OPENAI_SCOPE = "https://cognitiveservices.azure.com/.default"
_logged_paths: set[str] = set()


def _log_auth_path(service: str, path: str) -> None:
    key = f"{service}:{path}"
    if key in _logged_paths:
        return
    logger.info("Using %s auth path for %s", path, service)
    _logged_paths.add(key)


@lru_cache(maxsize=1)
def get_default_azure_credential() -> DefaultAzureCredential:
    """Return a shared DefaultAzureCredential instance."""
    _log_auth_path("azure", "managed-identity")
    return DefaultAzureCredential()


@lru_cache(maxsize=1)
def get_openai_token_provider():
    """Return a cached Azure OpenAI bearer token provider."""
    _log_auth_path("azure-openai", "managed-identity")
    return get_bearer_token_provider(get_default_azure_credential(), _OPENAI_SCOPE)


def build_openai_client_kwargs(
    *,
    endpoint: str | None,
    api_key: str | None,
    api_version: str,
    use_managed_identity: bool,
) -> dict[str, Any] | None:
    """Build Azure OpenAI client kwargs from the provided auth configuration."""
    if not endpoint:
        return None

    client_kwargs: dict[str, Any] = {
        "api_version": api_version,
        "azure_endpoint": endpoint,
    }
    if api_key:
        _log_auth_path("azure-openai", "api-key")
        client_kwargs["api_key"] = api_key
        return client_kwargs

    if use_managed_identity:
        client_kwargs["azure_ad_token_provider"] = get_openai_token_provider()
        return client_kwargs

    return None


def uses_managed_identity_storage(
    *,
    use_managed_identity: bool,
    storage_account_url: str | None,
    storage_connection_string: str | None,
) -> bool:
    """Return True when Blob auth should use managed identity."""
    return bool(
        use_managed_identity and storage_account_url and not storage_connection_string
    )


def create_blob_service_client(
    *,
    storage_connection_string: str | None,
    storage_account_url: str | None,
    use_managed_identity: bool,
    **kwargs: Any,
) -> BlobServiceClient | None:
    """Create a BlobServiceClient from the provided storage auth configuration."""
    if storage_connection_string:
        _log_auth_path("azure-storage", "connection-string")
        return BlobServiceClient.from_connection_string(
            storage_connection_string,
            **kwargs,
        )

    if use_managed_identity and storage_account_url:
        _log_auth_path("azure-storage", "managed-identity")
        return BlobServiceClient(
            account_url=storage_account_url.rstrip("/"),
            credential=get_default_azure_credential(),
            **kwargs,
        )

    return None
