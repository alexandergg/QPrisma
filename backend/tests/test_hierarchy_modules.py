"""
Unit tests for the extracted hierarchy modules.

Tests HierarchyEmbeddingGenerator and HierarchyNodeFactory in isolation
with mocked dependencies (no Neo4j or Azure OpenAI required).
"""

from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

from services.hierarchical_context_service import (
    EmbeddingPoolStrategy,
    HierarchicalConfig,
)

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def config():
    """Default hierarchical config for testing."""
    return HierarchicalConfig(
        embedding_dimensions=10,  # small for tests
        pool_strategy=EmbeddingPoolStrategy.WEIGHTED_MEAN,
        compress_chapter_embeddings=False,
        compress_video_embeddings=False,
        compressed_dimensions=5,
    )


@pytest.fixture
def mock_embedding_service():
    """Mocked EmbeddingService returning deterministic embeddings."""
    svc = AsyncMock()

    # Return normalised 10-dim vector seeded by first char of text
    async def _gen(text: str):
        seed = sum(ord(c) for c in text[:8])
        rng = np.random.RandomState(seed)
        vec = rng.randn(10)
        vec = vec / np.linalg.norm(vec)
        return vec.tolist()

    svc.generate_embedding = AsyncMock(side_effect=_gen)
    return svc


@pytest.fixture
def embedding_generator(mock_embedding_service, config):
    from services.hierarchy_embedding_generator import HierarchyEmbeddingGenerator

    return HierarchyEmbeddingGenerator(
        embedding_service=mock_embedding_service,
        config=config,
    )


@pytest.fixture
def mock_kg_service():
    """Mocked KnowledgeGraphService with execute_query and a fake driver/session."""
    svc = MagicMock()
    # Phase 7: HierarchyNodeFactory now uses execute_query() instead of _driver.session()
    svc.execute_query.return_value = {"id": "test-id"}
    # Keep session mock for any remaining direct session usage (e.g., ensure_vector_indexes)
    mock_session = MagicMock()
    mock_session.__enter__ = MagicMock(return_value=mock_session)
    mock_session.__exit__ = MagicMock(return_value=False)
    svc._driver.session.return_value = mock_session
    mock_result = MagicMock()
    mock_result.single.return_value = {"id": "test-id"}
    mock_session.run.return_value = mock_result
    return svc


@pytest.fixture
def node_factory(mock_kg_service):
    from services.hierarchy_node_factory import HierarchyNodeFactory

    return HierarchyNodeFactory(knowledge_graph=mock_kg_service)


# =============================================================================
# HierarchyEmbeddingGenerator – Pooling
# =============================================================================


