"""
Shared Dependencies for API Routes

This module contains shared dependencies, utilities, and service getters
that are used across multiple route modules.
"""

import logging
import re

from azure.storage.blob import BlobServiceClient
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from openai import AsyncAzureOpenAI, AzureOpenAI

from core.config import settings
from models.user import User
from services.auth_service import AuthService
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
_video_processor = None
_auth_service: AuthService | None = None
_pyav_extractor = None


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


def get_pyav_extractor():
    """Get or create PyAVFrameExtractor singleton.

    Returns ``None`` when the ``av`` package is not installed.
    """
    global _pyav_extractor
    if _pyav_extractor is None:
        try:
            from services.pyav_extractor import PyAVFrameExtractor, is_pyav_available

            if is_pyav_available():
                _pyav_extractor = PyAVFrameExtractor()
            else:
                logger.debug("PyAV not available — get_pyav_extractor() returning None")
        except ImportError:
            logger.debug("pyav_extractor module not found — returning None")
    return _pyav_extractor


def get_auth_service() -> AuthService:
    """Get or create Auth Service."""
    global _auth_service
    if _auth_service is None:
        _auth_service = AuthService()
    return _auth_service


_knowledge_graph_service = None

_scene_detect_service = None

_video_decoder = None


def get_video_decoder():
    """Get or create a :class:`VideoDecoder` singleton.

    The decoder backend is selected from ``settings.app.video_decoder_backend``
    (default ``"pyav"``).  If the requested backend is unavailable the best
    available decoder is returned instead.

    Returns ``None`` only when **no** decoder can be instantiated (both
    PyAV and FFmpeg missing).
    """
    global _video_decoder
    if _video_decoder is None:
        from services.video_decoder import get_best_decoder, get_decoder_by_name

        try:
            backend = settings.app.video_decoder_backend
        except Exception:
            backend = "pyav"

        try:
            _video_decoder = get_decoder_by_name(backend)
        except (ValueError, RuntimeError):
            logger.warning(
                "Configured decoder %r unavailable — falling back to best available",
                backend,
            )
            try:
                _video_decoder = get_best_decoder()
            except RuntimeError:
                logger.error("No video decoder backend available")
                return None
    return _video_decoder


def get_scene_detect_service():
    """Get or create SceneDetectService singleton."""
    global _scene_detect_service
    if _scene_detect_service is None:
        from services.scene_detect_service import SceneDetectService

        _scene_detect_service = SceneDetectService()
    return _scene_detect_service


def get_knowledge_graph_service():
    """Get or create Knowledge Graph Service, ensuring it is connected."""
    global _knowledge_graph_service
    if _knowledge_graph_service is None:
        from services.knowledge_graph import (
            get_knowledge_graph_service as _get_kg_service,
        )

        _knowledge_graph_service = _get_kg_service()
        if not _knowledge_graph_service.is_connected:
            _knowledge_graph_service.connect()
    return _knowledge_graph_service


_graph_search_service = None

_faster_whisper_transcriber = None


def get_faster_whisper_transcriber():
    """Get or create FasterWhisperTranscriber singleton.

    Returns ``None`` when the ``faster-whisper`` package is not installed
    or the backend is not configured.
    """
    global _faster_whisper_transcriber
    if _faster_whisper_transcriber is None:
        if settings.azure.whisper_backend != "faster_whisper":
            logger.debug(
                "faster-whisper backend not selected (whisper_backend=%s)",
                settings.azure.whisper_backend,
            )
            return None
        try:
            from services.faster_whisper_service import (
                FasterWhisperTranscriber,
                is_faster_whisper_available,
            )

            if not is_faster_whisper_available():
                logger.warning(
                    "whisper_backend is 'faster_whisper' but the package is not installed. "
                    "Install with: pip install 'qprisma-backend[gpu]'"
                )
                return None

            _faster_whisper_transcriber = FasterWhisperTranscriber(
                model_size=settings.azure.faster_whisper_model,
                device=settings.azure.faster_whisper_device,
                compute_type=settings.azure.faster_whisper_compute_type,
                batch_size=settings.azure.faster_whisper_batch_size,
            )
        except Exception:
            logger.exception("Failed to create FasterWhisperTranscriber")
            return None
    return _faster_whisper_transcriber


def get_graph_search_service():
    """Get or create Graph Search Service (VideoRAG-style hybrid search)."""
    global _graph_search_service
    if _graph_search_service is None:
        from services.graph_search_service import GraphSearchService

        _graph_search_service = GraphSearchService()
        _graph_search_service.graph_service = get_knowledge_graph_service()
        # Initialize vector indexes on first use
        try:
            _graph_search_service.initialize_vector_indexes()
        except Exception as e:
            logger.warning(f"Failed to initialize vector indexes (Neo4j may not be connected): {e}")
    return _graph_search_service


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


async def get_tool_artifact_service():
    """Get ToolArtifactService singleton."""
    from services.tool_artifact_service import (
        get_tool_artifact_service as _get_tool_artifact_service,
    )

    return await _get_tool_artifact_service()


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


async def get_token_from_header(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> str:
    """
    Extract raw JWT token string from Authorization header.

    Returns:
        Raw JWT token string
    """
    return credentials.credentials


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
        token_data = await auth_service.verify_token(credentials.credentials)
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
        token_data = await auth_service.verify_token(credentials.credentials)
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
