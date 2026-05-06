"""Azure client and storage helper dependencies for API routes."""

import asyncio
import re
from datetime import UTC, datetime, timedelta
from functools import partial

from azure.storage.blob import BlobSasPermissions


def get_blob_service():
    """Get or create Blob Storage client with optimized transfer settings."""
    import api.dependencies as deps

    if deps._blob_service is None:
        deps._blob_service = deps.create_blob_service_client(
            storage_connection_string=deps.settings.azure.storage_connection_string,
            storage_account_url=deps.settings.azure.storage_account_url,
            use_managed_identity=deps.settings.azure.use_managed_identity,
            max_single_put_size=256 * 1024 * 1024,
            max_block_size=100 * 1024 * 1024,
            max_concurrency=8,
        )
    return deps._blob_service


def get_openai_client():
    """Get or create Azure OpenAI client (sync)."""
    import api.dependencies as deps

    if deps._openai_client is None:
        client_kwargs = deps.build_openai_client_kwargs(
            endpoint=deps.settings.azure.openai_endpoint,
            api_key=deps.settings.azure.openai_api_key,
            api_version=deps.settings.azure.openai_api_version,
            use_managed_identity=deps.settings.azure.use_managed_identity,
        )
        if client_kwargs is not None:
            deps._openai_client = deps.AzureOpenAI(**client_kwargs)
    return deps._openai_client


def get_async_openai_client():
    """Get or create Azure OpenAI client (async)."""
    import api.dependencies as deps

    if deps._async_openai_client is None:
        client_kwargs = deps.build_openai_client_kwargs(
            endpoint=deps.settings.azure.openai_endpoint,
            api_key=deps.settings.azure.openai_api_key,
            api_version=deps.settings.azure.openai_api_version,
            use_managed_identity=deps.settings.azure.use_managed_identity,
        )
        if client_kwargs is not None:
            deps._async_openai_client = deps.AsyncAzureOpenAI(**client_kwargs)
    return deps._async_openai_client


def get_storage_container_name() -> str:
    """Get Azure Storage container name for media."""
    import api.dependencies as deps

    return deps.settings.azure.storage_container_name


def get_storage_account_info() -> tuple[str, str, str] | None:
    """Extract (account_name, account_key, container_name) from connection string."""
    import api.dependencies as deps

    conn_string = deps.settings.azure.storage_connection_string or ""
    account_name_match = re.search(r"AccountName=([^;]+)", conn_string)
    account_key_match = re.search(r"AccountKey=([^;]+)", conn_string)

    if not (account_name_match and account_key_match):
        return None

    return (
        account_name_match.group(1),
        account_key_match.group(1),
        deps.get_storage_container_name(),
    )


def build_blob_sas_url(
    blob_name: str,
    *,
    permission: BlobSasPermissions,
    expiry: datetime,
    start: datetime | None = None,
    container_name: str | None = None,
) -> str | None:
    """Build a blob SAS URL using managed identity or local fallback credentials."""
    import api.dependencies as deps

    blob_service = deps.get_blob_service()
    if not blob_service:
        return None

    resolved_container = container_name or deps.get_storage_container_name()
    blob_client = blob_service.get_blob_client(container=resolved_container, blob=blob_name)
    start_time = start or (datetime.now(UTC) - timedelta(minutes=5))

    if deps.uses_managed_identity_storage(
        use_managed_identity=deps.settings.azure.use_managed_identity,
        storage_account_url=deps.settings.azure.storage_account_url,
        storage_connection_string=deps.settings.azure.storage_connection_string,
    ):
        user_delegation_key = blob_service.get_user_delegation_key(
            key_start_time=start_time,
            key_expiry_time=expiry,
        )
        sas_token = deps.generate_blob_sas(
            account_name=blob_client.account_name,
            container_name=resolved_container,
            blob_name=blob_name,
            user_delegation_key=user_delegation_key,
            permission=permission,
            start=start_time,
            expiry=expiry,
        )
        return f"{blob_client.url}?{sas_token}"

    account_info = deps.get_storage_account_info()
    if not account_info:
        return None

    account_name, account_key, _ = account_info
    sas_token = deps.generate_blob_sas(
        account_name=account_name,
        container_name=resolved_container,
        blob_name=blob_name,
        account_key=account_key,
        permission=permission,
        start=start_time,
        expiry=expiry,
    )
    return f"{blob_client.url}?{sas_token}"


async def build_blob_sas_url_async(
    blob_name: str,
    *,
    permission: BlobSasPermissions,
    expiry: datetime,
    start: datetime | None = None,
    container_name: str | None = None,
) -> str | None:
    """Build a blob SAS URL without blocking the event loop."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None,
        partial(
            build_blob_sas_url,
            blob_name,
            permission=permission,
            expiry=expiry,
            start=start,
            container_name=container_name,
        ),
    )
