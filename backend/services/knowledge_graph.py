"""
Knowledge Graph Service for QPrisma

Primary service for managing the multimodal Knowledge Graph in Neo4j.
Provides CRUD operations, hybrid search, and graph expansion for RAG.

Requires Neo4j 5.x with the APOC plugin.
"""

import logging
from contextlib import asynccontextmanager, contextmanager

from neo4j import AsyncDriver, AsyncGraphDatabase, AsyncSession, Driver, GraphDatabase, Session
from neo4j.exceptions import AuthError, ServiceUnavailable

from core.config import settings
from core.serializers import sanitize_for_json
from models.graph_models import (
    AudioSegmentNode,
    EntityNode,
    EntityType,
    FrameNode,
    GraphStats,
    RelationType,
    SceneNode,
    VideoNode,
)

logger = logging.getLogger(__name__)


class KnowledgeGraphService:
    """
    Service for managing the QPrisma Knowledge Graph in Neo4j.

    Features:
    - Connection pooling
    - CRUD for hierarchical nodes (Video -> Scene -> Frame -> Entity)
    - Temporal and semantic relations
    - Hybrid search (vector + graph traversal)
    - Graph expansion for RAG context
    """

    def __init__(
        self,
        uri: str | None = None,
        user: str | None = None,
        password: str | None = None,
        database: str = "neo4j",
    ):
        """
        Initialize the connection to Neo4j.

        Args:
            uri: Connection URI (default from settings)
            user: Username (default from settings)
            password: Password (default from settings)
            database: Database to use (default from settings)
        """
        self.uri = uri or settings.neo4j.uri
        self.user = user or settings.neo4j.user
        self.password = password or settings.neo4j.password
        self.database = database or settings.neo4j.database

        self._driver: Driver | None = None
        self._async_driver: AsyncDriver | None = None
        self._connected = False
        self._async_connected = False
        self._schema_initialized = False

    # =========================================================================
    # Connection Management
    # =========================================================================

    def connect(self) -> bool:
        """Establish a connection to Neo4j."""
        try:
            self._driver = GraphDatabase.driver(
                self.uri,
                auth=(self.user, self.password),
                max_connection_lifetime=3600,
                max_connection_pool_size=50,
                connection_acquisition_timeout=60,
            )
            # Verify connection
            self._driver.verify_connectivity()
            self._connected = True
            logger.info(f"Connected to Neo4j at {self.uri}")

            # Initialize schema/indexes once per process
            if not self._schema_initialized:
                try:
                    self.initialize_schema()
                    self._schema_initialized = True
                except Exception as e:
                    logger.warning(f"Neo4j schema initialization failed: {e}")

            return True
        except AuthError as e:
            logger.error(f"Neo4j authentication failed: {e}")
            self._connected = False
            return False
        except ServiceUnavailable as e:
            logger.error(f"Neo4j service unavailable: {e}")
            self._connected = False
            return False
        except Exception as e:
            logger.error(f"Failed to connect to Neo4j: {e}")
            self._connected = False
            return False

    def disconnect(self) -> None:
        """Close the connection to Neo4j."""
        if self._driver:
            self._driver.close()
            self._driver = None
            self._connected = False
            self._schema_initialized = False
            logger.info("Disconnected from Neo4j")
        if self._async_driver:
            # For sync disconnect of async driver, caller should use async_disconnect
            self._async_driver = None
            self._async_connected = False

    @property
    def is_connected(self) -> bool:
        """Check whether an active connection exists."""
        return self._connected and self._driver is not None

    @contextmanager
    def get_session(self) -> Session:
        """Context manager for obtaining a Neo4j session."""
        if not self.is_connected:
            self.connect()

        session = self._driver.session(database=self.database)
        try:
            yield session
        finally:
            session.close()

    def _execute_query(
        self,
        query: str,
        params: dict | None = None,
        single: bool = False,
        unpack_key: str | None = None,
    ) -> list[dict] | dict | None:
        """
        Execute a Neo4j query with centralized session management.

        Args:
            query: Cypher query string
            params: Query parameters (optional)
            single: If True, return single record; otherwise return list
            unpack_key: If provided, extract this key from each record

        Returns:
            Single dict, list of dicts, or None depending on params
        """
        params = params or {}
        with self.get_session() as session:
            result = session.run(query, **params)

            if single:
                record = result.single()
                if record is None:
                    return None
                if unpack_key:
                    return dict(record[unpack_key])
                return dict(record)

            records = list(result)
            if unpack_key:
                return [dict(r[unpack_key]) for r in records]
            return [dict(r) for r in records]

    # =========================================================================
    # Async Connection Management
    # =========================================================================

    async def async_connect(self) -> bool:
        """Establish an async connection to Neo4j."""
        try:
            self._async_driver = AsyncGraphDatabase.driver(
                self.uri,
                auth=(self.user, self.password),
                max_connection_lifetime=3600,
                max_connection_pool_size=50,
                connection_acquisition_timeout=60,
            )
            await self._async_driver.verify_connectivity()
            self._async_connected = True
            logger.info(f"Async connected to Neo4j at {self.uri}")
            return True
        except (AuthError, ServiceUnavailable) as e:
            logger.error(f"Neo4j async connection failed: {e}")
            self._async_connected = False
            return False
        except Exception as e:
            logger.error(f"Failed async connect to Neo4j: {e}")
            self._async_connected = False
            return False

    async def async_disconnect(self):
        """Close the async connection to Neo4j."""
        if self._async_driver:
            await self._async_driver.close()
            self._async_driver = None
            self._async_connected = False
            logger.info("Async disconnected from Neo4j")

    @property
    def is_async_connected(self) -> bool:
        """Check whether an active async connection exists."""
        return self._async_connected and self._async_driver is not None

    @asynccontextmanager
    async def get_async_session(self) -> AsyncSession:
        """Async context manager for obtaining a Neo4j session."""
        if not self.is_async_connected:
            await self.async_connect()

        session = self._async_driver.session(database=self.database)
        try:
            yield session
        finally:
            await session.close()

    async def async_execute_query(
        self,
        query: str,
        params: dict | None = None,
        single: bool = False,
        unpack_key: str | None = None,
    ) -> list[dict] | dict | None:
        """
        Execute a Neo4j query asynchronously.

        Args:
            query: Cypher query string
            params: Query parameters (optional)
            single: If True, return single record; otherwise return list
            unpack_key: If provided, extract this key from each record

        Returns:
            Single dict, list of dicts, or None depending on params
        """
        params = params or {}
        async with self.get_async_session() as session:
            result = await session.run(query, **params)

            if single:
                record = await result.single()
                if record is None:
                    return None
                if unpack_key:
                    return dict(record[unpack_key])
                return dict(record)

            records = [record async for record in result]
            if unpack_key:
                return [dict(r[unpack_key]) for r in records]
            return [dict(r) for r in records]

    # =========================================================================
    # Schema & Indexes
    # =========================================================================

    def initialize_schema(self) -> None:
        """Create required indexes and constraints in Neo4j."""
        with self.get_session() as session:
            # Uniqueness constraints
            constraints = [
                "CREATE CONSTRAINT video_id IF NOT EXISTS FOR (v:Video) REQUIRE v.id IS UNIQUE",
                "CREATE CONSTRAINT chapter_id IF NOT EXISTS FOR (c:Chapter) REQUIRE c.id IS UNIQUE",
                "CREATE CONSTRAINT scene_id IF NOT EXISTS FOR (s:Scene) REQUIRE s.id IS UNIQUE",
                "CREATE CONSTRAINT frame_id IF NOT EXISTS FOR (f:Frame) REQUIRE f.id IS UNIQUE",
                "CREATE CONSTRAINT entity_id IF NOT EXISTS FOR (e:Entity) REQUIRE e.id IS UNIQUE",
                "CREATE CONSTRAINT topic_id IF NOT EXISTS FOR (t:Topic) REQUIRE t.id IS UNIQUE",
                "CREATE CONSTRAINT audio_id IF NOT EXISTS FOR (a:AudioSegment) REQUIRE a.id IS UNIQUE",
            ]

            # Indexes for search
            indexes = [
                # Indexes by video_id for fast filtering
                "CREATE INDEX video_video_id IF NOT EXISTS FOR (v:Video) ON (v.video_id)",
                "CREATE INDEX scene_video_id IF NOT EXISTS FOR (s:Scene) ON (s.video_id)",
                "CREATE INDEX frame_video_id IF NOT EXISTS FOR (f:Frame) ON (f.video_id)",
                "CREATE INDEX entity_video_id IF NOT EXISTS FOR (e:Entity) ON (e.video_id)",
                "CREATE INDEX audio_video_id IF NOT EXISTS FOR (a:AudioSegment) ON (a.video_id)",
                # Indexes by timestamp for temporal queries
                "CREATE INDEX frame_timestamp IF NOT EXISTS FOR (f:Frame) ON (f.timestamp)",
                "CREATE INDEX scene_start_time IF NOT EXISTS FOR (s:Scene) ON (s.start_time)",
                "CREATE INDEX audio_start_time IF NOT EXISTS FOR (a:AudioSegment) ON (a.start_time)",
                # Indexes by entity type
                "CREATE INDEX entity_type IF NOT EXISTS FOR (e:Entity) ON (e.entity_type)",
                "CREATE INDEX entity_name IF NOT EXISTS FOR (e:Entity) ON (e.normalized_name)",
                # Full-text indexes for text search
                "CREATE FULLTEXT INDEX entity_search IF NOT EXISTS FOR (e:Entity) ON EACH [e.name, e.description]",
                "CREATE FULLTEXT INDEX frame_search IF NOT EXISTS FOR (f:Frame) ON EACH [f.description]",
                "CREATE FULLTEXT INDEX topic_search IF NOT EXISTS FOR (t:Topic) ON EACH [t.name, t.description]",
                "CREATE FULLTEXT INDEX audio_search IF NOT EXISTS FOR (a:AudioSegment) ON EACH [a.text]",
            ]

            for constraint in constraints:
                try:
                    session.run(constraint)
                except Exception as e:
                    logger.debug(f"Constraint may already exist: {e}")

            for index in indexes:
                try:
                    session.run(index)
                except Exception as e:
                    logger.debug(f"Index may already exist: {e}")

            logger.info("Neo4j schema initialized successfully")

    # =========================================================================
    # Video Node Operations
    # =========================================================================

    def create_video_node(self, video: VideoNode) -> str:
        """Create a Video node in the graph."""
        query = """
        CREATE (v:Video {
            id: $id,
            video_id: $video_id,
            title: $title,
            description: $description,
            duration_seconds: $duration_seconds,
            fps: $fps,
            resolution: $resolution,
            file_size_bytes: $file_size_bytes,
            format: $format,
            total_frames: $total_frames,
            extracted_frames: $extracted_frames,
            ai_summary: $ai_summary,
            topics: $topics,
            blob_url: $blob_url,
            thumbnail_url: $thumbnail_url,
            created_at: datetime($created_at),
            updated_at: datetime($updated_at)
        })
        RETURN v.id as id
        """

        with self.get_session() as session:
            result = session.run(
                query,
                id=video.id,
                video_id=video.video_id,
                title=video.title,
                description=video.description,
                duration_seconds=video.duration_seconds,
                fps=video.fps,
                resolution=list(video.resolution),
                file_size_bytes=video.file_size_bytes,
                format=video.format,
                total_frames=video.total_frames,
                extracted_frames=video.extracted_frames,
                ai_summary=video.ai_summary,
                topics=video.topics,
                blob_url=video.blob_url,
                thumbnail_url=video.thumbnail_url,
                created_at=video.created_at.isoformat(),
                updated_at=video.updated_at.isoformat(),
            )
            record = result.single()
            logger.info(f"Created Video node: {video.id}")
            return record["id"]

    def get_video_node(self, video_id: str) -> dict | None:
        """Retrieve a Video node by its video_id (or legacy id)."""
        query = """
        MATCH (v:Video)
        WHERE v.video_id = $video_id OR v.id = $video_id
        RETURN v
        """
        return self._execute_query(query, {"video_id": video_id}, single=True, unpack_key="v")

    def get_video_summary(self, video_id: str) -> tuple[str | None, list[str]]:
        """Get video summary and topics from the knowledge graph.

        Returns:
            Tuple of (summary, topics_list). Summary may be None if not found.
        """
        query = """
        MATCH (v:Video)
        WHERE v.video_id = $media_id OR v.id = $media_id
        RETURN v.summary as summary, v.topics as topics
        """
        record = self._execute_query(query, {"media_id": video_id}, single=True)
        if record:
            summary = record.get("summary")
            topics = record.get("topics", [])
            if isinstance(topics, str):
                topics = [t.strip() for t in topics.split(",") if t.strip()]
            return summary, topics or []
        return None, []

    def update_video_summary(self, video_id: str, summary: str, topics: list[str]):
        """Update the AI summary and topics for a video."""
        query = """
        MATCH (v:Video {video_id: $video_id})
        SET v.ai_summary = $summary,
            v.topics = $topics,
            v.updated_at = datetime()
        RETURN v.id
        """
        self._execute_query(query, {"video_id": video_id, "summary": summary, "topics": topics})

    # =========================================================================
    # Scene Node Operations
    # =========================================================================

    def create_scene_node(self, scene: SceneNode) -> str:
        """Create a Scene node and connect it to its Video."""
        query = """
        MATCH (v:Video {video_id: $video_id})
        CREATE (s:Scene {
            id: $id,
            video_id: $video_id,
            start_time: $start_time,
            end_time: $end_time,
            scene_index: $scene_index,
            description: $description,
            dominant_colors: $dominant_colors,
            scene_type: $scene_type,
            transition_type: $transition_type,
            visual_change_score: $visual_change_score,
            created_at: datetime($created_at)
        })
        CREATE (v)-[:CONTAINS]->(s)
        RETURN s.id as id
        """

        with self.get_session() as session:
            result = session.run(
                query,
                id=scene.id,
                video_id=scene.video_id,
                start_time=scene.start_time,
                end_time=scene.end_time,
                scene_index=scene.scene_index,
                description=scene.description,
                dominant_colors=scene.dominant_colors,
                scene_type=scene.scene_type,
                transition_type=scene.transition_type,
                visual_change_score=scene.visual_change_score,
                created_at=scene.created_at.isoformat(),
            )
            record = result.single()
            return record["id"]

    def get_video_scenes(self, video_id: str) -> list[dict]:
        """Retrieve all scenes for a video, ordered by start time."""
        query = """
        MATCH (v:Video)-[:CONTAINS]->(s:Scene)
        WHERE v.video_id = $video_id OR v.id = $video_id
        RETURN s
        ORDER BY s.start_time
        """
        return self._execute_query(query, {"video_id": video_id}, unpack_key="s")

    def get_scene_frames(self, scene_id: str) -> list[dict]:
        """Retrieve all frames for a scene, ordered by timestamp."""
        query = """
        MATCH (s:Scene {id: $scene_id})-[:CONTAINS]->(f:Frame)
        RETURN f.id as id, f.timestamp as timestamp, f.description as description
        ORDER BY f.timestamp
        """
        return self._execute_query(query, {"scene_id": scene_id})

    def get_video_frames(self, video_id: str) -> list[dict]:
        """Retrieve all frames for a video together with their descriptions."""
        query = """
        MATCH (v:Video)-[:CONTAINS*1..2]->(f:Frame)
        WHERE v.video_id = $video_id OR v.id = $video_id
        RETURN DISTINCT f.id as id, f.timestamp as timestamp, f.frame_number as frame_number,
               f.description as description, f.scene_id as scene_id
        ORDER BY f.timestamp
        """
        return self._execute_query(query, {"video_id": video_id})

    # =========================================================================
    # Frame Node Operations
    # =========================================================================

    def create_frame_node(self, frame: FrameNode) -> str:
        """Create a Frame node and connect it to its Scene (if present) or Video."""
        if frame.scene_id:
            query = """
            MATCH (s:Scene {id: $scene_id})
            CREATE (f:Frame {
                id: $id,
                video_id: $video_id,
                scene_id: $scene_id,
                timestamp: $timestamp,
                frame_number: $frame_number,
                description: $description,
                perceptual_hash: $perceptual_hash,
                content_hash: $content_hash,
                image_url: $image_url,
                blur_score: $blur_score,
                brightness: $brightness,
                is_keyframe: $is_keyframe,
                created_at: datetime($created_at)
            })
            CREATE (s)-[:CONTAINS]->(f)
            RETURN f.id as id
            """
        else:
            query = """
            MATCH (v:Video {video_id: $video_id})
            CREATE (f:Frame {
                id: $id,
                video_id: $video_id,
                timestamp: $timestamp,
                frame_number: $frame_number,
                description: $description,
                perceptual_hash: $perceptual_hash,
                content_hash: $content_hash,
                image_url: $image_url,
                blur_score: $blur_score,
                brightness: $brightness,
                is_keyframe: $is_keyframe,
                created_at: datetime($created_at)
            })
            CREATE (v)-[:CONTAINS]->(f)
            RETURN f.id as id
            """

        with self.get_session() as session:
            result = session.run(
                query,
                id=frame.id,
                video_id=frame.video_id,
                scene_id=frame.scene_id,
                timestamp=frame.timestamp,
                frame_number=frame.frame_number,
                description=frame.description,
                perceptual_hash=frame.perceptual_hash,
                content_hash=frame.content_hash,
                image_url=frame.image_url,
                blur_score=frame.blur_score,
                brightness=frame.brightness,
                is_keyframe=frame.is_keyframe,
                created_at=frame.created_at.isoformat(),
            )
            record = result.single()
            return record["id"]

    def create_frames_batch(self, frames: list[FrameNode]) -> int:
        """Create multiple Frame nodes in a single batch for better performance."""
        query = """
        UNWIND $frames as frame
        MATCH (v:Video {video_id: frame.video_id})
        CREATE (f:Frame {
            id: frame.id,
            video_id: frame.video_id,
            timestamp: frame.timestamp,
            frame_number: frame.frame_number,
            description: frame.description,
            perceptual_hash: frame.perceptual_hash,
            image_url: frame.image_url,
            is_keyframe: frame.is_keyframe,
            created_at: datetime(frame.created_at)
        })
        CREATE (v)-[:CONTAINS]->(f)
        RETURN count(f) as created
        """

        frames_data = [
            {
                "id": f.id,
                "video_id": f.video_id,
                "timestamp": f.timestamp,
                "frame_number": f.frame_number,
                "description": f.description,
                "perceptual_hash": f.perceptual_hash,
                "image_url": f.image_url,
                "is_keyframe": f.is_keyframe,
                "created_at": f.created_at.isoformat(),
            }
            for f in frames
        ]

        with self.get_session() as session:
            result = session.run(query, frames=frames_data)
            record = result.single()
            count = record["created"]
            logger.info(f"Created {count} Frame nodes in batch")
            return count

    # =========================================================================
    # Entity Node Operations
    # =========================================================================

    def create_entity_node(self, entity: EntityNode, frame_id: str) -> str:
        """Create an Entity node and connect it to the Frame where it was detected."""
        query = """
        MATCH (f:Frame {id: $frame_id})
        MERGE (e:Entity {normalized_name: $normalized_name, entity_type: $entity_type})
        ON CREATE SET
            e.id = $id,
            e.name = $name,
            e.description = $description,
            e.attributes = $attributes,
            e.confidence = $confidence,
            e.occurrence_count = 1,
            e.first_seen_time = f.timestamp,
            e.last_seen_time = f.timestamp,
            e.created_at = datetime($created_at)
        ON MATCH SET
            e.occurrence_count = e.occurrence_count + 1,
            e.last_seen_time = f.timestamp,
            e.confidence = CASE WHEN $confidence > e.confidence THEN $confidence ELSE e.confidence END
        CREATE (f)-[:CONTAINS {confidence: $confidence, bounding_box: $bounding_box}]->(e)
        RETURN e.id as id
        """

        with self.get_session() as session:
            result = session.run(
                query,
                id=entity.id,
                frame_id=frame_id,
                name=entity.name,
                normalized_name=entity.normalized_name,
                entity_type=entity.entity_type.value,
                description=entity.description,
                attributes=str(entity.attributes),  # Neo4j does not support nested maps directly
                confidence=entity.confidence,
                bounding_box=str(entity.bounding_box) if entity.bounding_box else None,
                created_at=entity.created_at.isoformat(),
            )
            record = result.single()
            return record["id"]

    def create_entities_batch(self, entities: list[tuple[EntityNode, str]]) -> int:
        """
        Create multiple Entity nodes in a single batch.

        Args:
            entities: List of (EntityNode, frame_id) tuples
        """
        query = """
        UNWIND $entities as entity
        MATCH (f:Frame {id: entity.frame_id})
        MERGE (e:Entity {normalized_name: entity.normalized_name, entity_type: entity.entity_type})
        ON CREATE SET
            e.id = entity.id,
            e.name = entity.name,
            e.description = entity.description,
            e.confidence = entity.confidence,
            e.occurrence_count = 1,
            e.first_seen_time = f.timestamp,
            e.created_at = datetime(entity.created_at)
        ON MATCH SET
            e.occurrence_count = e.occurrence_count + 1,
            e.last_seen_time = f.timestamp
        CREATE (f)-[:CONTAINS {confidence: entity.confidence}]->(e)
        RETURN count(e) as created
        """

        entities_data = [
            {
                "id": e.id,
                "frame_id": frame_id,
                "name": e.name,
                "normalized_name": e.normalized_name,
                "entity_type": e.entity_type.value,
                "description": e.description,
                "confidence": e.confidence,
                "created_at": e.created_at.isoformat(),
            }
            for e, frame_id in entities
        ]

        with self.get_session() as session:
            result = session.run(query, entities=entities_data)
            record = result.single()
            return record["created"]

    def get_entity_by_name(self, name: str, entity_type: EntityType | None = None) -> dict | None:
        """Look up an entity by its normalized name."""
        normalized = name.lower().strip()

        if entity_type:
            query = """
            MATCH (e:Entity {normalized_name: $name, entity_type: $type})
            RETURN e
            """
            params = {"name": normalized, "type": entity_type.value}
        else:
            query = """
            MATCH (e:Entity {normalized_name: $name})
            RETURN e
            """
            params = {"name": normalized}

        return self._execute_query(query, params, single=True, unpack_key="e")

    # =========================================================================
    # Audio Segment (Transcript) Operations
    # =========================================================================

    def create_audio_segment(self, segment: AudioSegmentNode) -> str:
        """Create an AudioSegment (transcript) node and connect it to its Video."""
        query = """
        MATCH (v:Video)
        WHERE v.video_id = $video_id OR v.id = $video_id
        CREATE (a:AudioSegment {
            id: $id,
            video_id: $video_id,
            start_time: $start_time,
            end_time: $end_time,
            text: $text,
            language: $language,
            confidence: $confidence,
            speaker_id: $speaker_id,
            speaker_label: $speaker_label,
            created_at: datetime($created_at)
        })
        CREATE (v)-[:HAS_TRANSCRIPT]->(a)
        RETURN a.id as id
        """

        with self.get_session() as session:
            result = session.run(
                query,
                id=segment.id,
                video_id=segment.video_id,
                start_time=segment.start_time,
                end_time=segment.end_time,
                text=segment.text,
                language=segment.language,
                confidence=segment.confidence,
                speaker_id=segment.speaker_id,
                speaker_label=segment.speaker_label,
                created_at=segment.created_at.isoformat(),
            )
            record = result.single()
            if record:
                return record["id"]
            return segment.id

    def create_audio_segments_batch(
        self, segments: list[AudioSegmentNode], batch_size: int = 100
    ) -> int:
        """
        Create multiple AudioSegment nodes in batches.

        Args:
            segments: List of AudioSegmentNode instances to create
            batch_size: Number of nodes per batch to avoid timeouts

        Returns:
            Total number of segments created
        """
        if not segments:
            return 0

        # Use MERGE to avoid duplicate errors
        query = """
        UNWIND $segments as seg
        MERGE (a:AudioSegment {id: seg.id})
        SET a.video_id = seg.video_id,
            a.start_time = seg.start_time,
            a.end_time = seg.end_time,
            a.text = seg.text,
            a.language = seg.language,
            a.confidence = seg.confidence,
            a.created_at = datetime(seg.created_at)
        WITH a, seg
        OPTIONAL MATCH (v:Video)
        WHERE v.video_id = seg.video_id OR v.id = seg.video_id
        FOREACH (_ IN CASE WHEN v IS NOT NULL THEN [1] ELSE [] END |
            MERGE (v)-[:HAS_TRANSCRIPT]->(a)
        )
        RETURN count(a) as created
        """

        total_created = 0

        # Process in batches to avoid timeouts on large volumes
        for i in range(0, len(segments), batch_size):
            batch = segments[i : i + batch_size]
            segments_data = [
                {
                    "id": s.id,
                    "video_id": s.video_id,
                    "start_time": s.start_time,
                    "end_time": s.end_time,
                    "text": s.text,
                    "language": s.language,
                    "confidence": s.confidence,
                    "created_at": s.created_at.isoformat(),
                }
                for s in batch
            ]

            try:
                with self.get_session() as session:
                    result = session.run(query, segments=segments_data)
                    record = result.single()
                    count = record["created"] if record else 0
                    total_created += count
            except Exception as e:
                logger.error(f"Failed to create batch {i//batch_size + 1}: {e}")
                # Continue with the next batch rather than failing completely
                continue

        logger.info(
            f"Created {total_created} AudioSegment nodes in {(len(segments) + batch_size - 1) // batch_size} batches"
        )
        return total_created

    def get_video_transcripts(self, video_id: str) -> list[dict]:
        """Retrieve all transcript segments for a video."""
        query = """
        MATCH (v:Video)-[:HAS_TRANSCRIPT]->(a:AudioSegment)
        WHERE v.video_id = $video_id OR v.id = $video_id
        RETURN a.id as id, a.start_time as start_time, a.end_time as end_time,
               a.text as text, a.language as language, a.confidence as confidence
        ORDER BY a.start_time
        """
        return self._execute_query(query, {"video_id": video_id})

    def search_transcripts(
        self, query_text: str, video_id: str | None = None, limit: int = 20
    ) -> list[dict]:
        """
        Search audio transcripts for a given text.

        Args:
            query_text: Text to search for
            video_id: Filter to a specific video (optional)
            limit: Maximum number of results to return

        Returns:
            List of transcript segments that contain the text
        """
        if video_id:
            query = """
            MATCH (v:Video)-[:HAS_TRANSCRIPT]->(a:AudioSegment)
            WHERE (v.video_id = $video_id OR v.id = $video_id)
              AND toLower(a.text) CONTAINS toLower($query_text)
            RETURN a.id as id, a.video_id as video_id,
                   a.start_time as start_time, a.end_time as end_time,
                   a.text as text, a.language as language,
                   v.title as video_title
            ORDER BY a.start_time
            LIMIT $limit
            """
        else:
            query = """
            MATCH (v:Video)-[:HAS_TRANSCRIPT]->(a:AudioSegment)
            WHERE toLower(a.text) CONTAINS toLower($query_text)
            RETURN a.id as id, a.video_id as video_id,
                   a.start_time as start_time, a.end_time as end_time,
                   a.text as text, a.language as language,
                   v.title as video_title
            ORDER BY a.start_time
            LIMIT $limit
            """

        with self.get_session() as session:
            result = session.run(query, query_text=query_text, video_id=video_id, limit=limit)
            return [dict(record) for record in result]

    def delete_video_transcripts(self, video_id: str) -> int:
        """Delete all transcript segments for a video."""
        # Count first, then delete
        count_query = """
        MATCH (a:AudioSegment)
        WHERE a.video_id = $video_id
        RETURN count(a) as count
        """

        delete_query = """
        MATCH (a:AudioSegment)
        WHERE a.video_id = $video_id
        DETACH DELETE a
        """

        try:
            # Count before deleting
            result = self._execute_query(count_query, {"video_id": video_id}, single=True)
            count = result["count"] if result else 0

            if count > 0:
                # Delete in batches to avoid memory issues
                self._execute_query(delete_query, {"video_id": video_id})
                logger.info(f"Deleted {count} AudioSegment nodes for video {video_id}")

            return count
        except Exception as e:
            logger.error(f"Error deleting transcripts for video {video_id}: {e}")
            return 0

    # =========================================================================
    # Relation Operations
    # =========================================================================

    def create_relation(
        self,
        source_id: str,
        target_id: str,
        relation_type: RelationType,
        properties: dict | None = None,
    ) -> bool:
        """Create a relation between two nodes."""
        props = properties or {}
        props_string = ", ".join([f"{k}: ${k}" for k in props])

        query = f"""
        MATCH (a {{id: $source_id}})
        MATCH (b {{id: $target_id}})
        CREATE (a)-[r:{relation_type.value} {{{props_string}}}]->(b)
        RETURN type(r) as rel_type
        """

        params = {"source_id": source_id, "target_id": target_id, **props}

        with self.get_session() as session:
            result = session.run(query, **params)
            record = result.single()
            return record is not None

    def create_relations_batch(
        self,
        relations: list[dict],
    ) -> int:
        """
        Create multiple relations in batched UNWIND operations, grouped by type.

        Each dict in relations must have: source_id, target_id, relation_type (str),
        and optionally confidence (float) and evidence_count (int).

        Returns the total number of relations created.
        """
        from collections import defaultdict

        grouped: dict[str, list[dict]] = defaultdict(list)
        for rel in relations:
            grouped[rel["relation_type"]].append(rel)

        total_created = 0
        for rel_type, rels in grouped.items():
            batch_data = [
                {
                    "source_id": r["source_id"],
                    "target_id": r["target_id"],
                    "confidence": r.get("confidence", 0.0),
                    "evidence_count": r.get("evidence_count", 0),
                }
                for r in rels
            ]

            query = f"""
            UNWIND $batch AS rel
            MATCH (a {{id: rel.source_id}})
            MATCH (b {{id: rel.target_id}})
            CREATE (a)-[r:{rel_type} {{
                confidence: rel.confidence,
                evidence_count: rel.evidence_count
            }}]->(b)
            RETURN count(r) as created
            """

            try:
                with self.get_session() as session:
                    result = session.run(query, batch=batch_data)
                    record = result.single()
                    total_created += record["created"] if record else 0
            except Exception as e:
                logger.error(f"Batch relation creation failed for type {rel_type}: {e}")

        return total_created

    def create_temporal_relation(
        self,
        source_id: str,
        target_id: str,
        relation_type: RelationType,
        time_gap: float | None = None,
    ):
        """Create a temporal relation between two nodes."""
        query = f"""
        MATCH (a {{id: $source_id}})
        MATCH (b {{id: $target_id}})
        CREATE (a)-[r:{relation_type.value} {{time_gap_seconds: $time_gap}}]->(b)
        RETURN type(r)
        """

        with self.get_session() as session:
            session.run(query, source_id=source_id, target_id=target_id, time_gap=time_gap)

    def create_entity_cooccurrence(self, frame_id: str):
        """
        Create APPEARS_WITH relations between entities that appear in the same frame.
        """
        query = """
        MATCH (f:Frame {id: $frame_id})-[:CONTAINS]->(e1:Entity)
        MATCH (f)-[:CONTAINS]->(e2:Entity)
        WHERE e1.id < e2.id
        MERGE (e1)-[r:APPEARS_WITH]-(e2)
        ON CREATE SET r.count = 1, r.frames = [$frame_id]
        ON MATCH SET r.count = r.count + 1, r.frames = r.frames + $frame_id
        RETURN count(r) as relations_created
        """

        with self.get_session() as session:
            result = session.run(query, frame_id=frame_id)
            record = result.single()
            return record["relations_created"]

    # =========================================================================
    # Search Operations
    # =========================================================================

    def search_entities(
        self,
        query_text: str,
        entity_types: list[EntityType] | None = None,
        video_id: str | None = None,
        limit: int = 20,
    ) -> list[dict]:
        """Full-text search for entities."""
        type_filter = ""
        video_filter = ""

        if entity_types:
            types = [t.value for t in entity_types]
            type_filter = f"AND e.entity_type IN {types}"

        if video_id:
            video_filter = "MATCH (v:Video {video_id: $video_id})-[:CONTAINS*..3]->(e)"

        if video_filter:
            cypher = f"""
            {video_filter}
            WHERE e:Entity
            {type_filter}
            CALL db.index.fulltext.queryNodes('entity_search', $query) YIELD node, score
            WHERE node = e
            RETURN e, score
            ORDER BY score DESC
            LIMIT $limit
            """
        else:
            cypher = f"""
            CALL db.index.fulltext.queryNodes('entity_search', $query) YIELD node, score
            WHERE node:Entity {type_filter.replace('e.', 'node.')}
            RETURN node as e, score
            ORDER BY score DESC
            LIMIT $limit
            """

        with self.get_session() as session:
            result = session.run(cypher, query=query_text, video_id=video_id, limit=limit)
            return [{"entity": dict(r["e"]), "score": r["score"]} for r in result]

    def search_frames_by_description(
        self,
        query_text: str,
        video_id: str | None = None,
        time_range: tuple[float, float] | None = None,
        limit: int = 20,
    ) -> list[dict]:
        """Full-text search across frame descriptions."""
        filters = []
        params = {"query": query_text, "limit": limit}

        if video_id:
            filters.append("node.video_id = $video_id")
            params["video_id"] = video_id

        if time_range:
            # Use parameterized queries for time range to prevent injection
            filters.append("node.timestamp >= $time_start AND node.timestamp <= $time_end")
            params["time_start"] = time_range[0]
            params["time_end"] = time_range[1]

        where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""

        cypher = f"""
        CALL db.index.fulltext.queryNodes('frame_search', $query) YIELD node, score
        {where_clause}
        RETURN node as f, score
        ORDER BY score DESC
        LIMIT $limit
        """

        with self.get_session() as session:
            result = session.run(cypher, **params)
            return [{"frame": dict(r["f"]), "score": r["score"]} for r in result]

    # =========================================================================
    # Graph Expansion for RAG
    # =========================================================================

    def expand_context(
        self,
        node_id: str,
        hops: int = 2,
        relation_types: list[RelationType] | None = None,
        max_nodes: int = 50,
    ) -> dict:
        """
        Expand the context of a node for RAG.

        Returns related nodes up to N hops away.
        """
        rel_filter = ""
        if relation_types:
            rel_types = "|".join([r.value for r in relation_types])
            rel_filter = f"[:{rel_types}]"
        else:
            rel_filter = ""

        cypher = f"""
        MATCH (start {{id: $node_id}})
        CALL apoc.path.subgraphNodes(start, {{
            maxLevel: $hops,
            relationshipFilter: '{rel_filter}',
            limit: $max_nodes
        }}) YIELD node
        WHERE node <> start
        RETURN node,
               length(shortestPath((start)-[*]-(node))) as distance
        ORDER BY distance
        """

        with self.get_session() as session:
            result = session.run(cypher, node_id=node_id, hops=hops, max_nodes=max_nodes)

            nodes_by_distance = {0: []}  # Include start node at distance 0

            # Get start node data
            start_result = session.run("MATCH (n {id: $node_id}) RETURN n", node_id=node_id)
            start_record = start_result.single()
            if start_record:
                nodes_by_distance[0].append(dict(start_record["n"]))

            for record in result:
                distance = record["distance"]
                node_data = dict(record["node"])

                if distance not in nodes_by_distance:
                    nodes_by_distance[distance] = []
                nodes_by_distance[distance].append(node_data)

            return {
                "center_node_id": node_id,
                "hops": hops,
                "total_nodes": sum(len(v) for v in nodes_by_distance.values()),
                "nodes_by_distance": nodes_by_distance,
            }

    def get_entity_timeline(self, entity_name: str, video_id: str) -> list[dict]:
        """
        Retrieve the appearance timeline of an entity within a video.
        """
        cypher = """
        MATCH (v:Video {video_id: $video_id})-[:CONTAINS*..2]->(f:Frame)-[:CONTAINS]->(e:Entity)
        WHERE e.normalized_name = $entity_name
        RETURN f.timestamp as timestamp, f.id as frame_id, f.description as context
        ORDER BY f.timestamp
        """
        normalized = entity_name.lower().strip()
        results = self._execute_query(cypher, {"video_id": video_id, "entity_name": normalized})
        return [
            {"timestamp": r["timestamp"], "frame_id": r["frame_id"], "context": r["context"]}
            for r in results
        ]

    def get_related_entities(
        self,
        entity_id: str,
        relation_types: list[RelationType] | None = None,
        limit: int = 20,
    ) -> list[dict]:
        """Retrieve entities related to a given entity."""
        if relation_types:
            rel_types = "|".join([r.value for r in relation_types])
            rel_filter = f"[r:{rel_types}]"
        else:
            rel_filter = "[r]"

        cypher = f"""
        MATCH (e:Entity {{id: $entity_id}})-{rel_filter}-(related:Entity)
        RETURN related, type(r) as relation,
               CASE WHEN startNode(r) = e THEN 'outgoing' ELSE 'incoming' END as direction
        LIMIT $limit
        """
        results = self._execute_query(cypher, {"entity_id": entity_id, "limit": limit})
        return [
            {"entity": dict(r["related"]), "relation": r["relation"], "direction": r["direction"]}
            for r in results
        ]

    # =========================================================================
    # Cross-Video Queries
    # =========================================================================

    def find_common_entities(
        self,
        video_ids: list[str],
        entity_type: str | None = None,
        limit: int = 20,
    ) -> list[dict]:
        """Find entities that appear in multiple videos."""
        type_filter = ""
        if entity_type and entity_type != "any":
            type_filter = "AND e.entity_type = $entity_type"

        cypher = f"""
        MATCH (f:Frame)-[:CONTAINS]->(e:Entity)
        WHERE f.video_id IN $video_ids {type_filter}
        WITH e.name AS name, e.entity_type AS etype,
             collect(DISTINCT f.video_id) AS videos,
             count(DISTINCT f) AS total_appearances
        WHERE size(videos) >= 2
        RETURN name, etype, videos, total_appearances
        ORDER BY size(videos) DESC, total_appearances DESC
        LIMIT $limit
        """

        params: dict = {"video_ids": video_ids, "limit": limit}
        if entity_type and entity_type != "any":
            params["entity_type"] = entity_type

        with self.get_session() as session:
            result = session.run(cypher, **params)
            return [
                {
                    "name": r["name"],
                    "entity_type": r["etype"],
                    "shared_across": r["videos"],
                    "total_appearances": r["total_appearances"],
                }
                for r in result
            ]

    def get_video_topics(
        self,
        video_ids: list[str],
    ) -> list[dict]:
        """Get topics and summaries for multiple videos."""
        cypher = """
        MATCH (v:Video)
        WHERE v.video_id IN $video_ids
        RETURN v.video_id AS video_id,
               v.title AS title,
               v.summary AS summary,
               v.topics AS topics,
               v.duration AS duration
        """

        with self.get_session() as session:
            result = session.run(cypher, video_ids=video_ids)
            return [dict(r) for r in result]

    # =========================================================================
    # Statistics
    # =========================================================================

    def get_stats(self) -> GraphStats:
        """Retrieve statistics for the Knowledge Graph."""
        cypher = """
        CALL {
            MATCH (n) RETURN count(n) as total_nodes
        }
        CALL {
            MATCH ()-[r]->() RETURN count(r) as total_relations
        }
        CALL {
            MATCH (v:Video) RETURN count(v) as total_videos
        }
        CALL {
            MATCH (f:Frame) RETURN count(f) as total_frames
        }
        CALL {
            MATCH (e:Entity) RETURN count(e) as total_entities
        }
        RETURN total_nodes, total_relations, total_videos, total_frames, total_entities
        """

        nodes_by_type_cypher = """
        MATCH (n)
        RETURN labels(n)[0] as label, count(n) as count
        """

        relations_by_type_cypher = """
        MATCH ()-[r]->()
        RETURN type(r) as type, count(r) as count
        """

        with self.get_session() as session:
            # General statistics
            result = session.run(cypher)
            record = result.single()

            # Nodes by type
            nodes_result = session.run(nodes_by_type_cypher)
            nodes_by_type = {r["label"]: r["count"] for r in nodes_result}

            # Relations by type
            rels_result = session.run(relations_by_type_cypher)
            relations_by_type = {r["type"]: r["count"] for r in rels_result}

            total_nodes = record["total_nodes"]
            total_relations = record["total_relations"]

            return GraphStats(
                total_nodes=total_nodes,
                nodes_by_type=nodes_by_type,
                total_relations=total_relations,
                relations_by_type=relations_by_type,
                total_videos=record["total_videos"],
                total_frames_indexed=record["total_frames"],
                total_entities_extracted=record["total_entities"],
                avg_relations_per_node=total_relations / total_nodes if total_nodes > 0 else 0,
            )

    # =========================================================================
    # Multimodal Search (Visual + Audio)
    # =========================================================================

    def search_multimodal(
        self,
        query_text: str,
        video_id: str | None = None,
        include_visual: bool = True,
        include_audio: bool = True,
        limit: int = 20,
    ) -> dict:
        """
        Combined search across visual content (frames) and audio (transcripts).

        Args:
            query_text: Text to search for
            video_id: Filter to a specific video (optional)
            include_visual: Include results from visual frame descriptions
            include_audio: Include results from audio transcripts
            limit: Maximum number of results per content type

        Returns:
            Dict with combined visual and audio results
        """
        results = {
            "query": query_text,
            "visual_results": [],
            "audio_results": [],
            "combined_timeline": [],
        }

        video_filter = ""
        if video_id:
            video_filter = "AND (v.video_id = $video_id OR v.id = $video_id)"

        # Split query into keywords for better matching (used by both visual and audio)
        keywords = [w.strip() for w in query_text.split() if len(w.strip()) > 2]

        # Search visual frame descriptions
        if include_visual:
            if keywords:
                keyword_conditions = " OR ".join(
                    [f"toLower(f.description) CONTAINS toLower('{kw}')" for kw in keywords[:5]]
                )
                desc_filter = f"({keyword_conditions})"
            else:
                desc_filter = "toLower(f.description) CONTAINS toLower($query_text)"

            visual_query = f"""
            MATCH (v:Video)-[:CONTAINS*1..2]->(f:Frame)
            WHERE {desc_filter}
            {video_filter}
            RETURN f.id as id, f.video_id as video_id, f.timestamp as timestamp,
                   f.description as content, 'visual' as source_type,
                   v.title as video_title
            ORDER BY f.timestamp
            LIMIT $limit
            """

            with self.get_session() as session:
                result = session.run(
                    visual_query, query_text=query_text, video_id=video_id, limit=limit
                )
                results["visual_results"] = [dict(r) for r in result]

        # Search audio transcripts
        if include_audio:
            # Split query into keywords for better matching
            keywords = [w.strip() for w in query_text.split() if len(w.strip()) > 2]
            # Build OR conditions for each keyword
            if keywords:
                keyword_conditions = " OR ".join(
                    [f"toLower(a.text) CONTAINS toLower('{kw}')" for kw in keywords[:5]]
                )
                text_filter = f"({keyword_conditions})"
            else:
                text_filter = "toLower(a.text) CONTAINS toLower($query_text)"

            audio_query = f"""
            MATCH (v:Video)-[:HAS_TRANSCRIPT]->(a:AudioSegment)
            WHERE {text_filter}
            {video_filter}
            RETURN a.id as id, a.video_id as video_id, a.start_time as timestamp,
                   a.end_time as end_time, a.text as content, 'audio' as source_type,
                   v.title as video_title
            ORDER BY a.start_time
            LIMIT $limit
            """

            with self.get_session() as session:
                result = session.run(
                    audio_query, query_text=query_text, video_id=video_id, limit=limit
                )
                results["audio_results"] = [dict(r) for r in result]

        # Merge and sort by timestamp
        combined = []
        for r in results["visual_results"]:
            combined.append(
                {
                    "timestamp": r["timestamp"],
                    "type": "visual",
                    "content": r["content"],
                    "video_id": r["video_id"],
                    "video_title": r.get("video_title"),
                }
            )

        for r in results["audio_results"]:
            combined.append(
                {
                    "timestamp": r["timestamp"],
                    "end_time": r.get("end_time"),
                    "type": "audio",
                    "content": r["content"],
                    "video_id": r["video_id"],
                    "video_title": r.get("video_title"),
                }
            )

        results["combined_timeline"] = sorted(combined, key=lambda x: x["timestamp"])
        results["total_visual"] = len(results["visual_results"])
        results["total_audio"] = len(results["audio_results"])

        return results

    # =========================================================================
    # Cleanup Operations
    # =========================================================================

    def delete_video_graph(self, video_id: str) -> int:
        """Delete the entire subgraph for a video (scenes, frames, transcripts, entities)."""
        cypher = """
        MATCH (v:Video)
        WHERE v.video_id = $video_id OR v.id = $video_id
        OPTIONAL MATCH (v)-[*]->(n)
        DETACH DELETE v, n
        RETURN count(n) as deleted
        """
        result = self._execute_query(cypher, {"video_id": video_id}, single=True)
        count = result["deleted"] if result else 0
        logger.info(f"Deleted graph for video {video_id}: {count} nodes")
        return count

    # =========================================================================
    # Graph Visualization (NVL-compatible)
    # =========================================================================

    def get_video_subgraph(
        self,
        video_id: str,
        depth: int = 2,
        include_entities: bool = True,
        max_nodes: int = 200,
    ) -> dict:
        """
        Return a balanced subgraph for a video as nodes + relationships.

        Instead of letting a single label (e.g. Frame) flood the result,
        we collect each label separately and apply per-type quotas so the
        visualization always shows a representative mix of labels.

        Returns NVL-compatible structure:
        {
            "nodes": [{"id", "labels", "properties"}, ...],
            "relationships": [{"id", "start", "end", "type", "properties"}, ...],
        }

        Args:
            video_id: The video to visualize.
            depth: How many relationship hops to traverse (1-4).
            include_entities: Whether to include Entity nodes.
            max_nodes: Maximum total nodes to return.
        """
        # ── Step 1: collect per-label node samples ──────────────────────────
        # Quotas per label type (order matters for budget allocation).
        # The Video root always gets 1 slot; remaining budget is split among
        # the other types with a priority order that favours higher-level
        # structures (Chapters, Scenes) over dense leaves (Frames, Audio).
        label_configs = [
            ("Chapter", 0.15),  # 15 % of budget
            ("Scene", 0.25),  # 25 %
            ("AudioSegment", 0.20),  # 20 %
            ("Frame", 0.30),  # 30 %
        ]
        if include_entities:
            label_configs.append(("Entity", 0.10))  # 10 %

        budget = max_nodes - 1  # reserve 1 for the Video node itself

        # Collect the Video root node first
        cypher_video = """
        MATCH (v:Video)
        WHERE v.video_id = $video_id OR v.id = $video_id
        RETURN {
            id: coalesce(v.id, v.video_id, elementId(v)),
            labels: labels(v),
            properties: properties(v)
        } AS node
        """

        # For each label, collect connected nodes up to a per-type limit.
        # We use a depth-aware pattern: the relationship path differs per type.
        _label_cypher: dict[str, str] = {
            "Chapter": f"""
                MATCH (v:Video)-[:HAS_CHAPTER|CONTAINS*1..{depth}]->(n:Chapter)
                WHERE v.video_id = $video_id OR v.id = $video_id
                RETURN DISTINCT {{
                    id: coalesce(n.id, elementId(n)),
                    labels: labels(n),
                    properties: properties(n)
                }} AS node
                LIMIT $limit
            """,
            "Scene": f"""
                MATCH (v:Video)-[:HAS_SCENE|CONTAINS*1..{depth}]->(n:Scene)
                WHERE v.video_id = $video_id OR v.id = $video_id
                RETURN DISTINCT {{
                    id: coalesce(n.id, elementId(n)),
                    labels: labels(n),
                    properties: properties(n)
                }} AS node
                LIMIT $limit
            """,
            "Frame": f"""
                MATCH (v:Video)-[:HAS_FRAME|CONTAINS*1..{depth}]->(n:Frame)
                WHERE v.video_id = $video_id OR v.id = $video_id
                WITH n ORDER BY n.timestamp
                WITH collect(n) AS frames
                WITH frames, size(frames) AS total
                WITH frames,
                     CASE WHEN total <= $limit THEN 1
                          ELSE toInteger(ceil(toFloat(total) / $limit))
                     END AS step
                UNWIND range(0, size(frames) - 1, step) AS idx
                WITH frames[idx] AS n
                RETURN {{
                    id: coalesce(n.id, elementId(n)),
                    labels: labels(n),
                    properties: properties(n)
                }} AS node
                LIMIT $limit
            """,
            "AudioSegment": f"""
                MATCH (v:Video)-[:HAS_TRANSCRIPT|HAS_AUDIO|CONTAINS*1..{depth}]->(n:AudioSegment)
                WHERE v.video_id = $video_id OR v.id = $video_id
                WITH n ORDER BY n.start_time
                WITH collect(n) AS segs
                With segs, size(segs) AS total
                WITH segs,
                     CASE WHEN total <= $limit THEN 1
                          ELSE toInteger(ceil(toFloat(total) / $limit))
                     END AS step
                UNWIND range(0, size(segs) - 1, step) AS idx
                WITH segs[idx] AS n
                RETURN {{
                    id: coalesce(n.id, elementId(n)),
                    labels: labels(n),
                    properties: properties(n)
                }} AS node
                LIMIT $limit
            """,
            "Entity": f"""
                MATCH (v:Video)-[*1..{depth}]->(n:Entity)
                WHERE v.video_id = $video_id OR v.id = $video_id
                RETURN DISTINCT {{
                    id: coalesce(n.id, elementId(n)),
                    labels: labels(n),
                    properties: properties(n)
                }} AS node
                LIMIT $limit
            """,
        }

        all_nodes: list[dict] = []
        collected_ids: set[str] = set()

        with self.get_session() as session:
            # Video root
            rec = session.run(cypher_video, video_id=video_id).single()
            if not rec:
                return {"nodes": [], "relationships": []}
            video_node = dict(rec["node"])
            vid = video_node.get("id")
            all_nodes.append(video_node)
            if vid:
                collected_ids.add(str(vid))

            # Per-label queries
            for label, fraction in label_configs:
                limit = max(5, int(budget * fraction))
                cypher = _label_cypher.get(label)
                if not cypher:
                    continue
                result = session.run(
                    cypher,
                    video_id=video_id,
                    limit=limit,
                )
                for record in result:
                    node = dict(record["node"])
                    nid = str(node.get("id", ""))
                    if nid and nid not in collected_ids:
                        collected_ids.add(nid)
                        all_nodes.append(node)

            # ── Step 2: fetch relationships between collected nodes ─────────
            # Use the video as anchor and match direct relationships to
            # collected nodes, which is far more efficient than a full scan.
            node_ids = list(collected_ids)
            cypher_rels = """
            MATCH (a)-[r]->(b)
            WHERE (coalesce(a.id, a.video_id, elementId(a)) IN $node_ids)
              AND (coalesce(b.id, b.video_id, elementId(b)) IN $node_ids)
            RETURN DISTINCT
                elementId(r) AS rid,
                coalesce(a.id, a.video_id, elementId(a)) AS start_id,
                coalesce(b.id, b.video_id, elementId(b)) AS end_id,
                type(r) AS rel_type,
                properties(r) AS props
            """
            rel_result = session.run(cypher_rels, node_ids=node_ids)
            raw_rels = [
                {
                    "id": rec["rid"],
                    "start": rec["start_id"],
                    "end": rec["end_id"],
                    "type": rec["rel_type"],
                    "properties": rec["props"],
                }
                for rec in rel_result
            ]

        # ── Step 3: deduplicate & sanitize ──────────────────────────────────
        seen_node_ids: set[str] = set()
        nodes = []
        for n in all_nodes:
            nid = str(n.get("id", ""))
            if nid and nid not in seen_node_ids:
                seen_node_ids.add(nid)
                nodes.append(sanitize_for_json(n))

        seen_rel_keys: set[str] = set()
        relationships = []
        for r in raw_rels:
            key = f"{r.get('start')}-{r.get('type')}-{r.get('end')}"
            if key not in seen_rel_keys:
                seen_rel_keys.add(key)
                relationships.append(sanitize_for_json(r))

        return {"nodes": nodes, "relationships": relationships}

    def expand_node_subgraph(
        self,
        node_id: str,
        hops: int = 1,
        max_nodes: int = 50,
    ) -> dict:
        """
        Expand a single node's neighborhood, returning nodes + relationships.

        Used for progressive lazy-load expansion in the graph viewer.
        """
        cypher = """
        MATCH (start)
        WHERE start.id = $node_id OR start.video_id = $node_id
        CALL apoc.path.subgraphAll(start, {
            maxLevel: $hops,
            limit: $max_nodes
        }) YIELD nodes, relationships
        RETURN
            [n IN nodes | {
                id: coalesce(n.id, n.video_id, elementId(n)),
                labels: labels(n),
                properties: properties(n)
            }] AS nodes,
            [r IN relationships | {
                id: elementId(r),
                start: coalesce(startNode(r).id, startNode(r).video_id, elementId(startNode(r))),
                end: coalesce(endNode(r).id, endNode(r).video_id, elementId(endNode(r))),
                type: type(r),
                properties: properties(r)
            }] AS relationships
        """

        with self.get_session() as session:
            result = session.run(cypher, node_id=node_id, hops=hops, max_nodes=max_nodes)
            record = result.single()

            if not record:
                return {"nodes": [], "relationships": []}

            # Deduplicate
            seen_node_ids: set[str] = set()
            nodes = []
            for n in record["nodes"] or []:
                nid = n.get("id")
                if nid and nid not in seen_node_ids:
                    seen_node_ids.add(nid)
                    nodes.append(sanitize_for_json(dict(n)))

            seen_rel_keys: set[str] = set()
            relationships = []
            for r in record["relationships"] or []:
                key = f"{r.get('start')}-{r.get('type')}-{r.get('end')}"
                if key not in seen_rel_keys:
                    seen_rel_keys.add(key)
                    relationships.append(sanitize_for_json(dict(r)))

            return {"nodes": nodes, "relationships": relationships}

    def clear_all(self) -> None:
        """Delete all data from the graph. USE WITH CAUTION."""
        self._execute_query("MATCH (n) DETACH DELETE n")
        logger.warning("All graph data has been deleted")


# =============================================================================
# Singleton for global use
# =============================================================================

_knowledge_graph_service: KnowledgeGraphService | None = None


def get_knowledge_graph_service() -> KnowledgeGraphService:
    """Return the singleton instance of KnowledgeGraphService."""
    global _knowledge_graph_service
    if _knowledge_graph_service is None:
        _knowledge_graph_service = KnowledgeGraphService()
    return _knowledge_graph_service
