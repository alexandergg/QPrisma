"""
Embedding Service for QPrisma

Genera embeddings usando Azure OpenAI text-embedding-3-large.
Proporciona cache de embeddings y batch processing.
"""

import hashlib
import logging
import os

from openai import AzureOpenAI, APIError, APIConnectionError, RateLimitError
from tenacity import retry, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)


class EmbeddingService:
    """
    Servicio para generar embeddings con Azure OpenAI.

    Características:
    - text-embedding-3-large (3072 dimensiones)
    - Batch processing para eficiencia
    - Cache de embeddings por hash de contenido
    - Retry con exponential backoff
    """

    # Dimensiones del modelo text-embedding-3-large
    EMBEDDING_DIMENSIONS = 3072

    def __init__(
        self,
        api_key: str | None = None,
        endpoint: str | None = None,
        deployment: str | None = None,
        api_version: str = "2024-08-01-preview",
        cache_service=None,
    ):
        """
        Inicializa el servicio de embeddings.

        Args:
            api_key: Azure OpenAI API key
            endpoint: Azure OpenAI endpoint
            deployment: Nombre del deployment de embeddings
            api_version: Versión del API
            cache_service: Servicio de cache opcional
        """
        self.api_key = api_key or os.getenv("AZURE_OPENAI_API_KEY")
        self.endpoint = endpoint or os.getenv("AZURE_OPENAI_ENDPOINT")
        self.deployment = deployment or os.getenv(
            "AZURE_OPENAI_DEPLOYMENT_EMBEDDING", "text-embedding-3-large"
        )
        self.api_version = api_version
        self.cache_service = cache_service

        self._client: AzureOpenAI | None = None

        # Estadísticas
        self.stats = {
            "total_requests": 0,
            "cache_hits": 0,
            "tokens_used": 0,
        }

    @property
    def client(self) -> AzureOpenAI:
        """Lazy initialization del cliente Azure OpenAI."""
        if self._client is None:
            self._client = AzureOpenAI(
                api_key=self.api_key,
                api_version=self.api_version,
                azure_endpoint=self.endpoint,
            )
        return self._client

    def _compute_hash(self, text: str) -> str:
        """Computa hash SHA-256 del texto para cache."""
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def _get_from_cache(self, text_hash: str) -> list[float] | None:
        """Intenta obtener embedding del cache."""
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
        """Guarda embedding en cache (default: 7 días)."""
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
    def generate_embedding(self, text: str, use_cache: bool = True) -> list[float]:
        """
        Genera embedding para un texto.

        Args:
            text: Texto a embedear
            use_cache: Si usar cache

        Returns:
            Lista de floats (embedding de 3072 dimensiones)
        """
        if not text or not text.strip():
            # Retornar embedding de ceros para texto vacío
            return [0.0] * self.EMBEDDING_DIMENSIONS

        # Normalizar texto
        text = text.strip()[:8000]  # Limitar a 8000 chars

        # Intentar cache
        text_hash = self._compute_hash(text)
        if use_cache:
            cached = self._get_from_cache(text_hash)
            if cached:
                return cached

        # Generar embedding
        self.stats["total_requests"] += 1

        try:
            response = self.client.embeddings.create(
                model=self.deployment,
                input=text,
            )
        except (APIError, APIConnectionError, RateLimitError) as e:
            logger.error(f"OpenAI API error generating embedding: {e}")
            raise

        embedding = response.data[0].embedding
        self.stats["tokens_used"] += response.usage.total_tokens

        # Guardar en cache
        if use_cache:
            self._save_to_cache(text_hash, embedding)

        return embedding

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
    )
    def generate_embeddings_batch(
        self,
        texts: list[str],
        use_cache: bool = True,
        batch_size: int = 100,
    ) -> list[list[float]]:
        """
        Genera embeddings para múltiples textos en batch.

        Args:
            texts: Lista de textos.
            use_cache: Si usar cache.
            batch_size: Tamaño máximo de batch.

        Returns:
            Lista de embeddings.
        """
        if not texts:
            return []

        results: list[list[float] | None] = [None] * len(texts)
        texts_to_embed: list[str] = []
        indices_to_embed: list[int] = []

        # Verificar cache primero
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

        # Procesar en batches
        for batch_start in range(0, len(texts_to_embed), batch_size):
            batch_end = min(batch_start + batch_size, len(texts_to_embed))
            batch_texts = texts_to_embed[batch_start:batch_end]
            batch_indices = indices_to_embed[batch_start:batch_end]

            self.stats["total_requests"] += 1

            try:
                response = self.client.embeddings.create(
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

                # Guardar en cache
                if use_cache:
                    text_hash = self._compute_hash(batch_texts[j])
                    self._save_to_cache(text_hash, embedding)

        return results

    def compute_similarity(self, embedding1: list[float], embedding2: list[float]) -> float:
        """
        Calcula similitud coseno entre dos embeddings.

        Args:
            embedding1: Primer embedding
            embedding2: Segundo embedding

        Returns:
            Similitud coseno (0-1)
        """
        import math

        dot_product = sum(a * b for a, b in zip(embedding1, embedding2))
        norm1 = math.sqrt(sum(a * a for a in embedding1))
        norm2 = math.sqrt(sum(b * b for b in embedding2))

        if norm1 == 0 or norm2 == 0:
            return 0.0

        return dot_product / (norm1 * norm2)

    def get_stats(self) -> dict:
        """Retorna estadísticas del servicio."""
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
    """Obtiene la instancia singleton del EmbeddingService."""
    global _embedding_service
    if _embedding_service is None:
        _embedding_service = EmbeddingService(cache_service=cache_service)
    return _embedding_service
