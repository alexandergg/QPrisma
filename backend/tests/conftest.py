"""
QPrisma Test Configuration

This file contains shared fixtures and configuration for pytest.
"""

import asyncio
import os
import sys
from pathlib import Path
from typing import AsyncGenerator, Generator

import pytest

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent))


# =============================================================================
# Pytest Configuration
# =============================================================================


def pytest_configure(config):
    """Configure pytest markers."""
    config.addinivalue_line("markers", "unit: mark test as unit test")
    config.addinivalue_line("markers", "integration: mark test as integration test")
    config.addinivalue_line("markers", "e2e: mark test as end-to-end test")
    config.addinivalue_line("markers", "slow: mark test as slow running")
    config.addinivalue_line("markers", "requires_azure: mark test as requiring Azure services")
    config.addinivalue_line("markers", "requires_redis: mark test as requiring Redis")
    config.addinivalue_line("markers", "requires_neo4j: mark test as requiring Neo4j")
    config.addinivalue_line("markers", "requires_postgres: mark test as requiring PostgreSQL")


# =============================================================================
# Event Loop Fixture
# =============================================================================


@pytest.fixture(scope="session")
def event_loop() -> Generator[asyncio.AbstractEventLoop, None, None]:
    """Create an event loop for the test session."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# =============================================================================
# Environment Fixtures
# =============================================================================


@pytest.fixture(scope="session")
def test_env():
    """Set up test environment variables."""
    original_env = os.environ.copy()

    # Set test-specific environment variables
    os.environ.setdefault("APP_ENV", "test")
    os.environ.setdefault("LOG_LEVEL", "WARNING")

    yield os.environ

    # Restore original environment
    os.environ.clear()
    os.environ.update(original_env)


# =============================================================================
# API Client Fixtures
# =============================================================================


@pytest.fixture
def api_base_url() -> str:
    """Get the API base URL for tests."""
    return os.environ.get("TEST_API_URL", "http://localhost:8000")


@pytest.fixture
def api_headers() -> dict:
    """Get default headers for API requests."""
    return {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


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
# Service Fixtures
# =============================================================================


@pytest.fixture
async def cache_service() -> AsyncGenerator:
    """Create a CacheService instance for testing."""
    try:
        from services.cache_service import CacheConfig, CacheService

        config = CacheConfig(key_prefix="test_qprisma", max_memory_items=100)
        cache = CacheService(config=config)
        await cache.connect()

        yield cache

        # Cleanup
        await cache.clear_all()
        await cache.disconnect()
    except ImportError:
        pytest.skip("CacheService not available")


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
