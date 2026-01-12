"""
Knowledge Graph Service for QPrisma

Servicio principal para gestionar el Knowledge Graph multimodal en Neo4j.
Proporciona operaciones CRUD, búsqueda híbrida y graph expansion para RAG.

Requiere Neo4j 5.x con plugin APOC.
"""

import logging
import os
from contextlib import contextmanager

from neo4j import Driver, GraphDatabase, Session
from neo4j.exceptions import AuthError, ServiceUnavailable

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
    Servicio para gestionar el Knowledge Graph de QPrisma en Neo4j.

    Características:
    - Conexión con pool de conexiones
    - CRUD de nodos jerárquicos (Video → Scene → Frame → Entity)
    - Relaciones temporales y semánticas
    - Búsqueda híbrida (vector + graph traversal)
    - Graph expansion para contexto RAG
    """

    def __init__(
        self,
        uri: str | None = None,
        user: str | None = None,
        password: str | None = None,
        database: str = "neo4j",
    ):
        """
        Inicializa la conexión a Neo4j.

        Args:
            uri: URI de conexión (default: bolt://localhost:7687)
            user: Usuario (default: neo4j)
            password: Contraseña (default: qprisma123)
            database: Base de datos a usar
        """
        self.uri = uri or os.getenv("NEO4J_URI", "bolt://localhost:7687")
        self.user = user or os.getenv("NEO4J_USER", "neo4j")
        self.password = password or os.getenv("NEO4J_PASSWORD", "qprisma123")
        self.database = database or os.getenv("NEO4J_DATABASE", "neo4j")

        self._driver: Driver | None = None
        self._connected = False
        self._schema_initialized = False

    # =========================================================================
    # Connection Management
    # =========================================================================

    def connect(self) -> bool:
        """Establece conexión con Neo4j."""
        try:
            self._driver = GraphDatabase.driver(
                self.uri,
                auth=(self.user, self.password),
                max_connection_lifetime=3600,
                max_connection_pool_size=50,
                connection_acquisition_timeout=60,
            )
            # Verificar conexión
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

    def disconnect(self):
        """Cierra la conexión con Neo4j."""
        if self._driver:
            self._driver.close()
            self._driver = None
            self._connected = False
            self._schema_initialized = False
            logger.info("Disconnected from Neo4j")

    @property
    def is_connected(self) -> bool:
        """Verifica si hay conexión activa."""
        return self._connected and self._driver is not None

    @contextmanager
    def get_session(self) -> Session:
        """Context manager para obtener una sesión de Neo4j."""
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
    # Schema & Indexes
    # =========================================================================

    def initialize_schema(self):
        """Crea índices y constraints necesarios en Neo4j."""
        with self.get_session() as session:
            # Constraints de unicidad
            constraints = [
                "CREATE CONSTRAINT video_id IF NOT EXISTS FOR (v:Video) REQUIRE v.id IS UNIQUE",
                "CREATE CONSTRAINT chapter_id IF NOT EXISTS FOR (c:Chapter) REQUIRE c.id IS UNIQUE",
                "CREATE CONSTRAINT scene_id IF NOT EXISTS FOR (s:Scene) REQUIRE s.id IS UNIQUE",
                "CREATE CONSTRAINT frame_id IF NOT EXISTS FOR (f:Frame) REQUIRE f.id IS UNIQUE",
                "CREATE CONSTRAINT entity_id IF NOT EXISTS FOR (e:Entity) REQUIRE e.id IS UNIQUE",
                "CREATE CONSTRAINT topic_id IF NOT EXISTS FOR (t:Topic) REQUIRE t.id IS UNIQUE",
                "CREATE CONSTRAINT audio_id IF NOT EXISTS FOR (a:AudioSegment) REQUIRE a.id IS UNIQUE",
            ]

            # Índices para búsqueda
            indexes = [
                # Índices por video_id para filtrado rápido
                "CREATE INDEX video_video_id IF NOT EXISTS FOR (v:Video) ON (v.video_id)",
                "CREATE INDEX scene_video_id IF NOT EXISTS FOR (s:Scene) ON (s.video_id)",
                "CREATE INDEX frame_video_id IF NOT EXISTS FOR (f:Frame) ON (f.video_id)",
                "CREATE INDEX entity_video_id IF NOT EXISTS FOR (e:Entity) ON (e.video_id)",
                # Índices por timestamp para queries temporales
                "CREATE INDEX frame_timestamp IF NOT EXISTS FOR (f:Frame) ON (f.timestamp)",
                "CREATE INDEX scene_start_time IF NOT EXISTS FOR (s:Scene) ON (s.start_time)",
                # Índices por tipo de entidad
                "CREATE INDEX entity_type IF NOT EXISTS FOR (e:Entity) ON (e.entity_type)",
                "CREATE INDEX entity_name IF NOT EXISTS FOR (e:Entity) ON (e.normalized_name)",
                # Índice full-text para búsqueda de texto
                "CREATE FULLTEXT INDEX entity_search IF NOT EXISTS FOR (e:Entity) ON EACH [e.name, e.description]",
                "CREATE FULLTEXT INDEX frame_search IF NOT EXISTS FOR (f:Frame) ON EACH [f.description]",
                "CREATE FULLTEXT INDEX topic_search IF NOT EXISTS FOR (t:Topic) ON EACH [t.name, t.description]",
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
        """Crea un nodo Video en el grafo."""
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
        """Obtiene un nodo Video por su video_id (o id legacy)."""
        query = """
        MATCH (v:Video)
        WHERE v.video_id = $video_id OR v.id = $video_id
        RETURN v
        """
        return self._execute_query(query, {"video_id": video_id}, single=True, unpack_key="v")

    def update_video_summary(self, video_id: str, summary: str, topics: list[str]):
        """Actualiza el resumen y topics de un video."""
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
        """Crea un nodo Scene y lo conecta al Video."""
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
        """Obtiene todas las escenas de un video ordenadas por tiempo."""
        query = """
        MATCH (v:Video)-[:CONTAINS]->(s:Scene)
        WHERE v.video_id = $video_id OR v.id = $video_id
        RETURN s
        ORDER BY s.start_time
        """
        return self._execute_query(query, {"video_id": video_id}, unpack_key="s")

    def get_scene_frames(self, scene_id: str) -> list[dict]:
        """Obtiene todos los frames de una escena ordenados por timestamp."""
        query = """
        MATCH (s:Scene {id: $scene_id})-[:CONTAINS]->(f:Frame)
        RETURN f.id as id, f.timestamp as timestamp, f.description as description
        ORDER BY f.timestamp
        """
        return self._execute_query(query, {"scene_id": scene_id})

    def get_video_frames(self, video_id: str) -> list[dict]:
        """Obtiene todos los frames de un video con sus descripciones."""
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
        """Crea un nodo Frame y lo conecta a su Scene (si existe) o Video."""
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
        """Crea múltiples frames en batch para mejor rendimiento."""
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
        """Crea un nodo Entity y lo conecta al Frame donde fue detectado."""
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
                attributes=str(entity.attributes),  # Neo4j no soporta maps anidados directamente
                confidence=entity.confidence,
                bounding_box=str(entity.bounding_box) if entity.bounding_box else None,
                created_at=entity.created_at.isoformat(),
            )
            record = result.single()
            return record["id"]

    def create_entities_batch(self, entities: list[tuple[EntityNode, str]]) -> int:
        """
        Crea múltiples entidades en batch.

        Args:
            entities: Lista de tuplas (EntityNode, frame_id)
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
        """Busca una entidad por nombre normalizado."""
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
        """Crea un nodo AudioSegment (transcripción) y lo conecta al Video."""
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

    def create_audio_segments_batch(self, segments: list[AudioSegmentNode]) -> int:
        """Crea múltiples segmentos de audio en batch."""
        if not segments:
            return 0

        query = """
        UNWIND $segments as seg
        MATCH (v:Video)
        WHERE v.video_id = seg.video_id OR v.id = seg.video_id
        CREATE (a:AudioSegment {
            id: seg.id,
            video_id: seg.video_id,
            start_time: seg.start_time,
            end_time: seg.end_time,
            text: seg.text,
            language: seg.language,
            confidence: seg.confidence,
            created_at: datetime(seg.created_at)
        })
        CREATE (v)-[:HAS_TRANSCRIPT]->(a)
        RETURN count(a) as created
        """

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
            for s in segments
        ]

        with self.get_session() as session:
            result = session.run(query, segments=segments_data)
            record = result.single()
            count = record["created"] if record else 0
            logger.info(f"Created {count} AudioSegment nodes in batch")
            return count

    def get_video_transcripts(self, video_id: str) -> list[dict]:
        """Obtiene todos los segmentos de transcripción de un video."""
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
        Busca en las transcripciones de audio.

        Args:
            query_text: Texto a buscar
            video_id: Filtrar por video específico (opcional)
            limit: Número máximo de resultados

        Returns:
            Lista de segmentos que contienen el texto
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
        """Elimina todos los segmentos de transcripción de un video."""
        query = """
        MATCH (v:Video)-[:HAS_TRANSCRIPT]->(a:AudioSegment)
        WHERE v.video_id = $video_id OR v.id = $video_id
        DETACH DELETE a
        RETURN count(a) as deleted
        """
        result = self._execute_query(query, {"video_id": video_id}, single=True)
        count = result["deleted"] if result else 0
        logger.info(f"Deleted {count} AudioSegment nodes for video {video_id}")
        return count

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
        """Crea una relación entre dos nodos."""
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

    def create_temporal_relation(
        self,
        source_id: str,
        target_id: str,
        relation_type: RelationType,
        time_gap: float | None = None,
    ):
        """Crea una relación temporal entre nodos."""
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
        Crea relaciones APPEARS_WITH entre entidades que aparecen en el mismo frame.
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
        """Búsqueda full-text de entidades."""
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
        """Búsqueda full-text en descripciones de frames."""
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
        Expande el contexto de un nodo para RAG.

        Devuelve nodos relacionados hasta N hops de distancia.
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
        Obtiene la línea temporal de apariciones de una entidad en un video.
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
        """Obtiene entidades relacionadas a una entidad dada."""
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
    # Statistics
    # =========================================================================

    def get_stats(self) -> GraphStats:
        """Obtiene estadísticas del Knowledge Graph."""
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
            # Estadísticas generales
            result = session.run(cypher)
            record = result.single()

            # Nodos por tipo
            nodes_result = session.run(nodes_by_type_cypher)
            nodes_by_type = {r["label"]: r["count"] for r in nodes_result}

            # Relaciones por tipo
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
        Búsqueda combinada en contenido visual (frames) y audio (transcripciones).

        Args:
            query_text: Texto a buscar
            video_id: Filtrar por video específico (opcional)
            include_visual: Incluir resultados de descripción visual
            include_audio: Incluir resultados de transcripción
            limit: Número máximo de resultados por tipo

        Returns:
            Dict con resultados visuales y de audio combinados
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

        # Buscar en descripciones visuales (frames)
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

        # Buscar en transcripciones
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

        # Combinar y ordenar por timestamp
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
        """Elimina todo el subgrafo asociado a un video (scenes, frames, transcripts, entities)."""
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

    def clear_all(self):
        """Elimina todos los datos del grafo. USAR CON PRECAUCIÓN."""
        self._execute_query("MATCH (n) DETACH DELETE n")
        logger.warning("All graph data has been deleted")


# =============================================================================
# Singleton para uso global
# =============================================================================

_knowledge_graph_service: KnowledgeGraphService | None = None


def get_knowledge_graph_service() -> KnowledgeGraphService:
    """Obtiene la instancia singleton del KnowledgeGraphService."""
    global _knowledge_graph_service
    if _knowledge_graph_service is None:
        _knowledge_graph_service = KnowledgeGraphService()
    return _knowledge_graph_service
