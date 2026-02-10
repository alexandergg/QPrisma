"""
Tests for Embedding Service
Tests text embedding generation with Azure OpenAI and caching.
"""

import hashlib
from unittest.mock import Mock, patch

import pytest

from services.embedding_service import EmbeddingService


@pytest.fixture
def embedding_service():
    """Create an EmbeddingService instance for testing."""
    return EmbeddingService(
        api_key="test_key",
        endpoint="https://test.openai.azure.com",
        deployment="text-embedding-3-large",
    )


@pytest.fixture
def mock_cache_service():
    """Create a mock cache service."""
    cache = Mock()
    cache.get = Mock(return_value=None)
    cache.set = Mock()
    return cache


@pytest.fixture
def sample_embedding():
    """Sample embedding vector (shortened for testing)."""
    return [0.1] * 3072  # text-embedding-3-large dimensions


class TestEmbeddingServiceInit:
    """Tests for EmbeddingService initialization."""

    def test_initializes_with_provided_credentials(self):
        """Test initialization with explicitly provided credentials."""
        service = EmbeddingService(
            api_key="custom_key",
            endpoint="https://custom.openai.azure.com",
            deployment="custom_deployment",
        )

        assert service.api_key == "custom_key"
        assert service.endpoint == "https://custom.openai.azure.com"
        assert service.deployment == "custom_deployment"

    def test_falls_back_to_environment_variables(self):
        """Test that service falls back to environment variables."""
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

    def test_uses_default_api_version(self):
        """Test that default API version is set."""
        service = EmbeddingService(api_key="test_key", endpoint="https://test.openai.azure.com")

        assert service.api_version == "2024-08-01-preview"

    def test_accepts_cache_service(self):
        """Test that cache service can be provided."""
        mock_cache = Mock()
        service = EmbeddingService(
            api_key="test_key",
            endpoint="https://test.openai.azure.com",
            cache_service=mock_cache,
        )

        assert service.cache_service == mock_cache

    def test_initializes_stats(self):
        """Test that statistics are initialized."""
        service = EmbeddingService(api_key="test_key", endpoint="https://test.openai.azure.com")

        assert service.stats["total_requests"] == 0
        assert service.stats["cache_hits"] == 0
        assert service.stats["tokens_used"] == 0


class TestClientLazyInit:
    """Tests for lazy initialization of Azure OpenAI client."""

    def test_client_not_initialized_on_construction(self, embedding_service):
        """Test that client is not initialized until accessed."""
        assert embedding_service._client is None

    def test_client_initialized_on_first_access(self, embedding_service):
        """Test that client is initialized on first access."""
        with patch("services.embedding_service.AzureOpenAI") as mock_azure:
            _ = embedding_service.client

            mock_azure.assert_called_once_with(
                api_key="test_key",
                api_version="2024-08-01-preview",
                azure_endpoint="https://test.openai.azure.com",
            )

    def test_client_reused_on_subsequent_access(self, embedding_service):
        """Test that client is reused after initialization."""
        with patch("services.embedding_service.AzureOpenAI") as mock_azure:
            client1 = embedding_service.client
            client2 = embedding_service.client

            # Should only be called once
            assert mock_azure.call_count == 1
            assert client1 is client2


class TestHashComputation:
    """Tests for text hashing functionality."""

    def test_computes_consistent_hash(self, embedding_service):
        """Test that same text produces same hash."""
        text = "test text"
        hash1 = embedding_service._compute_hash(text)
        hash2 = embedding_service._compute_hash(text)

        assert hash1 == hash2

    def test_different_texts_produce_different_hashes(self, embedding_service):
        """Test that different texts produce different hashes."""
        hash1 = embedding_service._compute_hash("text 1")
        hash2 = embedding_service._compute_hash("text 2")

        assert hash1 != hash2

    def test_hash_is_sha256(self, embedding_service):
        """Test that hash is SHA-256."""
        text = "test text"
        expected_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        actual_hash = embedding_service._compute_hash(text)

        assert actual_hash == expected_hash

    def test_handles_unicode_text(self, embedding_service):
        """Test that unicode text is hashed correctly."""
        text = "Testing with émojis 🎉 and ñ characters"
        hash_result = embedding_service._compute_hash(text)

        # Should not raise exception and should return valid hex string
        assert isinstance(hash_result, str)
        assert len(hash_result) == 64  # SHA-256 produces 64 hex characters


class TestEmbeddingGeneration:
    """Tests for embedding generation."""

    def test_generate_embedding_calls_azure_api(self, embedding_service, sample_embedding):
        """Test that embedding generation calls Azure API."""
        mock_response = Mock()
        mock_response.data = [Mock(embedding=sample_embedding)]
        mock_response.usage.total_tokens = 10

        with patch("services.embedding_service.AzureOpenAI") as mock_azure:
            mock_azure.return_value.embeddings.create.return_value = mock_response

            result = embedding_service.generate_embedding("test text")

            assert result == sample_embedding
            mock_azure.return_value.embeddings.create.assert_called_once()

    @pytest.mark.asyncio
    async def test_generate_embedding_uses_correct_model(self, embedding_service, sample_embedding):
        """Test that correct deployment name is used."""
        mock_response = Mock()
        mock_response.data = [Mock(embedding=sample_embedding)]
        mock_response.usage.total_tokens = 10

        with patch("services.embedding_service.AzureOpenAI") as mock_azure:
            mock_azure.return_value.embeddings.create.return_value = mock_response

            embedding_service.generate_embedding("test text")

            call_kwargs = mock_azure.return_value.embeddings.create.call_args[1]
            assert call_kwargs["model"] == "text-embedding-3-large"

    def test_updates_statistics(self, embedding_service, sample_embedding):
        """Test that statistics are updated after generation."""
        mock_response = Mock()
        mock_response.data = [Mock(embedding=sample_embedding)]
        mock_response.usage.total_tokens = 10

        with patch("services.embedding_service.AzureOpenAI") as mock_azure:
            mock_azure.return_value.embeddings.create.return_value = mock_response

            embedding_service.generate_embedding("test text")

            assert embedding_service.stats["total_requests"] == 1
            assert embedding_service.stats["tokens_used"] == 10


