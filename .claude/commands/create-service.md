# Create Backend Service

Create a new backend service following QPrisma patterns.

## Usage
```
/create-service <service_name> [--azure] [--singleton]
```

## Instructions

When creating a new service for QPrisma, follow these patterns:

### 1. Create the service file at `backend/services/{name}_service.py`

```python
"""
{Name} Service
{'=' * (len(name) + 8)}

{Description of what this service does}.
"""

import logging
from typing import Any

from tenacity import retry, stop_after_attempt, wait_exponential

from core.config import settings

logger = logging.getLogger(__name__)


class {Name}Service:
    """
    Service for {description}.

    This service provides:
    - {Feature 1}
    - {Feature 2}
    - {Feature 3}
    """

    def __init__(self):
        """Initialize the {name} service."""
        self._client = None
        self._initialized = False

        # Load configuration from centralized settings (never use os.getenv directly)
        # self.config_value = settings.{section}.{key}

        logger.info(f"{Name}Service initialized")

    # =========================================================================
    # Initialization
    # =========================================================================

    def _ensure_initialized(self) -> None:
        """Ensure the service is initialized before use."""
        if not self._initialized:
            self._initialize()

    def _initialize(self) -> None:
        """Initialize the service client and connections."""
        try:
            # Initialize client/connection here
            # self._client = SomeClient(...)
            self._initialized = True
            logger.info(f"{Name}Service client initialized")
        except Exception as e:
            logger.error(f"Failed to initialize {Name}Service: {e}")
            raise

    # =========================================================================
    # Public Methods
    # =========================================================================

    async def process(self, data: dict[str, Any]) -> dict[str, Any]:
        """
        Process data through the service.

        Args:
            data: Input data to process

        Returns:
            Processed result dictionary

        Raises:
            ValueError: If input data is invalid
            RuntimeError: If processing fails
        """
        self._ensure_initialized()

        try:
            # Validate input
            if not data:
                raise ValueError("Input data cannot be empty")

            # Process
            result = await self._do_process(data)

            logger.info(f"Successfully processed data: {len(data)} items")
            return result

        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Error processing data: {e}")
            raise RuntimeError(f"Processing failed: {e}") from e

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
    )
    async def _do_process(self, data: dict[str, Any]) -> dict[str, Any]:
        """
        Internal processing with retry logic.

        Args:
            data: Data to process

        Returns:
            Processed result
        """
        # Implementation here
        return {"processed": True, "data": data}

    async def get_status(self) -> dict[str, Any]:
        """
        Get the current service status.

        Returns:
            Status dictionary with health information
        """
        return {
            "service": "{name}",
            "initialized": self._initialized,
            "healthy": self._check_health(),
        }

    def _check_health(self) -> bool:
        """Check if the service is healthy."""
        try:
            # Perform health check
            return self._initialized and self._client is not None
        except Exception:
            return False

    # =========================================================================
    # Cleanup
    # =========================================================================

    async def close(self) -> None:
        """Clean up service resources."""
        if self._client:
            # Close client connections
            # await self._client.close()
            self._client = None
        self._initialized = False
        logger.info(f"{Name}Service closed")


# =============================================================================
# Singleton Instance
# =============================================================================

_service_instance: {Name}Service | None = None


def get_{name}_service() -> {Name}Service:
    """Get or create the {name} service singleton."""
    global _service_instance
    if _service_instance is None:
        _service_instance = {Name}Service()
    return _service_instance
```

### 2. For Azure-integrated services

```python
"""
{Name} Service (Azure)
{'=' * (len(name) + 16)}

Azure-integrated service for {description}.
"""

import logging
from typing import Any

from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient  # or other Azure SDK

from core.config import settings

logger = logging.getLogger(__name__)


class {Name}Service:
    """Azure-integrated {name} service."""

    def __init__(self):
        """Initialize with Azure credentials."""
        self._client = None

        # Azure configuration from centralized settings
        self.connection_string = settings.azure.storage_connection  # or relevant setting
        self.endpoint = settings.azure.openai_endpoint  # or relevant setting

        if not self.connection_string and not self.endpoint:
            logger.warning(
                "No Azure {name} configuration found. "
                "Check core.config.settings for required Azure settings."
            )

    @property
    def client(self):
        """Lazy-initialize Azure client."""
        if self._client is None:
            if self.connection_string:
                self._client = BlobServiceClient.from_connection_string(
                    self.connection_string
                )
            elif self.endpoint:
                credential = DefaultAzureCredential()
                self._client = BlobServiceClient(
                    account_url=self.endpoint,
                    credential=credential,
                )
            else:
                raise RuntimeError("Azure {name} not configured")
        return self._client

    async def upload(self, data: bytes, name: str) -> str:
        """Upload data to Azure."""
        try:
            container = self.client.get_container_client("container-name")
            blob = container.get_blob_client(name)
            blob.upload_blob(data, overwrite=True)
            return blob.url
        except Exception as e:
            logger.error(f"Azure upload failed: {e}")
            raise
```

### 3. Add lazy initialization in `backend/api/dependencies.py`

```python
# In api/dependencies.py (single source of truth for service singletons)
_{name}_service: {Name}Service | None = None


def get_{name}_service() -> {Name}Service:
    """Get or create {name} service singleton."""
    global _{name}_service
    if _{name}_service is None:
        from services.{name}_service import {Name}Service
        _{name}_service = {Name}Service()
    return _{name}_service
```

### 4. Create tests at `backend/tests/test_{name}_service.py`

```python
"""Tests for {name} service."""

import pytest

from services.{name}_service import {Name}Service, get_{name}_service


class Test{Name}Service:
    """Test cases for {Name}Service."""

    @pytest.fixture
    def service(self):
        """Create a fresh service instance for testing."""
        return {Name}Service()

    @pytest.mark.asyncio
    async def test_process_success(self, service):
        """Test successful data processing."""
        result = await service.process({"key": "value"})
        assert result["processed"] is True

    @pytest.mark.asyncio
    async def test_process_empty_data(self, service):
        """Test processing with empty data raises ValueError."""
        with pytest.raises(ValueError, match="cannot be empty"):
            await service.process({})

    @pytest.mark.asyncio
    async def test_get_status(self, service):
        """Test status retrieval."""
        status = await service.get_status()
        assert status["service"] == "{name}"
        assert "healthy" in status

    def test_singleton(self):
        """Test that get_{name}_service returns singleton."""
        service1 = get_{name}_service()
        service2 = get_{name}_service()
        assert service1 is service2


class Test{Name}ServiceIntegration:
    """Integration tests (require external services)."""

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_real_processing(self):
        """Test with real external service."""
        service = get_{name}_service()
        # Test with real service
        pass
```

## Service Categories

| Category | Pattern | Example Services |
|----------|---------|------------------|
| Processing | Async methods with retry | `video_processor`, `audio_processor` |
| Storage | Azure SDK integration | `storage_service`, `cache_service` |
| AI/ML | Azure OpenAI/Cognitive | `embedding_service`, `vision_service` |
| Database | Connection pooling | `database_service`, `knowledge_graph` |
| Integration | External APIs | `export_service`, `webhook_service` |

## Checklist
- [ ] Service class created with proper structure
- [ ] Lazy initialization pattern implemented
- [ ] Environment variables documented
- [ ] Error handling with proper logging
- [ ] Retry logic for external calls (tenacity)
- [ ] Health check method implemented
- [ ] Cleanup method for resources
- [ ] Singleton getter function created
- [ ] Added to `api/dependencies.py` lazy initialization
- [ ] Unit tests created
- [ ] Integration tests created (marked with `@pytest.mark.integration`)
