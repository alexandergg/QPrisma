"""Tests for services.embedding_service."""

import hashlib
from unittest.mock import AsyncMock, Mock, patch

import pytest

from services.embedding_service import EmbeddingService


@pytest.fixture
def embedding_service() -> EmbeddingService:
    """Create an EmbeddingService instance for unit tests."""
    return EmbeddingService(
        api_key="test_key",
        endpoint="https://test.openai.azure.com",
        deployment="text-embedding-3-large",
    )


@pytest.fixture
def sample_embedding() -> list[float]:
    """Small sample embedding vector for deterministic assertions."""
    return [0.1, 0.2, 0.3]


@pytest.fixture
def mock_cache_service() -> Mock:
    """Create a mock cache backend."""
    cache = Mock()
    cache.get = Mock(return_value=None)
    cache.set = Mock()
    return cache


class TestEmbeddingServiceInit:
    def test_initializes_with_provided_credentials(self) -> None:
        service = EmbeddingService(
            api_key="custom_key",
            endpoint="https://custom.openai.azure.com",
            deployment="custom_deployment",
        )

        assert service.api_key == "custom_key"
        assert service.endpoint == "https://custom.openai.azure.com"
        assert service.deployment == "custom_deployment"

    def test_falls_back_to_environment_variables(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "AZURE_OPENAI_API_KEY": "env_key",
                "AZURE_OPENAI_ENDPOINT": "https://env.openai.azure.com",
                "AZURE_OPENAI_DEPLOYMENT_EMBEDDING": "env_deployment",
            },
        ):
            service = EmbeddingService()

        assert service.api_key == "env_key"
        assert service.endpoint == "https://env.openai.azure.com"
        assert service.deployment == "env_deployment"


class TestClientLazyInit:
    def test_client_not_initialized_on_construction(
        self, embedding_service: EmbeddingService
    ) -> None:
        assert embedding_service._client is None

    def test_client_initialized_on_first_access(self, embedding_service: EmbeddingService) -> None:
        with patch("services.embedding_service.AsyncAzureOpenAI") as mock_client_ctor:
            _ = embedding_service.client

        mock_client_ctor.assert_called_once_with(
            api_key="test_key",
            api_version="2024-08-01-preview",
            azure_endpoint="https://test.openai.azure.com",
        )

    def test_client_reused_on_subsequent_access(self, embedding_service: EmbeddingService) -> None:
        with patch("services.embedding_service.AsyncAzureOpenAI") as mock_client_ctor:
            client1 = embedding_service.client
            client2 = embedding_service.client

        assert mock_client_ctor.call_count == 1
        assert client1 is client2


class TestHashComputation:
    def test_computes_consistent_hash(self, embedding_service: EmbeddingService) -> None:
        text = "test text"
        assert embedding_service._compute_hash(text) == embedding_service._compute_hash(text)

    def test_hash_is_sha256(self, embedding_service: EmbeddingService) -> None:
        text = "test text"
        expected_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        assert embedding_service._compute_hash(text) == expected_hash


class TestEmbeddingGeneration:
    @pytest.mark.asyncio
    async def test_generate_embedding_calls_api(
        self, embedding_service: EmbeddingService, sample_embedding: list[float]
    ) -> None:
        mock_response = Mock()
        mock_response.data = [Mock(embedding=sample_embedding)]
        mock_response.usage = Mock(total_tokens=10)

        with patch("services.embedding_service.AsyncAzureOpenAI") as mock_client_ctor:
            mock_client_ctor.return_value.embeddings.create = AsyncMock(return_value=mock_response)
            result = await embedding_service.generate_embedding("test text")

        assert result == sample_embedding
        mock_client_ctor.return_value.embeddings.create.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_generate_embedding_uses_correct_model(
        self, embedding_service: EmbeddingService
    ) -> None:
        mock_response = Mock()
        mock_response.data = [Mock(embedding=[0.1, 0.2])]
        mock_response.usage = Mock(total_tokens=10)

        with patch("services.embedding_service.AsyncAzureOpenAI") as mock_client_ctor:
            mock_client_ctor.return_value.embeddings.create = AsyncMock(return_value=mock_response)
            await embedding_service.generate_embedding("test text")

        call_kwargs = mock_client_ctor.return_value.embeddings.create.call_args.kwargs
        assert call_kwargs["model"] == "text-embedding-3-large"

    @pytest.mark.asyncio
    async def test_updates_statistics(self, embedding_service: EmbeddingService) -> None:
        mock_response = Mock()
        mock_response.data = [Mock(embedding=[0.1, 0.2])]
        mock_response.usage = Mock(total_tokens=7)

        with patch("services.embedding_service.AsyncAzureOpenAI") as mock_client_ctor:
            mock_client_ctor.return_value.embeddings.create = AsyncMock(return_value=mock_response)
            await embedding_service.generate_embedding("test text")

        assert embedding_service.stats["total_requests"] == 1
        assert embedding_service.stats["tokens_used"] == 7

    @pytest.mark.asyncio
    async def test_handles_empty_text(self, embedding_service: EmbeddingService) -> None:
        result = await embedding_service.generate_embedding("")
        assert result == [0.0] * embedding_service.EMBEDDING_DIMENSIONS