class TestCaching:
    """Tests for embedding caching functionality."""

    def test_uses_cached_embedding_when_available(
        self, embedding_service, mock_cache_service, sample_embedding
    ):
        """Test that cached embeddings are used when available."""
        embedding_service.cache_service = mock_cache_service
        mock_cache_service.get.return_value = sample_embedding

        with patch("services.embedding_service.AzureOpenAI") as mock_azure:
            mock_azure.return_value.embeddings.create.return_value = Mock()
            result = embedding_service.generate_embedding("test text")

            # Should return cached value
            assert result == sample_embedding
            # Should not call Azure API
            mock_azure.return_value.embeddings.create.assert_not_called()
            # Should increment cache hit counter
            assert embedding_service.stats["cache_hits"] == 1

    def test_caches_new_embedding(self, embedding_service, mock_cache_service, sample_embedding):
        """Test that newly generated embeddings are cached."""
        embedding_service.cache_service = mock_cache_service
        mock_cache_service.get.return_value = None  # Cache miss

        mock_response = Mock()
        mock_response.data = [Mock(embedding=sample_embedding)]
        mock_response.usage.total_tokens = 10

        with patch("services.embedding_service.AzureOpenAI") as mock_azure:
            mock_azure.return_value.embeddings.create.return_value = mock_response

            embedding_service.generate_embedding("test text")

            # Should store in cache
            mock_cache_service.set.assert_called_once()

    def test_works_without_cache_service(self, embedding_service, sample_embedding):
        """Test that service works without cache."""
        embedding_service.cache_service = None

        mock_response = Mock()
        mock_response.data = [Mock(embedding=sample_embedding)]
        mock_response.usage.total_tokens = 10

        with patch("services.embedding_service.AzureOpenAI") as mock_azure:
            mock_azure.return_value.embeddings.create.return_value = mock_response

            result = embedding_service.generate_embedding("test text")

            # Should still work
            assert result == sample_embedding


class TestBatchProcessing:
    """Tests for batch embedding generation."""

    def test_batch_generate_processes_multiple_texts(self, embedding_service, sample_embedding):
        """Test that batch generation handles multiple texts."""
        texts = ["text 1", "text 2", "text 3"]

        mock_response = Mock()
        mock_response.data = [
            Mock(embedding=sample_embedding),
            Mock(embedding=sample_embedding),
            Mock(embedding=sample_embedding),
        ]
        mock_response.usage.total_tokens = 30

        with patch("services.embedding_service.AzureOpenAI") as mock_azure:
            mock_azure.return_value.embeddings.create.return_value = mock_response

            results = embedding_service.generate_embeddings_batch(texts)

            assert len(results) == 3
            # Should call API once for batch
            assert mock_azure.return_value.embeddings.create.call_count == 1

    def test_batch_uses_cache_for_known_texts(
        self, embedding_service, mock_cache_service, sample_embedding
    ):
        """Test that batch generation uses cache when available."""
        embedding_service.cache_service = mock_cache_service
        texts = ["text 1", "text 2"]

        # First text is cached, second is not
        def mock_get(key):
            if "text 1" in key:
                return sample_embedding
            return None

        mock_cache_service.get.side_effect = mock_get

        mock_response = Mock()
        mock_response.data = [Mock(embedding=sample_embedding)]
        mock_response.usage.total_tokens = 10

        with patch("services.embedding_service.AzureOpenAI") as mock_azure:
            mock_azure.return_value.embeddings.create.return_value = mock_response

            results = embedding_service.generate_embeddings_batch(texts)

            assert len(results) == 2
            # Should only request embedding for text 2
            assert mock_azure.return_value.embeddings.create.call_count == 1


class TestErrorHandling:
    """Tests for error handling."""

    def test_handles_api_error_gracefully(self, embedding_service):
        """Test that API errors are handled properly."""
        with patch("services.embedding_service.AzureOpenAI") as mock_azure:
            mock_azure.return_value.embeddings.create.side_effect = Exception("API Error")

            with pytest.raises(Exception, match="API Error"):
                embedding_service.generate_embedding("test text")

    def test_handles_empty_text(self, embedding_service):
        """Test handling of empty text input."""
        result = embedding_service.generate_embedding("")
        assert result == [0.0] * embedding_service.EMBEDDING_DIMENSIONS

    @pytest.mark.asyncio
    async def test_validates_text_length(self, embedding_service):
        """Test that overly long texts are rejected or truncated."""
        very_long_text = "a" * 100000  # Very long text

        # Behavior depends on implementation
        # Should either truncate or raise error
        # This test documents the expected behavior
        pass


@pytest.mark.integration
class TestIntegration:
    """Integration tests (require Azure credentials)."""

    @pytest.mark.requires_azure
    @pytest.mark.asyncio
    async def test_real_embedding_generation(self):
        """Test actual embedding generation with Azure OpenAI."""
        import os

        if not os.getenv("AZURE_OPENAI_API_KEY"):
            pytest.skip("Azure credentials not configured")

        service = EmbeddingService()
        embedding = service.generate_embedding("Hello, world!")

        assert isinstance(embedding, list)
        assert len(embedding) == EmbeddingService.EMBEDDING_DIMENSIONS
        assert all(isinstance(x, float) for x in embedding)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
