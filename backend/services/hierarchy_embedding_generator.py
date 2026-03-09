"""
Hierarchy Embedding Generator for QPrisma
==========================================

Generates and pools embeddings at each hierarchy level (scene, chapter, video)
using configurable pooling strategies and optional dimensionality compression.

Extracted from :class:`HierarchicalContextService` to isolate embedding
concerns from graph storage and search orchestration.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import numpy as np

from services.hierarchical_context_service import EmbeddingPoolStrategy

if TYPE_CHECKING:
    from services.embedding_service import EmbeddingService
    from services.hierarchical_context_service import HierarchicalConfig
    from services.scene_analyzer import Scene, VideoStructure

logger = logging.getLogger(__name__)


class HierarchyEmbeddingGenerator:
    """Generates and pools embeddings for video hierarchy levels.

    Handles:
    - Embedding pooling (mean, weighted, max) across child embeddings
    - Dimensionality compression for higher-level embeddings
    - Text construction for each hierarchy level
    - Embedding generation via the underlying :class:`EmbeddingService`
    """

    def __init__(
        self,
        embedding_service: EmbeddingService,
        config: HierarchicalConfig,
    ) -> None:
        self._embedding_service = embedding_service
        self._config = config

    # =========================================================================
    # Pooling & Compression
    # =========================================================================

    def pool_embeddings(
        self,
        embeddings: list[list[float]],
        weights: list[float] | None = None,
        strategy: EmbeddingPoolStrategy | None = None,
    ) -> list[float]:
        """
        Pool multiple embeddings into a single embedding.

        Args:
            embeddings: List of embeddings to pool
            weights: Optional weights for weighted averaging
            strategy: Pooling strategy to use

        Returns:
            Single pooled embedding
        """
        if not embeddings:
            return [0.0] * self._config.embedding_dimensions

        if len(embeddings) == 1:
            return embeddings[0]

        strategy = strategy or self._config.pool_strategy
        embeddings_array = np.array(embeddings)

        if strategy == EmbeddingPoolStrategy.MEAN:
            pooled = np.mean(embeddings_array, axis=0)

        elif strategy == EmbeddingPoolStrategy.WEIGHTED_MEAN:
            if weights is None:
                weights = [1.0] * len(embeddings)
            weights = np.array(weights) / sum(weights)
            pooled = np.average(embeddings_array, axis=0, weights=weights)

        elif strategy == EmbeddingPoolStrategy.MAX_POOL:
            pooled = np.max(embeddings_array, axis=0)

        else:  # Default to mean
            pooled = np.mean(embeddings_array, axis=0)

        # Normalize
        norm = np.linalg.norm(pooled)
        if norm > 0:
            pooled = pooled / norm

        return pooled.tolist()

    def compress_embedding(self, embedding: list[float], target_dims: int) -> list[float]:
        """
        Compress embedding to lower dimensionality using PCA-like reduction.

        Simple approach: select evenly spaced dimensions.
        For production, use proper PCA or learned projection.
        """
        if len(embedding) <= target_dims:
            return embedding

        # Simple dimensionality reduction: select evenly spaced
        step = len(embedding) / target_dims
        indices = [int(i * step) for i in range(target_dims)]
        compressed = [embedding[i] for i in indices]

        # Normalize
        norm = np.linalg.norm(compressed)
        if norm > 0:
            compressed = (np.array(compressed) / norm).tolist()

        return compressed

    # =========================================================================
    # Embedding Generation
    # =========================================================================

    async def generate_scene_embedding(
        self, scene: Scene, frame_embeddings: list[list[float]] | None = None
    ) -> list[float]:
        """
        Generate embedding for a scene.

        Combines:
        1. Summary text embedding
        2. Pooled frame embeddings (if available)
        """
        embeddings_to_pool = []
        weights = []

        # Generate summary embedding (primary)
        summary_text = self.build_scene_text(scene)
        if summary_text:
            summary_embedding = await self._embedding_service.generate_embedding(summary_text)
            embeddings_to_pool.append(summary_embedding)
            weights.append(2.0)  # Higher weight for summary

        # Pool frame embeddings (secondary)
        if frame_embeddings:
            pooled_frames = self.pool_embeddings(frame_embeddings)
            embeddings_to_pool.append(pooled_frames)
            weights.append(1.0)

        if not embeddings_to_pool:
            return [0.0] * self._config.embedding_dimensions

        return self.pool_embeddings(embeddings_to_pool, weights)

    async def generate_chapter_embedding(
        self, chapter: dict, scene_embeddings: list[list[float]], scene_durations: list[float]
    ) -> list[float]:
        """
        Generate embedding for a chapter.

        Combines:
        1. Chapter summary embedding
        2. Weighted pool of scene embeddings (by duration)
        """
        embeddings_to_pool = []
        weights = []

        # Generate chapter summary embedding
        chapter_text = self.build_chapter_text(chapter)
        if chapter_text:
            chapter_embedding = await self._embedding_service.generate_embedding(chapter_text)
            embeddings_to_pool.append(chapter_embedding)
            weights.append(2.0)

        # Pool scene embeddings weighted by duration
        if scene_embeddings:
            pooled_scenes = self.pool_embeddings(
                scene_embeddings, scene_durations, EmbeddingPoolStrategy.WEIGHTED_MEAN
            )
            embeddings_to_pool.append(pooled_scenes)
            weights.append(1.0)

        result = self.pool_embeddings(embeddings_to_pool, weights)

        # Optionally compress
        if self._config.compress_chapter_embeddings:
            result = self.compress_embedding(result, self._config.compressed_dimensions)

        return result

    async def generate_video_embedding(
        self,
        structure: VideoStructure,
        chapter_embeddings: list[list[float]],
        chapter_durations: list[float],
    ) -> list[float]:
        """
        Generate embedding for entire video.

        Combines:
        1. Video summary embedding
        2. Weighted pool of chapter embeddings
        """
        embeddings_to_pool = []
        weights = []

        # Generate video summary embedding
        video_text = self.build_video_text(structure)
        if video_text:
            video_embedding = await self._embedding_service.generate_embedding(video_text)
            embeddings_to_pool.append(video_embedding)
            weights.append(2.0)

        # Pool chapter embeddings weighted by duration
        if chapter_embeddings:
            pooled_chapters = self.pool_embeddings(
                chapter_embeddings, chapter_durations, EmbeddingPoolStrategy.WEIGHTED_MEAN
            )
            embeddings_to_pool.append(pooled_chapters)
            weights.append(1.0)

        result = self.pool_embeddings(embeddings_to_pool, weights)

        # Optionally compress
        if self._config.compress_video_embeddings:
            result = self.compress_embedding(result, self._config.compressed_dimensions)

        return result

    # =========================================================================
    # Text Building
    # =========================================================================

    def build_scene_text(self, scene: Scene) -> str:
        """Build text representation for scene embedding."""
        parts = []

        if scene.title:
            parts.append(scene.title)
        if scene.summary:
            parts.append(scene.summary)
        if scene.visual_description:
            parts.append(f"Visual: {scene.visual_description}")
        if scene.transcript_segment:
            parts.append(f"Speech: {scene.transcript_segment[:500]}")
        if scene.detected_objects:
            parts.append(f"Contains: {', '.join(scene.detected_objects[:10])}")

        return " | ".join(parts) if parts else ""

    def build_chapter_text(self, chapter: dict) -> str:
        """Build text representation for chapter embedding."""
        parts = []

        if chapter.get("title"):
            parts.append(chapter["title"])
        if chapter.get("summary"):
            parts.append(chapter["summary"])
        if chapter.get("themes"):
            parts.append(f"Themes: {', '.join(chapter['themes'])}")

        return " | ".join(parts) if parts else ""

    def build_video_text(self, structure: VideoStructure) -> str:
        """Build text representation for video embedding."""
        parts = []

        if structure.video_title:
            parts.append(structure.video_title)
        if structure.video_summary:
            parts.append(structure.video_summary)
        if structure.key_topics:
            parts.append(f"Topics: {', '.join(structure.key_topics)}")

        return " | ".join(parts) if parts else ""
