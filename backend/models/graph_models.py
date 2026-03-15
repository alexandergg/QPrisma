"""
Knowledge Graph Models for QPrisma

This module defines the Pydantic models for the multimodal Knowledge Graph.
Hierarchical structure: Video -> Chapter -> Scene -> Frame -> Entity

Inspired by VideoRAG (HKUDS) for semantic video indexing.
"""

from datetime import UTC, datetime
from enum import Enum
from uuid import uuid4

from pydantic import BaseModel, Field

# =============================================================================
# Enums
# =============================================================================


class EntityType(str, Enum):
    """Types of entities that can be extracted from frames."""

    PERSON = "person"
    OBJECT = "object"
    LOCATION = "location"
    ACTION = "action"
    CONCEPT = "concept"
    TEXT = "text"  # OCR text detected
    BRAND = "brand"
    EVENT = "event"


class RelationType(str, Enum):
    """Types of relationships between graph nodes."""

    # Hierarchical
    CONTAINS = "CONTAINS"
    BELONGS_TO = "BELONGS_TO"

    # Temporal
    BEFORE = "BEFORE"
    AFTER = "AFTER"
    DURING = "DURING"
    STARTS_WITH = "STARTS_WITH"
    ENDS_WITH = "ENDS_WITH"
    SIMULTANEOUS = "SIMULTANEOUS"

    # Sequential chains (dense temporal)
    NEXT_FRAME = "NEXT_FRAME"
    NEXT_SEGMENT = "NEXT_SEGMENT"
    NEXT_SCENE = "NEXT_SCENE"

    # Semantic
    RELATES_TO = "RELATES_TO"
    SIMILAR_TO = "SIMILAR_TO"
    CAUSES = "CAUSES"
    CAUSED_BY = "CAUSED_BY"
    INTERACTS_WITH = "INTERACTS_WITH"
    APPEARS_WITH = "APPEARS_WITH"
    MENTIONED_IN = "MENTIONED_IN"

    # Cross-video
    SAME_ENTITY = "SAME_ENTITY"  # Same entity in different videos
    TOPIC_OVERLAP = "TOPIC_OVERLAP"

    # Community / Hierarchical summarization
    IN_COMMUNITY = "IN_COMMUNITY"  # Entity -> Community membership
    SUMMARIZES = "SUMMARIZES"  # Community -> Video (summary of)
    SUPPORTS = "SUPPORTS"  # Frame/AudioSegment -> Community (evidence)


class NodeType(str, Enum):
    """Node types in the graph."""

    VIDEO = "Video"
    CHAPTER = "Chapter"
    SCENE = "Scene"
    FRAME = "Frame"
    ENTITY = "Entity"
    AUDIO_SEGMENT = "AudioSegment"
    TOPIC = "Topic"
    COMMUNITY = "Community"


# =============================================================================
# Base Models
# =============================================================================


class GraphNodeBase(BaseModel):
    """Base model for all graph nodes."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    node_type: NodeType
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    # Embeddings for vector search
    embedding: list[float] | None = None
    embedding_model: str | None = None

    # Flexible metadata
    metadata: dict = Field(default_factory=dict)


class GraphRelationBase(BaseModel):
    """Base model for relationships between nodes."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    source_id: str
    target_id: str
    relation_type: RelationType
    weight: float = Field(default=1.0, ge=0.0, le=1.0)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    # Additional relationship properties
    properties: dict = Field(default_factory=dict)


# =============================================================================
# Video Hierarchy Nodes
# =============================================================================


class VideoNode(GraphNodeBase):
    """Root node representing a complete video."""

    node_type: NodeType = NodeType.VIDEO

    # Identification
    video_id: str  # ID in Cosmos DB / Blob Storage
    title: str
    description: str | None = None

    # Video metadata
    duration_seconds: float
    fps: float
    resolution: tuple[int, int]  # (width, height)
    file_size_bytes: int
    format: str  # mp4, avi, etc.

    # Processing
    total_frames: int
    extracted_frames: int
    processing_config: dict = Field(default_factory=dict)

    # AI-generated summary
    summary: str | None = None
    topics: list[str] = Field(default_factory=list)

    # URLs
    blob_url: str | None = None
    thumbnail_url: str | None = None


