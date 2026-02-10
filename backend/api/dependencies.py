"""
Shared Dependencies for API Routes

This module contains shared dependencies, utilities, and service getters
that are used across multiple route modules.
"""

import re

from azure.storage.blob import BlobServiceClient
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from openai import AsyncAzureOpenAI, AzureOpenAI

from core.config import settings
from models.user import User
from services.auth_service import AuthService
from services.database_service import get_database_service

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
_video_processor = None
_auth_service: AuthService | None = None


def get_blob_service() -> BlobServiceClient | None:
    """Get or create Blob Storage client with optimized transfer settings."""
    global _blob_service
    if _blob_service is None:
        conn_string = settings.azure.storage_connection_string
        if conn_string:
            _blob_service = BlobServiceClient.from_connection_string(
                conn_string,
                max_single_put_size=256 * 1024 * 1024,  # 256MB: use blocks above this
                max_block_size=100 * 1024 * 1024,  # 100MB blocks for parallel transfer
                max_concurrency=8,  # parallel threads per blob operation
            )
    return _blob_service


def get_openai_client() -> AzureOpenAI | None:
    """Get or create Azure OpenAI client (sync)."""
    global _openai_client
    if _openai_client is None:
        endpoint = settings.azure.openai_endpoint
        api_key = settings.azure.openai_api_key
        if endpoint and api_key:
            _openai_client = AzureOpenAI(
                azure_endpoint=endpoint,
                api_key=api_key,
                api_version=settings.azure.openai_api_version,
            )
    return _openai_client


def get_async_openai_client() -> AsyncAzureOpenAI | None:
    """Get or create Azure OpenAI client (async)."""
    global _async_openai_client
    if _async_openai_client is None:
        endpoint = settings.azure.openai_endpoint
        api_key = settings.azure.openai_api_key
        if endpoint and api_key:
            _async_openai_client = AsyncAzureOpenAI(
                azure_endpoint=endpoint,
                api_key=api_key,
                api_version=settings.azure.openai_api_version,
            )
    return _async_openai_client


def get_video_processor():
    """Get or create Video Processor service."""
    global _video_processor
    if _video_processor is None:
        blob_service = get_blob_service()
        openai_client = get_openai_client()
        if blob_service and openai_client:
            from services.video_processor import VideoProcessor

            _video_processor = VideoProcessor(
                openai_client=openai_client,
                blob_service=blob_service,
                container_name=settings.azure.storage_container_name,
            )
    return _video_processor


def get_auth_service() -> AuthService:
    """Get or create Auth Service."""
    global _auth_service
    if _auth_service is None:
        _auth_service = AuthService()
    return _auth_service


_graph_search_service = None


def get_graph_search_service():
    """Get or create Graph Search Service (VideoRAG-style hybrid search)."""
    global _graph_search_service
    if _graph_search_service is None:
        from services.graph_search_service import GraphSearchService

        _graph_search_service = GraphSearchService()
        # Initialize vector indexes on first use
        try:
            _graph_search_service.initialize_vector_indexes()
        except Exception:
            pass  # Neo4j may not be connected yet
    return _graph_search_service


def get_storage_container_name() -> str:
    """Get Azure Storage container name for media."""
    return settings.azure.storage_container_name


def get_storage_account_info() -> tuple[str, str, str] | None:
    """Extract (account_name, account_key, container_name) from connection string.

    Returns None if the connection string is missing or malformed.
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


# =============================================================================
# Authentication Dependency
# =============================================================================

# Optional security scheme that doesn't require authentication
security_optional = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> User:
    """
    Validate JWT token and return current user.

    Raises:
        HTTPException: 401 if token is invalid or expired
    """
    from datetime import UTC, datetime

    auth_service = get_auth_service()

    try:
        token_data = auth_service.verify_token(credentials.credentials)
        # Create User from token data
        now = datetime.now(UTC)
        return User(
            id=token_data.user_id,
            email=token_data.email or "",
            full_name=None,
            is_active=True,
            is_superuser=False,
            created_at=now,
            updated_at=now,
        )
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token")


async def get_current_user_optional(
    credentials: HTTPAuthorizationCredentials | None = Depends(security_optional),
) -> User | None:
    """
    Optionally validate JWT token and return current user.

    Returns None if no token is provided or if token is invalid.
    Does not raise exceptions - useful for endpoints that work with or without auth.
    """
    if credentials is None:
        return None

    from datetime import UTC, datetime

    auth_service = get_auth_service()

    try:
        token_data = auth_service.verify_token(credentials.credentials)
        now = datetime.now(UTC)
        return User(
            id=token_data.user_id,
            email=token_data.email or "",
            full_name=None,
            is_active=True,
            is_superuser=False,
            created_at=now,
            updated_at=now,
        )
    except Exception:
        # Token invalid or expired - return None instead of raising
        return None