class TestCaching:
    @pytest.mark.asyncio
    async def test_uses_cached_embedding_when_available(
        self,
        embedding_service: EmbeddingService,
        mock_cache_service: Mock,
        sample_embedding: list[float],
    ) -> None:
        embedding_service.cache_service = mock_cache_service
        mock_cache_service.get.return_value = sample_embedding

        with patch("services.embedding_service.AsyncAzureOpenAI") as mock_client_ctor:
            result = await embedding_service.generate_embedding("test text")

        assert result == sample_embedding
        mock_client_ctor.assert_not_called()
        assert embedding_service.stats["cache_hits"] == 1

    @pytest.mark.asyncio
    async def test_caches_new_embedding(
        self, embedding_service: EmbeddingService, mock_cache_service: Mock
    ) -> None:
        embedding_service.cache_service = mock_cache_service
        mock_response = Mock()
        mock_response.data = [Mock(embedding=[0.1, 0.2])]
        mock_response.usage = Mock(total_tokens=10)

        with patch("services.embedding_service.AsyncAzureOpenAI") as mock_client_ctor:
            mock_client_ctor.return_value.embeddings.create = AsyncMock(return_value=mock_response)
            await embedding_service.generate_embedding("test text")

        mock_cache_service.set.assert_called_once()


class TestBatchGeneration:
    @pytest.mark.asyncio
    async def test_batch_generate_processes_multiple_texts(
        self, embedding_service: EmbeddingService
    ) -> None:
        mock_response = Mock()
        mock_response.data = [Mock(embedding=[0.1]), Mock(embedding=[0.2])]
        mock_response.usage = Mock(total_tokens=20)

        with patch("services.embedding_service.AsyncAzureOpenAI") as mock_client_ctor:
            mock_client_ctor.return_value.embeddings.create = AsyncMock(return_value=mock_response)
            results = await embedding_service.generate_embeddings_batch(["text1", "text2", ""])

        assert len(results) == 3
        assert results[0] == [0.1]
        assert results[1] == [0.2]
        assert results[2] == [0.0] * embedding_service.EMBEDDING_DIMENSIONS

    @pytest.mark.asyncio
    async def test_batch_uses_cache_for_known_texts(
        self,
        embedding_service: EmbeddingService,
        mock_cache_service: Mock,
        sample_embedding: list[float],
    ) -> None:
        embedding_service.cache_service = mock_cache_service
        mock_cache_service.get.side_effect = [sample_embedding, None]

        mock_response = Mock()
        mock_response.data = [Mock(embedding=[0.5, 0.6, 0.7])]
        mock_response.usage = Mock(total_tokens=10)

        with patch("services.embedding_service.AsyncAzureOpenAI") as mock_client_ctor:
            mock_client_ctor.return_value.embeddings.create = AsyncMock(return_value=mock_response)
            results = await embedding_service.generate_embeddings_batch(["cached text", "new text"])

        assert len(results) == 2
        assert results[0] == sample_embedding
        assert results[1] == [0.5, 0.6, 0.7]
        mock_client_ctor.return_value.embeddings.create.assert_awaited_once()


class TestSimilarityAndStats:
    def test_compute_similarity_identical_vectors(
        self, embedding_service: EmbeddingService
    ) -> None:
        vector = [1.0, 2.0, 3.0]
        similarity = embedding_service.compute_similarity(vector, vector)
        assert abs(similarity - 1.0) < 1e-9

    def test_compute_similarity_zero_vector(self, embedding_service: EmbeddingService) -> None:
        similarity = embedding_service.compute_similarity([0.0, 0.0], [1.0, 1.0])
        assert similarity == 0.0

    def test_get_stats_includes_cache_hit_rate(self, embedding_service: EmbeddingService) -> None:
        embedding_service.stats["total_requests"] = 4
        embedding_service.stats["cache_hits"] = 1
        stats = embedding_service.get_stats()
        assert stats["cache_hit_rate"] == 0.25


@pytest.mark.integration
@pytest.mark.requires_azure
@pytest.mark.asyncio
async def test_real_embedding_generation() -> None:
    import os

    if os.getenv("RUN_INTEGRATION_TESTS", "").lower() not in {"1", "true", "yes"}:
        pytest.skip("Integration tests disabled. Set RUN_INTEGRATION_TESTS=true to enable.")
    if not os.getenv("AZURE_OPENAI_API_KEY"):
        pytest.skip("Azure credentials not configured")

    service = EmbeddingService()
    embedding = await service.generate_embedding("Hello, world!")

    assert isinstance(embedding, list)
    assert len(embedding) > 0
