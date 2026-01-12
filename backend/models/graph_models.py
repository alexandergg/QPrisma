"""
Knowledge Graph Models for QPrisma

Este módulo define los modelos Pydantic para el Knowledge Graph multimodal.
Estructura jerárquica: Video → Chapter → Scene → Frame → Entity

Inspirado en VideoRAG (HKUDS) para indexación semántica de video.
"""

from datetime import datetime
from enum import Enum
from uuid import uuid4

from pydantic import BaseModel, Field

# =============================================================================
# Enums
# =============================================================================


class EntityType(str, Enum):
    """Tipos de entidades que pueden ser extraídas de frames."""

    PERSON = "person"
    OBJECT = "object"
    LOCATION = "location"
    ACTION = "action"
    CONCEPT = "concept"
    TEXT = "text"  # OCR text detected
    BRAND = "brand"
    EVENT = "event"


class RelationType(str, Enum):
    """Tipos de relaciones entre nodos del grafo."""

    # Jerárquicas
    CONTAINS = "CONTAINS"
    BELONGS_TO = "BELONGS_TO"

    # Temporales
    BEFORE = "BEFORE"
    AFTER = "AFTER"
    DURING = "DURING"
    STARTS_WITH = "STARTS_WITH"
    ENDS_WITH = "ENDS_WITH"
    SIMULTANEOUS = "SIMULTANEOUS"

    # Semánticas
    RELATES_TO = "RELATES_TO"
    SIMILAR_TO = "SIMILAR_TO"
    CAUSES = "CAUSES"
    CAUSED_BY = "CAUSED_BY"
    INTERACTS_WITH = "INTERACTS_WITH"
    APPEARS_WITH = "APPEARS_WITH"
    MENTIONED_IN = "MENTIONED_IN"

    # Cross-video
    SAME_ENTITY = "SAME_ENTITY"  # Misma entidad en diferentes videos
    TOPIC_OVERLAP = "TOPIC_OVERLAP"


class NodeType(str, Enum):
    """Tipos de nodos en el grafo."""

    VIDEO = "Video"
    CHAPTER = "Chapter"
    SCENE = "Scene"
    FRAME = "Frame"
    ENTITY = "Entity"
    AUDIO_SEGMENT = "AudioSegment"
    TOPIC = "Topic"


# =============================================================================
# Base Models
# =============================================================================


class GraphNodeBase(BaseModel):
    """Modelo base para todos los nodos del grafo."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    node_type: NodeType
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    # Embeddings para búsqueda vectorial
    embedding: list[float] | None = None
    embedding_model: str | None = None

    # Metadata flexible
    metadata: dict = Field(default_factory=dict)


class GraphRelationBase(BaseModel):
    """Modelo base para relaciones entre nodos."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    source_id: str
    target_id: str
    relation_type: RelationType
    weight: float = Field(default=1.0, ge=0.0, le=1.0)
    created_at: datetime = Field(default_factory=datetime.utcnow)

    # Propiedades adicionales de la relación
    properties: dict = Field(default_factory=dict)


# =============================================================================
# Video Hierarchy Nodes
# =============================================================================


class VideoNode(GraphNodeBase):
    """Nodo raíz que representa un video completo."""

    node_type: NodeType = NodeType.VIDEO

    # Identificación
    video_id: str  # ID en Cosmos DB / Blob Storage
    title: str
    description: str | None = None

    # Metadata del video
    duration_seconds: float
    fps: float
    resolution: tuple[int, int]  # (width, height)
    file_size_bytes: int
    format: str  # mp4, avi, etc.

    # Procesamiento
    total_frames: int
    extracted_frames: int
    processing_config: dict = Field(default_factory=dict)

    # Summary generado por IA
    ai_summary: str | None = None
    topics: list[str] = Field(default_factory=list)

    # URLs
    blob_url: str | None = None
    thumbnail_url: str | None = None


class ChapterNode(GraphNodeBase):
    """Nodo que representa un capítulo o segmento lógico del video."""

    node_type: NodeType = NodeType.CHAPTER

    # Referencia al video padre
    video_id: str

    # Posición temporal
    start_time: float  # segundos
    end_time: float
    chapter_index: int

    # Contenido
    title: str | None = None
    summary: str | None = None
    topics: list[str] = Field(default_factory=list)

    # Detectado automáticamente o manual
    detection_method: str = "auto"  # auto, manual, scene_change


