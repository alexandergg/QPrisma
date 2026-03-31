"""
QPrisma Test Configuration

Shared fixtures and configuration for pytest.
Provides FastAPI TestClient, authentication helpers, and mock services.
"""

import os
import sys
from collections.abc import Generator
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent))


def _env_enabled(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes"}


collect_ignore: list[str] = []
if not _env_enabled("RUN_INTEGRATION_TESTS"):
    collect_ignore.extend(
        [
            "test_batch_vision.py",
            "test_deployments.py",
            "test_ffmpeg_basic.py",
            "test_graph_search.py",
            "test_hierarchical_context.py",
            "test_knowledge_graph.py",
        ]
    )
if not _env_enabled("RUN_E2E_TESTS"):
    collect_ignore.extend(
        [
            "test_chat_quick.py",
            "test_ffmpeg_endpoints.py",
            "test_full_pipeline.py",
            "test_video_upload.py",
        ]
    )
if not _env_enabled("RUN_PERFORMANCE_TESTS"):
    collect_ignore.append("test_parallel_performance.py")


# =============================================================================
# Environment Fixtures
# =============================================================================


@pytest.fixture(scope="session", autouse=True)
def test_env():
    """Set up test environment variables for the entire session."""
    original_env = os.environ.copy()

    os.environ.setdefault("APP_ENV", "test")
    os.environ.setdefault("LOG_LEVEL", "WARNING")
    os.environ.setdefault("DISABLE_REDIS_PUBSUB", "1")
    os.environ.setdefault("DISABLE_STARTUP_HEALTHCHECKS", "1")
    # Prevent production validators from firing
    os.environ.pop("ENVIRONMENT", None)

    yield os.environ

    os.environ.clear()
    os.environ.update(original_env)


# =============================================================================
# Settings Fixtures
# =============================================================================


@pytest.fixture
def reset_settings():
    """Reset the cached settings singleton between tests."""
    from core.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


# =============================================================================
# FastAPI App & Client Fixtures
# =============================================================================


@pytest.fixture
def app(reset_settings):
    """
    Create a FastAPI app with dependency overrides for testing.

    Resets all singleton services to prevent test pollution.
    """
    import api.dependencies as deps

    # Reset singletons
    deps._blob_service = None
    deps._openai_client = None
    deps._async_openai_client = None
    deps._video_processor = None
    deps._pyav_extractor = None
    deps._faster_whisper_transcriber = None
    deps._video_decoder = None
    deps._graph_search_service = None

    from api.main import app as fastapi_app

    yield fastapi_app

    # Cleanup overrides
    fastapi_app.dependency_overrides.clear()


@pytest.fixture
def client(app) -> Generator[TestClient, None, None]:
    """Sync TestClient for route tests."""
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture
async def async_client(app):
    """Async httpx client for async route tests."""
    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac


# =============================================================================
# Auth Service & Token Fixtures
# =============================================================================


@pytest.fixture
def auth_service():
    """Create a mock EntraAuthService for unit tests."""
    from unittest.mock import AsyncMock, MagicMock

    from models.user import EntraTokenData

    mock = MagicMock()
    mock.verify_token = AsyncMock(
        return_value=EntraTokenData(
            oid="entra-oid-test123", email="test@example.com", name="Test User"
        )
    )
    return mock


@pytest.fixture
def test_user():
    """A standard test user."""
    from models.user import User

    return User(
        id="user_test123",
        email="test@example.com",
        full_name="Test User",
        is_active=True,
        is_superuser=False,
        created_at=datetime(2024, 1, 1, tzinfo=UTC),
        updated_at=datetime(2024, 1, 1, tzinfo=UTC),
    )


@pytest.fixture
def superuser():
    """A superuser for admin tests."""
    from models.user import User

    return User(
        id="user_admin456",
        email="admin@example.com",
        full_name="Admin User",
        is_active=True,
        is_superuser=True,
        created_at=datetime(2024, 1, 1, tzinfo=UTC),
        updated_at=datetime(2024, 1, 1, tzinfo=UTC),
    )


@pytest.fixture
def auth_token(auth_service, test_user):
    """Generate a mock Bearer token for test_user."""
    return "mock-entra-id-token-for-tests"


@pytest.fixture
def auth_headers(auth_token):
    """HTTP headers with valid Bearer token."""
    return {"Authorization": f"Bearer {auth_token}"}


@pytest.fixture
def authenticated_app(app, test_user):
    """
    App with get_current_user overridden to return test_user.
    Use this for route tests that need authentication without real JWT.
    """
    from api.dependencies import get_current_user

    app.dependency_overrides[get_current_user] = lambda: test_user
    return app


@pytest.fixture
def authenticated_client(authenticated_app) -> Generator[TestClient, None, None]:
    """TestClient with authentication pre-configured."""
    with TestClient(authenticated_app, raise_server_exceptions=False) as c:
        yield c


# =============================================================================
# Mock Service Fixtures
# =============================================================================


@pytest.fixture
def mock_db_service():
    """Mocked DatabaseService with common methods."""
    mock = MagicMock()
    mock.health_check.return_value = {"status": "healthy"}
    mock.get_user_by_email.return_value = None
    mock.get_media.return_value = None
    mock.get_media_by_user.return_value = []
    mock.get_media_status.return_value = None
    mock.create_media.return_value = MagicMock(id="media_123")
    mock.create_user.return_value = MagicMock(id="user_new123", email="new@example.com")
    mock.get_project.return_value = None
    mock.get_projects_by_user.return_value = []
    mock.get_clip.return_value = None
    mock.get_clips_by_project.return_value = []
    return mock


@pytest.fixture
def mock_blob_service():
    """Mocked BlobServiceClient."""
    mock = MagicMock()
    mock_blob_client = MagicMock()
    mock_blob_client.upload_blob.return_value = None
    mock_blob_client.get_blob_properties.return_value = MagicMock(size=1024)
    mock.get_blob_client.return_value = mock_blob_client
    return mock


@pytest.fixture
def mock_openai_client():
    """Mocked AsyncAzureOpenAI client."""
    mock = AsyncMock()
    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=MagicMock(content="Test response"))]
    mock.chat.completions.create = AsyncMock(return_value=mock_response)
    return mock


