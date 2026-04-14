"""
Embedding Service for QPrisma

Generates embeddings using Azure OpenAI text-embedding-3-large.
Provides embedding cache and batch processing.
"""

import hashlib
import logging
from datetime import UTC, datetime

from openai import APIConnectionError, APIError, AsyncAzureOpenAI, AzureOpenAI, RateLimitError
from tenacity import retry, stop_after_attempt, wait_exponential

from core.azure_credentials import build_openai_client_kwargs
from core.config import settings

logger = logging.getLogger(__name__)


class EmbeddingService:
    """
    Service for generating embeddings with Azure OpenAI.

    Features:
    - text-embedding-3-large (3072 dimensions)
    - Batch processing for efficiency
    - Embedding cache by content hash
    - Retry with exponential backoff
    """

    # Dimensions of the text-embedding-3-large model
    EMBEDDING_DIMENSIONS = 3072
    # Coarse dimensions for fast initial filtering (Matryoshka)
    COARSE_DIMENSIONS = 512

    def __init__(
        self,
        api_key: str | None = None,
        endpoint: str | None = None,
        deployment: str | None = None,
        api_version: str = "2024-08-01-preview",
        cache_service=None,
    ):
        """
        Initialize the embedding service.

        Args:
            api_key: Azure OpenAI API key
            endpoint: Azure OpenAI endpoint
            deployment: Embeddings deployment name
            api_version: API version
            cache_service: Optional cache service
        """
        self.api_key = api_key or settings.azure.openai_api_key
        self.endpoint = endpoint or settings.azure.openai_endpoint
        self.deployment = deployment or settings.azure.openai_deployment_embedding
        self.api_version = api_version
        self.cache_service = cache_service

        self._client: AzureOpenAI | AsyncAzureOpenAI | None = None

        # Statistics
        self.stats = {
            "total_requests": 0,
            "cache_hits": 0,
            "tokens_used": 0,
        }

    @property
    def client(self) -> AzureOpenAI | AsyncAzureOpenAI:
        """Lazy initialization of the Azure OpenAI client."""
        if self._client is None:
            client_kwargs = build_openai_client_kwargs(
                endpoint=self.endpoint,
                api_key=self.api_key,
                api_version=self.api_version,
                use_managed_identity=settings.azure.use_managed_identity,
            )
            if client_kwargs is None:
                raise ValueError("Azure OpenAI client is not configured")
            self._client = AsyncAzureOpenAI(**client_kwargs)
        return self._client

    def _compute_hash(self, text: str) -> str:
        """Compute SHA-256 hash of text for cache."""
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def _get_from_cache(self, text_hash: str) -> list[float] | None:
        """Attempt to retrieve embedding from cache."""
        if self.cache_service is None:
            return None

        try:
            cached = self.cache_service.get(f"emb:{text_hash}")
            if cached:
                self.stats["cache_hits"] += 1
                return cached
        except Exception as e:
            logger.debug(f"Cache lookup failed: {e}")

        return None

    def _save_to_cache(self, text_hash: str, embedding: list[float], ttl: int = 86400 * 7):
        """Save embedding to cache (default: 7 days)."""
        if self.cache_service is None:
            return

        try:
            self.cache_service.set(f"emb:{text_hash}", embedding, ttl=ttl)
        except Exception as e:
            logger.debug(f"Cache save failed: {e}")

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
    )
    async def generate_embedding(self, text: str, use_cache: bool = True) -> list[float]:
        """
        Generate embedding for a text.

        Args:
            text: Text to embed
            use_cache: Whether to use cache

        Returns:
            List of floats (embedding of 3072 dimensions)
        """
        if not text or not text.strip():
            # Return zero embedding for empty text
            return [0.0] * self.EMBEDDING_DIMENSIONS

        # Normalize text
        text = text.strip()[:8000]  # Limit to 8000 chars

        # Try cache
        text_hash = self._compute_hash(text)
        if use_cache:
            cached = self._get_from_cache(text_hash)
            if cached:
                return cached

        # Generate embedding
        self.stats["total_requests"] += 1

        logger.info(
            "generate_embedding: calling Azure OpenAI | " "deployment=%s text_len=%d",
            self.deployment,
            len(text),
        )
        embed_start = datetime.now(UTC)

        try:
            response = await self.client.embeddings.create(
                model=self.deployment,
                input=text,
            )
        except (APIError, APIConnectionError, RateLimitError) as e:
            embed_ms = (datetime.now(UTC) - embed_start).total_seconds() * 1000
            logger.error(
                "generate_embedding: Azure OpenAI error after %.0f ms: %s",
                embed_ms,
                e,
            )
            raise

        embed_ms = (datetime.now(UTC) - embed_start).total_seconds() * 1000
        embedding = response.data[0].embedding
        self.stats["tokens_used"] += response.usage.total_tokens
        logger.info(
            "generate_embedding: success | %.0f ms tokens=%d dim=%d",
            embed_ms,
            response.usage.total_tokens,
            len(embedding),
        )

        # Save to cache
        if use_cache:
            self._save_to_cache(text_hash, embedding)

        return embedding

    def truncate_to_coarse(self, embedding: list[float]) -> list[float]:
        """Truncate a full embedding to coarse dimensions (Matryoshka property)."""
        return embedding[: self.COARSE_DIMENSIONS]

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
    )
    async def generate_embeddings_batch(
        self,
        texts: list[str],
        use_cache: bool = True,
        batch_size: int = 100,
    ) -> list[list[float]]:
        """
        Generate embeddings for multiple texts in batch.

        Args:
            texts: List of texts.
            use_cache: Whether to use cache.
            batch_size: Maximum batch size.

        Returns:
            List of embeddings.
        """
        if not texts:
            return []

        results: list[list[float] | None] = [None] * len(texts)
        texts_to_embed: list[str] = []
        indices_to_embed: list[int] = []

        # Check cache first
        for i, text in enumerate(texts):
            if not text or not text.strip():
                results[i] = [0.0] * self.EMBEDDING_DIMENSIONS
                continue

            text = text.strip()[:8000]
            text_hash = self._compute_hash(text)

            if use_cache:
                cached = self._get_from_cache(text_hash)
                if cached:
                    results[i] = cached
                    continue

            texts_to_embed.append(text)
            indices_to_embed.append(i)

        # Process in batches
        for batch_start in range(0, len(texts_to_embed), batch_size):
            batch_end = min(batch_start + batch_size, len(texts_to_embed))
            batch_texts = texts_to_embed[batch_start:batch_end]
            batch_indices = indices_to_embed[batch_start:batch_end]

            self.stats["total_requests"] += 1

            try:
                response = await self.client.embeddings.create(
                    model=self.deployment,
                    input=batch_texts,
                )
            except (APIError, APIConnectionError, RateLimitError) as e:
                logger.error(f"OpenAI API error in batch embedding: {e}")
                raise

            self.stats["tokens_used"] += response.usage.total_tokens

            for j, emb_data in enumerate(response.data):
                idx = batch_indices[j]
                embedding = emb_data.embedding
                results[idx] = embedding

                # Save to cache
                if use_cache:
                    text_hash = self._compute_hash(batch_texts[j])
                    self._save_to_cache(text_hash, embedding)

        return results

    def compute_similarity(self, embedding1: list[float], embedding2: list[float]) -> float:
        """
        Compute cosine similarity between two embeddings.

        Args:
            embedding1: First embedding
            embedding2: Second embedding

        Returns:
            Cosine similarity (0-1)
        """
        import math

        dot_product = sum(a * b for a, b in zip(embedding1, embedding2))
        norm1 = math.sqrt(sum(a * a for a in embedding1))
        norm2 = math.sqrt(sum(b * b for b in embedding2))

        if norm1 == 0 or norm2 == 0:
            return 0.0

        return dot_product / (norm1 * norm2)

    def get_stats(self) -> dict:
        """Return service statistics."""
        return {
            **self.stats,
            "cache_hit_rate": (
                self.stats["cache_hits"] / self.stats["total_requests"]
                if self.stats["total_requests"] > 0
                else 0
            ),
        }


# =============================================================================
# Singleton
# =============================================================================

_embedding_service: EmbeddingService | None = None


def get_embedding_service(cache_service=None) -> EmbeddingService:
    """Get the singleton instance of EmbeddingService."""
    global _embedding_service
    if _embedding_service is None:
        _embedding_service = EmbeddingService(cache_service=cache_service)
    return _embedding_service