class SceneNode(GraphNodeBase):
    """Nodo que representa una escena (cambio visual significativo)."""

    node_type: NodeType = NodeType.SCENE

    # Referencias
    video_id: str
    chapter_id: str | None = None

    # Posición temporal
    start_time: float
    end_time: float
    scene_index: int

    # Análisis de escena
    description: str | None = None
    dominant_colors: list[str] = Field(default_factory=list)
    scene_type: str | None = None  # indoor, outdoor, closeup, etc.

    # Métricas de cambio de escena
    transition_type: str | None = None  # cut, fade, dissolve
    visual_change_score: float = 0.0


class FrameNode(GraphNodeBase):
    """Nodo que representa un frame individual (keyframe)."""

    node_type: NodeType = NodeType.FRAME

    # Referencias
    video_id: str
    scene_id: str | None = None

    # Posición
    timestamp: float  # segundos
    frame_number: int

    # Análisis del frame
    description: str | None = None  # Descripción de GPT-4V

    # Hashes para deduplicación
    perceptual_hash: str | None = None
    content_hash: str | None = None

    # URLs
    image_url: str | None = None
    thumbnail_url: str | None = None

    # Calidad
    blur_score: float = 0.0
    brightness: float = 0.0
    is_keyframe: bool = True


class AudioSegmentNode(GraphNodeBase):
    """Nodo que representa un segmento de audio transcrito."""

    node_type: NodeType = NodeType.AUDIO_SEGMENT

    # Referencias
    video_id: str

    # Posición temporal
    start_time: float
    end_time: float

    # Transcripción
    text: str
    language: str = "es"
    confidence: float = 0.0

    # Speaker diarization (si está disponible)
    speaker_id: str | None = None
    speaker_label: str | None = None


# =============================================================================
# Entity Nodes
# =============================================================================


class EntityNode(GraphNodeBase):
    """Nodo que representa una entidad extraída (persona, objeto, etc.)."""

    node_type: NodeType = NodeType.ENTITY

    # Tipo de entidad
    entity_type: EntityType

    # Identificación
    name: str
    normalized_name: str  # Nombre normalizado para matching
    aliases: list[str] = Field(default_factory=list)

    # Descripción
    description: str | None = None

    # Atributos específicos del tipo
    attributes: dict = Field(default_factory=dict)
    # Ejemplo para PERSON: {"age_estimate": "adult", "gender": "male"}
    # Ejemplo para OBJECT: {"color": "red", "size": "large"}

    # Confianza de detección
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)

    # Bounding box (si aplica)
    bounding_box: dict | None = None  # {"x": 0, "y": 0, "width": 100, "height": 100}

    # Referencias cruzadas
    external_ids: dict = Field(default_factory=dict)  # {"wikidata": "Q123", ...}

    # Frecuencia de aparición
    occurrence_count: int = 1
    first_seen_time: float | None = None
    last_seen_time: float | None = None


class TopicNode(GraphNodeBase):
    """Nodo que representa un tema o concepto abstracto."""

    node_type: NodeType = NodeType.TOPIC

    # Identificación
    name: str
    normalized_name: str

    # Descripción
    description: str | None = None

    # Jerarquía de temas
    parent_topic: str | None = None
    subtopics: list[str] = Field(default_factory=list)

    # Keywords asociados
    keywords: list[str] = Field(default_factory=list)

    # Relevancia
    relevance_score: float = 1.0


# =============================================================================
# Relationship Models
# =============================================================================


class TemporalRelation(GraphRelationBase):
    """Relación temporal entre dos nodos."""

    # Propiedades temporales específicas
    time_gap_seconds: float | None = None  # Diferencia de tiempo


class SemanticRelation(GraphRelationBase):
    """Relación semántica entre entidades."""

    # Descripción de la relación
    description: str | None = None

    # Contexto donde se detectó
    context_frame_id: str | None = None
    context_text: str | None = None


