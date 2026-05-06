"""
Shared Dependencies for API Routes

This module contains shared dependencies, utilities, and service getters
that are used across multiple route modules.
"""

import asyncio
import logging
import re
import secrets
from datetime import UTC, datetime, timedelta
from functools import partial

from azure.storage.blob import BlobSasPermissions, BlobServiceClient, generate_blob_sas
from fastapi import Depends, Header, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from openai import AsyncAzureOpenAI, AzureOpenAI

from core.azure_credentials import (
    build_openai_client_kwargs,
    create_blob_service_client,
    uses_managed_identity_storage,
)
from core.config import settings
from models.user import User
from services.database_service import get_database_service

logger = logging.getLogger(__name__)

# =============================================================================
# Security
# =============================================================================

security = HTTPBearer()


# =============================================================================
# Service Singletons
# =============================================================================

_blob_service: BlobServiceClient | None = None
_openai_client: AzureOpenAI | None = None
_async_openai_client: AsyncAzureOpenAI | None = None


def get_blob_service() -> BlobServiceClient | None:
    """Get or create Blob Storage client with optimized transfer settings."""
    global _blob_service
    if _blob_service is None:
        _blob_service = create_blob_service_client(
            storage_connection_string=settings.azure.storage_connection_string,
            storage_account_url=settings.azure.storage_account_url,
            use_managed_identity=settings.azure.use_managed_identity,
            max_single_put_size=256 * 1024 * 1024,  # 256MB: use blocks above this
            max_block_size=100 * 1024 * 1024,  # 100MB blocks for parallel transfer
            max_concurrency=8,  # parallel threads per blob operation
        )
    return _blob_service


def get_openai_client() -> AzureOpenAI | None:
    """Get or create Azure OpenAI client (sync)."""
    global _openai_client
    if _openai_client is None:
        client_kwargs = build_openai_client_kwargs(
            endpoint=settings.azure.openai_endpoint,
            api_key=settings.azure.openai_api_key,
            api_version=settings.azure.openai_api_version,
            use_managed_identity=settings.azure.use_managed_identity,
        )
        if client_kwargs is not None:
            _openai_client = AzureOpenAI(**client_kwargs)
    return _openai_client


def get_async_openai_client() -> AsyncAzureOpenAI | None:
    """Get or create Azure OpenAI client (async)."""
    global _async_openai_client
    if _async_openai_client is None:
        client_kwargs = build_openai_client_kwargs(
            endpoint=settings.azure.openai_endpoint,
            api_key=settings.azure.openai_api_key,
            api_version=settings.azure.openai_api_version,
            use_managed_identity=settings.azure.use_managed_identity,
        )
        if client_kwargs is not None:
            _async_openai_client = AsyncAzureOpenAI(**client_kwargs)
    return _async_openai_client


_knowledge_graph_service = None


def get_knowledge_graph_service():
    """Get or create Knowledge Graph Service, ensuring it is connected.

    For async contexts (route handlers, async services), prefer
    :func:`get_async_graph_service` which returns the non-blocking facade.
    """
    global _knowledge_graph_service
    if _knowledge_graph_service is None:
        from services.knowledge_graph import (
            get_knowledge_graph_service as _get_kg_service,
        )

        _knowledge_graph_service = _get_kg_service()
        if not _knowledge_graph_service.is_connected:
            _knowledge_graph_service.connect()
    return _knowledge_graph_service


def get_async_graph_service():
    """Return the :class:`AsyncKnowledgeGraphFacade` singleton.

    The facade wraps the sync :class:`KnowledgeGraphService` with
    ``asyncio.to_thread()`` so that route handlers never block the
    event loop on Neo4j I/O.

    The underlying sync service is eagerly connected at startup via
    the FastAPI lifespan handler in ``api/main.py``.
    """
    from services.async_graph_facade import get_async_knowledge_graph_facade

    return get_async_knowledge_graph_facade()


def get_graph_search_service():
    """Get or create Graph Search Service (VideoRAG-style hybrid search).

    Delegates to the canonical service-layer singleton to avoid dual-instance
    initialization with different lifecycle paths.
    """
    from services.graph_search_service import (
        get_graph_search_service as _canonical_getter,
    )

    return _canonical_getter()


_graph_route_service = None


def get_graph_route_service():
    """Get or create Graph Route Service (business logic for graph routes)."""
    global _graph_route_service
    if _graph_route_service is None:
        from services.graph_route_service import GraphRouteService

        _graph_route_service = GraphRouteService(
            knowledge_graph_service=get_knowledge_graph_service(),
            graph_search_service=get_graph_search_service(),
        )
    return _graph_route_service


_hierarchical_context_service = None
_community_detection_service = None


def get_hierarchical_context_service():
    """Get or create Hierarchical Context Service."""
    global _hierarchical_context_service
    if _hierarchical_context_service is None:
        from services.embedding_service import get_embedding_service
        from services.hierarchical_context_service import (
            get_hierarchical_context_service as _get_hcs,
        )

        graph_svc = get_knowledge_graph_service()
        embedding_svc = get_embedding_service()
        _hierarchical_context_service = _get_hcs(
            graph_service=graph_svc, embedding_service=embedding_svc
        )
    return _hierarchical_context_service


_hierarchical_query_service = None


def get_hierarchical_query_service():
    """Get or create Hierarchical Query Service."""
    global _hierarchical_query_service
    if _hierarchical_query_service is None:
        from services.embedding_service import get_embedding_service
        from services.hierarchical_query_service import (
            get_hierarchical_query_service as _get_hqs,
        )

        graph_svc = get_knowledge_graph_service()
        embedding_svc = get_embedding_service()
        _hierarchical_query_service = _get_hqs(
            graph_service=graph_svc, embedding_service=embedding_svc
        )
    return _hierarchical_query_service