class ChapterNode(GraphNodeBase):
    """Node representing a chapter or logical segment of the video."""

    node_type: NodeType = NodeType.CHAPTER

    # Reference to parent video
    video_id: str

    # Temporal position
    start_time: float  # seconds
    end_time: float
    chapter_index: int

    # Content
    title: str | None = None
    summary: str | None = None
    topics: list[str] = Field(default_factory=list)

    # Detected automatically or manually
    detection_method: str = "auto"  # auto, manual, scene_change


class SceneNode(GraphNodeBase):
    """Node representing a scene (significant visual change)."""

    node_type: NodeType = NodeType.SCENE

    # References
    video_id: str
    chapter_id: str | None = None

    # Temporal position
    start_time: float
    end_time: float
    scene_index: int

    # Scene analysis
    description: str | None = None
    dominant_colors: list[str] = Field(default_factory=list)
    scene_type: str | None = None  # indoor, outdoor, closeup, etc.

    # Scene change metrics
    transition_type: str | None = None  # cut, fade, dissolve
    visual_change_score: float = 0.0


class FrameNode(GraphNodeBase):
    """Node representing an individual frame (keyframe)."""

    node_type: NodeType = NodeType.FRAME

    # References
    video_id: str
    scene_id: str | None = None

    # Position
    timestamp: float  # seconds
    frame_number: int

    # Frame analysis
    description: str | None = None  # GPT-4V description

    # Hashes for deduplication
    perceptual_hash: str | None = None
    content_hash: str | None = None

    # URLs
    image_url: str | None = None
    thumbnail_url: str | None = None

    # Quality
    blur_score: float = 0.0
    brightness: float = 0.0
    is_keyframe: bool = True


class AudioSegmentNode(GraphNodeBase):
    """Node representing a transcribed audio segment."""

    node_type: NodeType = NodeType.AUDIO_SEGMENT

    # References
    video_id: str

    # Temporal position
    start_time: float
    end_time: float

    # Transcription
    text: str
    language: str = "es"
    confidence: float = 0.0

    # Speaker diarization (if available)
    speaker_id: str | None = None
    speaker_label: str | None = None


# =============================================================================
# Entity Nodes
# =============================================================================


class EntityNode(GraphNodeBase):
    """Node representing an extracted entity (person, object, etc.)."""

    node_type: NodeType = NodeType.ENTITY

    # Entity type
    entity_type: EntityType

    # Identification
    name: str
    normalized_name: str  # Normalized name for matching
    aliases: list[str] = Field(default_factory=list)

    # Description
    description: str | None = None

    # Type-specific attributes
    attributes: dict = Field(default_factory=dict)
    # Example for PERSON: {"age_estimate": "adult", "gender": "male"}
    # Example for OBJECT: {"color": "red", "size": "large"}

    # Detection confidence
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)

    # Bounding box (if applicable)
    bounding_box: dict | None = None  # {"x": 0, "y": 0, "width": 100, "height": 100}

    # Cross-references
    external_ids: dict = Field(default_factory=dict)  # {"wikidata": "Q123", ...}

    # Occurrence frequency
    occurrence_count: int = 1
    first_seen_time: float | None = None
    last_seen_time: float | None = None


class CommunityNode(GraphNodeBase):
    """Node representing a thematic community detected via graph clustering.

    Communities group related entities and content segments that share a
    common theme, enabling macro-level reasoning and efficient retrieval
    for broad or thematic queries.
    """

    node_type: NodeType = NodeType.COMMUNITY

    # Identification
    community_id: str  # Unique within video (e.g. "{video_id}_c0")
    video_id: str

    # Content
    title: str  # Short label (LLM-generated)
    summary: str  # LLM-generated thematic summary
    themes: list[str] = Field(default_factory=list)

    # Membership
    member_entity_ids: list[str] = Field(default_factory=list)
    member_count: int = 0

    # Temporal span of member content
    time_span_start: float | None = None
    time_span_end: float | None = None

    # Hierarchy level (0 = leaf community, 1+ = aggregated)
    level: int = 0


class TopicNode(GraphNodeBase):
    """Node representing an abstract topic or concept."""

    node_type: NodeType = NodeType.TOPIC

    # Identification
    name: str
    normalized_name: str

    # Description
    description: str | None = None

    # Topic hierarchy
    parent_topic: str | None = None
    subtopics: list[str] = Field(default_factory=list)

    # Associated keywords
    keywords: list[str] = Field(default_factory=list)

    # Relevance
    relevance_score: float = 1.0


# =============================================================================
# Relationship Models
# =============================================================================