class CrossVideoRelation(GraphRelationBase):
    """Relación entre entidades de diferentes videos."""

    source_video_id: str
    target_video_id: str

    # Similitud
    similarity_score: float = Field(default=0.0, ge=0.0, le=1.0)


# =============================================================================
# Query & Response Models
# =============================================================================


class GraphSearchQuery(BaseModel):
    """Query para búsqueda en el Knowledge Graph."""

    # Texto de búsqueda
    query: str

    # Filtros
    video_ids: list[str] | None = None
    entity_types: list[EntityType] | None = None
    node_types: list[NodeType] | None = None
    time_range: tuple[float, float] | None = None  # (start, end) en segundos

    # Configuración de búsqueda
    use_vector_search: bool = True
    use_graph_expansion: bool = True
    expansion_hops: int = Field(default=2, ge=1, le=4)

    # Paginación
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class GraphSearchResult(BaseModel):
    """Resultado de búsqueda en el Knowledge Graph."""

    # Nodo encontrado
    node_id: str
    node_type: NodeType

    # Scores
    vector_score: float = 0.0
    graph_score: float = 0.0
    combined_score: float = 0.0

    # Contenido
    content: dict  # Datos del nodo

    # Contexto del grafo
    related_nodes: list[dict] = Field(default_factory=list)
    path_to_root: list[str] = Field(default_factory=list)

    # Highlight
    highlights: list[str] = Field(default_factory=list)


class GraphSearchResponse(BaseModel):
    """Respuesta completa de búsqueda."""

    query: str
    total_results: int
    results: list[GraphSearchResult]

    # Métricas
    search_time_ms: float
    vector_search_time_ms: float
    graph_expansion_time_ms: float

    # Facets para filtrado
    facets: dict = Field(default_factory=dict)


# =============================================================================
# Graph Statistics
# =============================================================================


class GraphStats(BaseModel):
    """Estadísticas del Knowledge Graph."""

    # Conteos de nodos
    total_nodes: int = 0
    nodes_by_type: dict[str, int] = Field(default_factory=dict)

    # Conteos de relaciones
    total_relations: int = 0
    relations_by_type: dict[str, int] = Field(default_factory=dict)

    # Videos
    total_videos: int = 0
    total_frames_indexed: int = 0
    total_entities_extracted: int = 0

    # Métricas del grafo
    avg_relations_per_node: float = 0.0
    max_depth: int = 0

    # Almacenamiento
    database_size_mb: float = 0.0

    # Tiempo
    last_updated: datetime = Field(default_factory=datetime.utcnow)


# =============================================================================
# Entity Extraction Models
# =============================================================================


class ExtractedEntity(BaseModel):
    """Entidad extraída por GPT-4V de un frame."""

    entity_type: EntityType
    name: str
    confidence: float
    bounding_box: dict | None = None
    attributes: dict = Field(default_factory=dict)
    description: str | None = None


class FrameAnalysisResult(BaseModel):
    """Resultado del análisis de un frame."""

    frame_id: str
    timestamp: float

    # Descripción general
    description: str

    # Entidades detectadas
    entities: list[ExtractedEntity]

    # Relaciones detectadas entre entidades
    relations: list[dict]  # [{"source": "entity1", "target": "entity2", "type": "INTERACTS_WITH"}]

    # Temas/conceptos
    topics: list[str]

    # Actividades/acciones
    actions: list[str]

    # Texto detectado (OCR)
    detected_text: list[str] = Field(default_factory=list)

    # Metadata del análisis
    model_used: str = "gpt-4o"
    analysis_time_ms: float = 0.0


class VideoGraphSummary(BaseModel):
    """Resumen del grafo de un video específico."""

    video_id: str
    video_title: str

    # Conteos
    total_scenes: int
    total_frames: int
    total_entities: int
    unique_entities: int

    # Entidades más frecuentes por tipo
    top_persons: list[dict] = Field(default_factory=list)
    top_objects: list[dict] = Field(default_factory=list)
    top_locations: list[dict] = Field(default_factory=list)

    # Temas principales
    main_topics: list[str] = Field(default_factory=list)

    # Timeline de entidades
    entity_timeline: list[dict] = Field(default_factory=list)

    # Relaciones más comunes
    top_relations: list[dict] = Field(default_factory=list)
