"""
Services package for QPrisma.

This package contains all the service classes used by the API.
"""

from .audio_processor import AudioProcessor
from .auth_service import AuthService, get_auth_service
from .batch_processor import BatchProcessor
from .cache_service import CacheService, get_cache_service
from .coverage_analyzer import CoverageAnalyzer
from .cross_video_search_service import CrossVideoSearchService, get_cross_video_search_service
from .database_service import DatabaseService, get_database_service
from .embedding_service import EmbeddingService, get_embedding_service
from .enhanced_search import EnhancedSearchService
from .entity_extractor import EntityExtractor, get_entity_extractor
from .ffmpeg_processor import FFmpegVideoProcessor
from .graph_expander import GraphExpander
from .graph_node_repository import GraphNodeRepository
from .graph_search_service import GraphSearchService, get_graph_search_service
from .hierarchical_context_service import (
    HierarchicalContextService,
    get_hierarchical_context_service,
)
from .hierarchical_summarizer import HierarchicalSummarizer, SceneEmbeddingGenerator
from .hierarchy_embedding_generator import HierarchyEmbeddingGenerator
from .hierarchy_node_factory import HierarchyNodeFactory
from .highlight_detection_service import HighlightDetectionService, get_highlight_detection_service
from .knowledge_graph import KnowledgeGraphService, get_knowledge_graph_service
from .mem0_memory_service import Mem0MemoryService, get_mem0_memory_service
from .processing_metrics import PipelineMetrics, ProcessingTimer, StageMetrics
from .relation_builder import RelationBuilder, get_relation_builder
from .scene_analyzer import SceneAnalyzer
from .storage_tiering_service import StorageTieringService, get_storage_tiering_service
from .timestamp_calculator import TimestampCalculator
from .tool_artifact_service import ToolArtifactService, get_tool_artifact_service
from .video_processor import VideoProcessor

__all__ = [
    # Core processors
    "VideoProcessor",
    "AudioProcessor",
    "FFmpegVideoProcessor",
    "BatchProcessor",
    # Video processing specialists
    "CoverageAnalyzer",
    "TimestampCalculator",
    # AI Services
    "EmbeddingService",
    "get_embedding_service",
    "EnhancedSearchService",
    "EntityExtractor",
    "get_entity_extractor",
    "HierarchicalSummarizer",
    "SceneEmbeddingGenerator",
    "SceneAnalyzer",
    # Cross-Video Search
    "CrossVideoSearchService",
    "get_cross_video_search_service",
    # Graph Services
    "KnowledgeGraphService",
    "get_knowledge_graph_service",
    "GraphNodeRepository",
    "GraphExpander",
    "GraphSearchService",
    "get_graph_search_service",
    "HighlightDetectionService",
    "get_highlight_detection_service",
    "RelationBuilder",
    "get_relation_builder",
    "HierarchicalContextService",
    "get_hierarchical_context_service",
    "HierarchyEmbeddingGenerator",
    "HierarchyNodeFactory",
    "Mem0MemoryService",
    "get_mem0_memory_service",
    # Processing Metrics
    "PipelineMetrics",
    "ProcessingTimer",
    "StageMetrics",
    # Storage & Cache
    "CacheService",
    "get_cache_service",
    "DatabaseService",
    "get_database_service",
    "StorageTieringService",
    "get_storage_tiering_service",
    "ToolArtifactService",
    "get_tool_artifact_service",
    # Auth
    "AuthService",
    "get_auth_service",
]