async def get_tool_artifact_service():
    """Get ToolArtifactService singleton."""
    from services.tool_artifact_service import (
        get_tool_artifact_service as _get_tool_artifact_service,
    )

    return await _get_tool_artifact_service()


def get_community_detection_service():
    """Get or create Community Detection Service."""
    global _community_detection_service
    if _community_detection_service is None:
        from services.community_detection_service import (
            get_community_detection_service as _get_cds,
        )

        _community_detection_service = _get_cds()
    return _community_detection_service


def get_storage_container_name() -> str:
    """Get Azure Storage container name for media."""
    return settings.azure.storage_container_name


def get_storage_account_info() -> tuple[str, str, str] | None:
    """Extract (account_name, account_key, container_name) from connection string.

    This remains as a local/test fallback for SAS signing when managed identity
    storage auth is not enabled.
    """
    conn_string = settings.azure.storage_connection_string or ""
    account_name_match = re.search(r"AccountName=([^;]+)", conn_string)
    account_key_match = re.search(r"AccountKey=([^;]+)", conn_string)

    if not (account_name_match and account_key_match):
        return None

    return (
        account_name_match.group(1),
        account_key_match.group(1),
        get_storage_container_name(),
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
    blob_service = get_blob_service()
    if not blob_service:
        return None

    resolved_container = container_name or get_storage_container_name()
    blob_client = blob_service.get_blob_client(container=resolved_container, blob=blob_name)
    start_time = start or (datetime.now(UTC) - timedelta(minutes=5))

    if uses_managed_identity_storage(
        use_managed_identity=settings.azure.use_managed_identity,
        storage_account_url=settings.azure.storage_account_url,
        storage_connection_string=settings.azure.storage_connection_string,
    ):
        user_delegation_key = blob_service.get_user_delegation_key(
            key_start_time=start_time,
            key_expiry_time=expiry,
        )
        sas_token = generate_blob_sas(
            account_name=blob_client.account_name,
            container_name=resolved_container,
            blob_name=blob_name,
            user_delegation_key=user_delegation_key,
            permission=permission,
            start=start_time,
            expiry=expiry,
        )
        return f"{blob_client.url}?{sas_token}"

    account_info = get_storage_account_info()
    if not account_info:
        return None

    account_name, account_key, _ = account_info
    sas_token = generate_blob_sas(
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


def get_media_or_404(
    media_id: str,
    current_user: User,
    *,
    allow_superuser: bool = True,
):
    """Fetch media and enforce ownership."""
    db = get_database_service()
    media = db.get_media(media_id)
    if not media:
        raise HTTPException(status_code=404, detail="Media not found")
    if media.user_id != current_user.id and (not allow_superuser or not current_user.is_superuser):
        raise HTTPException(status_code=403, detail="Not authorized")
    return media


def get_user_media_ids(
    current_user: User,
    *,
    processed_only: bool = False,
) -> list[str]:
    """Return the current user's media IDs, optionally restricted to processed items."""
    db = get_database_service()
    return db.get_user_media_ids(current_user.id, processed_only=processed_only)


def get_graph_node_media_or_404(
    node_id: str,
    current_user: User,
    *,
    allow_superuser: bool = True,
):
    """Resolve a graph node to its video and enforce media ownership."""
    graph_service = get_knowledge_graph_service()
    video_id = graph_service.get_node_video_id(node_id)
    if not video_id:
        raise HTTPException(status_code=404, detail="Graph node not found")
    return get_media_or_404(video_id, current_user, allow_superuser=allow_superuser)


# =============================================================================
# Authentication Dependency
# =============================================================================

# Optional security scheme that doesn't require authentication
security_optional = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> User:
    """
    Validate Entra ID Bearer token and return current user.

    Auto-provisions user in PostgreSQL on first login (email-matched to existing records).

    Raises:
        HTTPException: 401 if token is invalid or expired
    """
    from services.entra_auth_service import get_entra_auth_service
    from services.user_provisioning_service import get_user_provisioning_service

    try:
        token_data = await get_entra_auth_service().verify_token(credentials.credentials)
        return get_user_provisioning_service().ensure_user_exists(token_data)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token") from None


async def get_current_user_optional(
    credentials: HTTPAuthorizationCredentials | None = Depends(security_optional),
) -> User | None:
    """
    Optionally validate Entra ID token and return current user.

    Returns None if no token is provided or if token is invalid.
    Does not raise exceptions - useful for endpoints that work with or without auth.
    """
    if credentials is None:
        return None

    from services.entra_auth_service import get_entra_auth_service
    from services.user_provisioning_service import get_user_provisioning_service

    try:
        token_data = await get_entra_auth_service().verify_token(credentials.credentials)
        return get_user_provisioning_service().ensure_user_exists(token_data)
    except Exception:
        return None


async def require_benchmark_operator(
    current_user: User | None = Depends(get_current_user_optional),
    benchmark_token: str | None = Header(default=None, alias="X-Benchmark-Token"),
) -> User | None:
    """Authorize benchmark automation via superuser bearer token or shared secret."""
    if current_user and current_user.is_superuser:
        return current_user

    configured_token = settings.benchmark.api_token
    if (
        configured_token
        and benchmark_token
        and secrets.compare_digest(benchmark_token, configured_token)
    ):
        return None

    if current_user is not None:
        raise HTTPException(status_code=403, detail="Benchmark automation requires admin access")
    raise HTTPException(status_code=401, detail="Benchmark automation credentials required")
