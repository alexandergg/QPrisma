"""
Services package for QPrisma.

This package contains all the service classes used by the API.
"""

from .audio_processor import AudioProcessor
from .auth_service import AuthService, get_auth_service
from .batch_processor import BatchProcessor
from .cache_service import CacheService, get_cache_service
from .database_service import DatabaseService, get_database_service
from .embedding_service import EmbeddingService, get_embedding_service
from .enhanced_search import EnhancedSearchService
from .entity_extractor import EntityExtractor, get_entity_extractor
from .export_service import ExportService, get_export_service
from .face_tracking_service import FaceTrackingService, get_face_tracking_service
from .ffmpeg_processor import FFmpegVideoProcessor
from .graph_search_service import GraphSearchService, get_graph_search_service
from .hierarchical_context_service import (
    HierarchicalContextService,
    get_hierarchical_context_service,
)
from .hierarchical_summarizer import HierarchicalSummarizer, SceneEmbeddingGenerator
from .knowledge_graph import KnowledgeGraphService, get_knowledge_graph_service
from .mem0_memory_service import Mem0MemoryService, get_mem0_memory_service
from .relation_builder import RelationBuilder, get_relation_builder
from .scene_analyzer import SceneAnalyzer
from .storage_tiering_service import StorageTieringService, get_storage_tiering_service
from .subtitle_service import SubtitleService, get_subtitle_service
from .tool_artifact_service import ToolArtifactService, get_tool_artifact_service
from .video_processor import VideoProcessor
from .viral_score_service import ViralScoreService, get_viral_score_service

__all__ = [
    # Core processors
    "VideoProcessor",
    "AudioProcessor",
    "FFmpegVideoProcessor",
    "BatchProcessor",
    # AI Services
    "EmbeddingService",
    "get_embedding_service",
    "EnhancedSearchService",
    "EntityExtractor",
    "get_entity_extractor",
    "HierarchicalSummarizer",
    "SceneEmbeddingGenerator",
    "SceneAnalyzer",
    "ViralScoreService",
    "get_viral_score_service",
    # Graph Services
    "KnowledgeGraphService",
    "get_knowledge_graph_service",
    "GraphSearchService",
    "get_graph_search_service",
    "RelationBuilder",
    "get_relation_builder",
    "HierarchicalContextService",
    "get_hierarchical_context_service",
    "Mem0MemoryService",
    "get_mem0_memory_service",
    # Export Services
    "ExportService",
    "get_export_service",
    "SubtitleService",
    "get_subtitle_service",
    "FaceTrackingService",
    "get_face_tracking_service",
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