@pytest.fixture
def mock_graph_search_service():
    """Mocked GraphSearchService."""
    mock = AsyncMock()
    mock.hybrid_search = AsyncMock(return_value=MagicMock(results=[], total_results=0))
    mock.graph_service = MagicMock(is_connected=True)
    return mock


# =============================================================================
# Test Data Fixtures
# =============================================================================


@pytest.fixture
def test_data_dir() -> Path:
    """Get the test data directory."""
    return Path(__file__).parent / "test_data"


@pytest.fixture
def sample_video_path(test_data_dir: Path) -> Path:
    """Get path to sample test video."""
    return test_data_dir / "test_video.mp4"


@pytest.fixture
def sample_frame_path(test_data_dir: Path) -> Path:
    """Get path to sample test frame."""
    return test_data_dir / "test_frame.jpg"


# =============================================================================
# Utility Functions
# =============================================================================


def skip_if_no_env(var_name: str):
    """Skip test if environment variable is not set."""
    if not os.environ.get(var_name):
        pytest.skip(f"Environment variable {var_name} not set")


def skip_if_no_azure():
    """Skip test if Azure credentials are not configured."""
    skip_if_no_env("AZURE_OPENAI_API_KEY")
    skip_if_no_env("AZURE_OPENAI_ENDPOINT")


def skip_if_no_redis():
    """Skip test if Redis is not configured."""
    skip_if_no_env("REDIS_URL")


def skip_if_no_neo4j():
    """Skip test if Neo4j is not configured."""
    skip_if_no_env("NEO4J_URI")