class TemporalRelation(GraphRelationBase):
    """Temporal relationship between two nodes."""

    # Temporal-specific properties
    time_gap_seconds: float | None = None  # Time difference


class SemanticRelation(GraphRelationBase):
    """Semantic relationship between entities."""

    # Relationship description
    description: str | None = None

    # Context where it was detected
    context_frame_id: str | None = None
    context_text: str | None = None


class CrossVideoRelation(GraphRelationBase):
    """Relationship between entities from different videos."""

    source_video_id: str
    target_video_id: str

    # Similarity
    similarity_score: float = Field(default=0.0, ge=0.0, le=1.0)


# =============================================================================
# Query & Response Models
# =============================================================================


class GraphSearchQuery(BaseModel):
    """Query for searching the Knowledge Graph."""

    # Search text
    query: str

    # Filters
    video_ids: list[str] | None = None
    entity_types: list[EntityType] | None = None
    node_types: list[NodeType] | None = None
    time_range: tuple[float, float] | None = None  # (start, end) in seconds

    # Search configuration
    use_vector_search: bool = True
    use_graph_expansion: bool = True
    expansion_hops: int = Field(default=2, ge=1, le=4)

    # Pagination
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class GraphSearchResult(BaseModel):
    """Search result from the Knowledge Graph."""

    # Found node
    node_id: str
    node_type: NodeType

    # Scores
    vector_score: float = 0.0
    graph_score: float = 0.0
    combined_score: float = 0.0

    # Content
    content: dict  # Node data

    # Graph context
    related_nodes: list[dict] = Field(default_factory=list)
    path_to_root: list[str] = Field(default_factory=list)

    # Highlight
    highlights: list[str] = Field(default_factory=list)


class GraphSearchResponse(BaseModel):
    """Complete search response."""

    query: str
    total_results: int
    results: list[GraphSearchResult]

    # Metrics
    search_time_ms: float
    vector_search_time_ms: float
    graph_expansion_time_ms: float

    # Facets for filtering
    facets: dict = Field(default_factory=dict)


# =============================================================================
# Graph Statistics
# =============================================================================


class GraphStats(BaseModel):
    """Knowledge Graph statistics."""

    # Node counts
    total_nodes: int = 0
    nodes_by_type: dict[str, int] = Field(default_factory=dict)

    # Relationship counts
    total_relations: int = 0
    relations_by_type: dict[str, int] = Field(default_factory=dict)

    # Videos
    total_videos: int = 0
    total_frames_indexed: int = 0
    total_entities_extracted: int = 0

    # Graph metrics
    avg_relations_per_node: float = 0.0
    max_depth: int = 0

    # Storage
    database_size_mb: float = 0.0

    # Time
    last_updated: datetime = Field(default_factory=lambda: datetime.now(UTC))


# =============================================================================
# Entity Extraction Models
# =============================================================================


class ExtractedEntity(BaseModel):
    """Entity extracted by GPT-4V from a frame."""

    entity_type: EntityType
    name: str
    confidence: float
    bounding_box: dict | None = None
    attributes: dict = Field(default_factory=dict)
    description: str | None = None


class FrameAnalysisResult(BaseModel):
    """Result of a frame analysis."""

    frame_id: str
    timestamp: float

    # General description
    description: str

    # Detected entities
    entities: list[ExtractedEntity]

    # Detected relationships between entities
    relations: list[dict]  # [{"source": "entity1", "target": "entity2", "type": "INTERACTS_WITH"}]

    # Topics/concepts
    topics: list[str]

    # Activities/actions
    actions: list[str]

    # Detected text (OCR)
    detected_text: list[str] = Field(default_factory=list)

    # Analysis metadata
    model_used: str = "gpt-4o"
    analysis_time_ms: float = 0.0


class VideoGraphSummary(BaseModel):
    """Summary of the graph for a specific video."""

    video_id: str
    video_title: str

    # Counts
    total_scenes: int
    total_frames: int
    total_entities: int
    unique_entities: int

    # Most frequent entities by type
    top_persons: list[dict] = Field(default_factory=list)
    top_objects: list[dict] = Field(default_factory=list)
    top_locations: list[dict] = Field(default_factory=list)

    # Main topics
    main_topics: list[str] = Field(default_factory=list)

    # Entity timeline
    entity_timeline: list[dict] = Field(default_factory=list)

    # Most common relationships
    top_relations: list[dict] = Field(default_factory=list)