class TestEmbeddingPooling:
    """Tests for pool_embeddings and compress_embedding."""

    def test_pool_empty_returns_zeros(self, embedding_generator):
        result = embedding_generator.pool_embeddings([])
        assert len(result) == 10
        assert all(v == 0.0 for v in result)

    def test_pool_single_returns_same(self, embedding_generator):
        emb = [1.0] * 10
        result = embedding_generator.pool_embeddings([emb])
        assert result is emb

    def test_pool_mean_strategy(self, embedding_generator):
        emb1 = [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
        emb2 = [0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
        result = embedding_generator.pool_embeddings(
            [emb1, emb2], strategy=EmbeddingPoolStrategy.MEAN
        )
        assert len(result) == 10
        # Normalized mean of [0.5, 0.5, 0, ...] → each ≈ 0.707
        assert abs(result[0] - result[1]) < 1e-6

    def test_pool_weighted_mean(self, embedding_generator):
        emb1 = [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
        emb2 = [0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
        result = embedding_generator.pool_embeddings(
            [emb1, emb2],
            weights=[3.0, 1.0],
            strategy=EmbeddingPoolStrategy.WEIGHTED_MEAN,
        )
        # First dimension should dominate
        assert result[0] > result[1]

    def test_pool_max_strategy(self, embedding_generator):
        emb1 = [1.0, 0.0, 0.5, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
        emb2 = [0.0, 1.0, 0.3, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
        result = embedding_generator.pool_embeddings(
            [emb1, emb2], strategy=EmbeddingPoolStrategy.MAX_POOL
        )
        # Before normalisation, max([1,0], [0,1]) → [1,1]
        assert abs(result[0] - result[1]) < 1e-6

    def test_pool_default_strategy_from_config(self, config):
        """Default strategy comes from config.pool_strategy."""
        from services.hierarchy_embedding_generator import HierarchyEmbeddingGenerator

        config.pool_strategy = EmbeddingPoolStrategy.MEAN
        gen = HierarchyEmbeddingGenerator(embedding_service=MagicMock(), config=config)
        emb1 = [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
        emb2 = [0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
        result = gen.pool_embeddings([emb1, emb2])
        assert abs(result[0] - result[1]) < 1e-6  # MEAN gives equal

    def test_compress_no_op_when_smaller(self, embedding_generator):
        emb = [1.0, 2.0, 3.0]
        result = embedding_generator.compress_embedding(emb, target_dims=10)
        assert result is emb

    def test_compress_reduces_dimensions(self, embedding_generator):
        emb = list(np.random.randn(20))
        result = embedding_generator.compress_embedding(emb, target_dims=5)
        assert len(result) == 5
        # Should be normalised
        norm = np.linalg.norm(result)
        assert abs(norm - 1.0) < 1e-6


# =============================================================================
# HierarchyEmbeddingGenerator – Text Building
# =============================================================================


class TestTextBuilding:
    """Tests for build_scene_text, build_chapter_text, build_video_text."""

    def test_build_scene_text(self, embedding_generator):
        scene = MagicMock()
        scene.title = "Intro"
        scene.summary = "A beginning"
        scene.visual_description = "Person talking"
        scene.transcript_segment = "Hello world"
        scene.detected_objects = ["person", "mic"]
        text = embedding_generator.build_scene_text(scene)
        assert "Intro" in text
        assert "A beginning" in text
        assert "Visual: Person talking" in text
        assert "Speech: Hello world" in text
        assert "Contains: person, mic" in text

    def test_build_scene_text_empty(self, embedding_generator):
        scene = MagicMock()
        scene.title = ""
        scene.summary = ""
        scene.visual_description = ""
        scene.transcript_segment = ""
        scene.detected_objects = []
        assert embedding_generator.build_scene_text(scene) == ""

    def test_build_chapter_text(self, embedding_generator):
        chapter = {"title": "Ch1", "summary": "First part", "themes": ["intro", "setup"]}
        text = embedding_generator.build_chapter_text(chapter)
        assert "Ch1" in text
        assert "First part" in text
        assert "Themes: intro, setup" in text

    def test_build_chapter_text_empty(self, embedding_generator):
        assert embedding_generator.build_chapter_text({}) == ""

    def test_build_video_text(self, embedding_generator):
        structure = MagicMock()
        structure.video_title = "My Video"
        structure.video_summary = "Great content"
        structure.key_topics = ["ai", "ml"]
        text = embedding_generator.build_video_text(structure)
        assert "My Video" in text
        assert "Great content" in text
        assert "Topics: ai, ml" in text


# =============================================================================
# HierarchyEmbeddingGenerator – Async Embedding Generation
# =============================================================================


class TestEmbeddingGeneration:
    """Tests for generate_scene/chapter/video_embedding."""

    @pytest.mark.asyncio
    async def test_generate_scene_embedding_with_text(
        self, embedding_generator, mock_embedding_service
    ):
        scene = MagicMock()
        scene.title = "Test scene"
        scene.summary = "A test"
        scene.visual_description = ""
        scene.transcript_segment = ""
        scene.detected_objects = []

        result = await embedding_generator.generate_scene_embedding(scene)
        assert len(result) == 10
        mock_embedding_service.generate_embedding.assert_called_once()

    @pytest.mark.asyncio
    async def test_generate_scene_embedding_with_frames(
        self, embedding_generator, mock_embedding_service
    ):
        scene = MagicMock()
        scene.title = "Scene"
        scene.summary = "Sum"
        scene.visual_description = ""
        scene.transcript_segment = ""
        scene.detected_objects = []

        frames = [list(np.random.randn(10)) for _ in range(3)]
        result = await embedding_generator.generate_scene_embedding(scene, frame_embeddings=frames)
        assert len(result) == 10

    @pytest.mark.asyncio
    async def test_generate_scene_embedding_empty(self, embedding_generator):
        scene = MagicMock()
        scene.title = ""
        scene.summary = ""
        scene.visual_description = ""
        scene.transcript_segment = ""
        scene.detected_objects = []

        result = await embedding_generator.generate_scene_embedding(scene)
        assert len(result) == 10
        assert all(v == 0.0 for v in result)

    @pytest.mark.asyncio
    async def test_generate_chapter_embedding(self, embedding_generator, mock_embedding_service):
        chapter = {"title": "Ch", "summary": "Test chapter"}
        scene_embs = [list(np.random.randn(10)) for _ in range(2)]
        durations = [30.0, 20.0]

        result = await embedding_generator.generate_chapter_embedding(
            chapter, scene_embs, durations
        )
        assert len(result) == 10

    @pytest.mark.asyncio
    async def test_generate_chapter_embedding_with_compression(
        self, config, mock_embedding_service
    ):
        from services.hierarchy_embedding_generator import HierarchyEmbeddingGenerator

        config.compress_chapter_embeddings = True
        config.compressed_dimensions = 5
        gen = HierarchyEmbeddingGenerator(mock_embedding_service, config)

        chapter = {"title": "Ch", "summary": "Compressed"}
        result = await gen.generate_chapter_embedding(chapter, [], [])
        assert len(result) == 5

    @pytest.mark.asyncio
    async def test_generate_video_embedding(self, embedding_generator, mock_embedding_service):
        structure = MagicMock()
        structure.video_title = "Vid"
        structure.video_summary = "Summary"
        structure.key_topics = ["topic"]

        chapter_embs = [list(np.random.randn(10)) for _ in range(3)]
        durations = [60.0, 40.0, 20.0]

        result = await embedding_generator.generate_video_embedding(
            structure, chapter_embs, durations
        )
        assert len(result) == 10


# =============================================================================
# HierarchyNodeFactory
# =============================================================================


class TestNodeFactory:
    """Tests for HierarchyNodeFactory with mocked KnowledgeGraphService."""

    def test_create_chapter_node(self, node_factory, mock_kg_service):
        chapter = MagicMock()
        chapter.id = "ch-1"
        chapter.video_id = "v-1"
        chapter.user_id = "user-1"
        chapter.start_time = 0.0
        chapter.end_time = 30.0
        chapter.chapter_index = 0
        chapter.title = "Intro"
        chapter.summary = "First"
        chapter.topics = ["intro"]

        result = node_factory.create_chapter_node(chapter)
        assert result == "test-id"
        mock_kg_service.execute_query.assert_called()
        call_kwargs = mock_kg_service.execute_query.call_args
        assert call_kwargs[0][1]["user_id"] == "user-1"

    def test_create_scene_node(self, node_factory, mock_kg_service):
        scene = MagicMock()
        scene.id = "sc-1"
        scene.video_id = "v-1"
        scene.chapter_id = "ch-1"
        scene.user_id = "user-1"
        scene.start_time = 0.0
        scene.end_time = 10.0
        scene.scene_index = 0
        scene.description = "Opening"

        result = node_factory.create_scene_node(scene)
        assert result == "test-id"
        call_kwargs = mock_kg_service.execute_query.call_args
        assert call_kwargs[0][1]["user_id"] == "user-1"

    def test_create_chapters_batch(self, node_factory, mock_kg_service):
        chapters = [
            {"id": "c1", "video_id": "v-1", "user_id": "user-1"},
            {"id": "c2", "video_id": "v-1"},
        ]
        node_factory.create_chapters_batch(chapters)
        mock_kg_service.execute_query.assert_called()
        call_kwargs = mock_kg_service.execute_query.call_args
        assert call_kwargs[0][1]["batch"][0]["user_id"] == "user-1"

    def test_create_scenes_batch(self, node_factory, mock_kg_service):
        scenes = [
            {"id": "s1", "video_id": "v-1", "user_id": "user-1"},
            {"id": "s2", "video_id": "v-1"},
        ]
        node_factory.create_scenes_batch(scenes)
        mock_kg_service.execute_query.assert_called()
        call_kwargs = mock_kg_service.execute_query.call_args
        assert call_kwargs[0][1]["batch"][0]["user_id"] == "user-1"

    def test_create_relationship(self, node_factory, mock_kg_service):
        from models.graph_models import RelationType

        node_factory.create_relationship("a", "b", RelationType.CONTAINS)
        mock_kg_service.execute_query.assert_called()

    def test_create_relationships_batch(self, node_factory, mock_kg_service):
        from models.graph_models import RelationType

        rels = [{"source_id": "a", "target_id": "b"}]
        node_factory.create_relationships_batch(rels, RelationType.CONTAINS)
        mock_kg_service.execute_query.assert_called()

    def test_store_embedding_node(self, node_factory, mock_kg_service):
        from models.graph_models import NodeType

        node_factory.store_embedding_node("n1", [0.1] * 10, NodeType.VIDEO)
        mock_kg_service.execute_query.assert_called()

    def test_store_embeddings_batch_adds_coarse(self, node_factory, mock_kg_service):
        embs = [{"node_id": "n1", "embedding": list(range(600))}]
        node_factory.store_embeddings_batch(embs)
        # Should have added coarse truncation
        assert "embedding_coarse" in embs[0]
        assert len(embs[0]["embedding_coarse"]) == 512

    def test_store_embeddings_batch_short_embedding(self, node_factory, mock_kg_service):
        embs = [{"node_id": "n1", "embedding": [0.1, 0.2, 0.3]}]
        node_factory.store_embeddings_batch(embs)
        # Short embedding → coarse == full
        assert embs[0]["embedding_coarse"] == [0.1, 0.2, 0.3]

    @pytest.mark.asyncio
    async def test_ensure_vector_indexes(self, node_factory, mock_kg_service):
        await node_factory.ensure_vector_indexes()
        # Should have created 6 indexes (3 full + 3 coarse) via execute_query
        assert mock_kg_service.execute_query.call_count >= 6


# =============================================================================
# Orchestrator Delegation
# =============================================================================


class TestOrchestratorDelegation:
    """Verify HierarchicalContextService delegates correctly."""

    @pytest.fixture
    def service(self, config):
        """Build service with mocked internals."""
        mock_graph = MagicMock()
        mock_graph.is_connected = True
        mock_emb = MagicMock()

        with (
            patch("services.hierarchical_context_service.SceneAnalyzer"),
            patch("services.hierarchical_context_service.HierarchicalSummarizer"),
        ):
            from services.hierarchical_context_service import HierarchicalContextService

            svc = HierarchicalContextService(
                graph_service=mock_graph,
                embedding_service=mock_emb,
                config=config,
            )
        return svc

    def test_pool_embeddings_delegates(self, service):
        service._embedding_generator = MagicMock()
        service._embedding_generator.pool_embeddings.return_value = [1.0]
        result = service._pool_embeddings([[1.0]], [1.0], EmbeddingPoolStrategy.MEAN)
        service._embedding_generator.pool_embeddings.assert_called_once_with(
            [[1.0]], [1.0], EmbeddingPoolStrategy.MEAN
        )
        assert result == [1.0]

    def test_compress_embedding_delegates(self, service):
        service._embedding_generator = MagicMock()
        service._embedding_generator.compress_embedding.return_value = [0.5]
        result = service._compress_embedding([1.0, 2.0], 1)
        service._embedding_generator.compress_embedding.assert_called_once_with([1.0, 2.0], 1)
        assert result == [0.5]

    def test_node_factory_accessible(self, service):
        """After Phase 8 inlining, storage calls go directly to _node_factory."""
        assert hasattr(service, "_node_factory")

    def test_query_service_accessible(self, service):
        """Phase 8: query methods are delegated to _query_service."""
        assert hasattr(service, "_query_service")

    def test_build_scene_text_delegates(self, service):
        service._embedding_generator = MagicMock()
        service._embedding_generator.build_scene_text.return_value = "text"
        scene = MagicMock()
        result = service._build_scene_text(scene)
        assert result == "text"
        service._embedding_generator.build_scene_text.assert_called_once_with(scene)
