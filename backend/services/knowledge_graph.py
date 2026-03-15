"""
Knowledge Graph Service for QPrisma

Primary service for managing the multimodal Knowledge Graph in Neo4j.
Provides CRUD operations, hybrid search, and graph expansion for RAG.

Requires Neo4j 5.x with the APOC plugin.

Internally delegates to:
- ``GraphNodeRepository``  – CRUD for nodes and relations
- ``GraphExpander``         – graph expansion, analytics, statistics, cleanup
"""

import logging
from contextlib import asynccontextmanager, contextmanager

from neo4j import AsyncDriver, AsyncGraphDatabase, AsyncSession, Driver, GraphDatabase, Session
from neo4j.exceptions import AuthError, ServiceUnavailable

from core.config import settings
from models.graph_models import (
    AudioSegmentNode,
    CommunityNode,
    EntityNode,
    EntityType,
    FrameNode,
    GraphStats,
    RelationType,
    SceneNode,
    VideoNode,
)
from services.graph_expander import GraphExpander
from services.graph_node_repository import GraphNodeRepository

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

    Internally composes ``GraphNodeRepository`` and ``GraphExpander`` while
    preserving the full public API via thin delegation methods.
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

        # Composed services – wired to own _execute_query / get_session so
        # they share connection management without owning it.
        self.nodes: GraphNodeRepository = GraphNodeRepository(self._execute_query, self.get_session)
        self.expander: GraphExpander = GraphExpander(self._execute_query, self.get_session)

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

    # Expected fulltext index definitions.  When the field list changes the
    # stale index is dropped so ``IF NOT EXISTS`` will re-create it with the
    # correct columns on the next run.
    _FULLTEXT_INDEX_DEFS: dict[str, list[str]] = {
        "entity_search": ["name", "description"],
        "frame_search": ["description"],
        "topic_search": ["name", "description"],
        "audio_search": ["text"],
        "community_search": ["title", "summary", "themes_text"],
    }

    def _migrate_fulltext_indexes(self, session: Session) -> None:
        """Drop fulltext indexes whose property list no longer matches."""
        result = session.run(
            "SHOW FULLTEXT INDEXES YIELD name, properties " "RETURN name, properties"
        )
        existing: dict[str, set[str]] = {rec["name"]: set(rec["properties"]) for rec in result}

        for idx_name, expected_props in self._FULLTEXT_INDEX_DEFS.items():
            if idx_name in existing and existing[idx_name] != set(expected_props):
                logger.info(
                    "Fulltext index %s has stale properties %s (expected %s) — dropping",
                    idx_name,
                    sorted(existing[idx_name]),
                    expected_props,
                )
                session.run(f"DROP INDEX {idx_name}")

    @staticmethod
    def _migrate_property_renames(session: Session) -> None:
        """Rename legacy properties on existing nodes for schema consistency."""
        migrations = [
            # VideoNode: ai_summary → summary
            (
                "MATCH (v:Video) WHERE v.ai_summary IS NOT NULL AND v.summary IS NULL "
                "SET v.summary = v.ai_summary REMOVE v.ai_summary "
                "RETURN count(v) AS migrated",
                "Video.ai_summary → summary",
            ),
        ]
        for query, label in migrations:
            result = session.run(query)
            record = result.single()
            count = record["migrated"] if record else 0
            if count:
                logger.info("Property migration '%s': %d node(s) updated", label, count)

    def initialize_schema(self) -> None:
        """Create required indexes and constraints in Neo4j."""
        with self.get_session() as session:
            # Migrate stale fulltext indexes before creating new ones
            try:
                self._migrate_fulltext_indexes(session)
            except Exception as e:
                logger.warning(f"Fulltext index migration check failed: {e}")

            # Migrate renamed properties on existing nodes
            try:
                self._migrate_property_renames(session)
            except Exception as e:
                logger.warning(f"Property rename migration failed: {e}")

            # Uniqueness constraints
            constraints = [
                "CREATE CONSTRAINT video_id IF NOT EXISTS FOR (v:Video) REQUIRE v.id IS UNIQUE",
                "CREATE CONSTRAINT chapter_id IF NOT EXISTS FOR (c:Chapter) REQUIRE c.id IS UNIQUE",
                "CREATE CONSTRAINT scene_id IF NOT EXISTS FOR (s:Scene) REQUIRE s.id IS UNIQUE",
                "CREATE CONSTRAINT frame_id IF NOT EXISTS FOR (f:Frame) REQUIRE f.id IS UNIQUE",
                "CREATE CONSTRAINT entity_id IF NOT EXISTS FOR (e:Entity) REQUIRE e.id IS UNIQUE",
                "CREATE CONSTRAINT topic_id IF NOT EXISTS FOR (t:Topic) REQUIRE t.id IS UNIQUE",
                "CREATE CONSTRAINT audio_id IF NOT EXISTS FOR (a:AudioSegment) REQUIRE a.id IS UNIQUE",
                "CREATE CONSTRAINT community_id IF NOT EXISTS FOR (c:Community) REQUIRE c.id IS UNIQUE",
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
                # Community indexes
                "CREATE INDEX community_video_id IF NOT EXISTS FOR (c:Community) ON (c.video_id)",
                "CREATE INDEX community_community_id IF NOT EXISTS FOR (c:Community) ON (c.community_id)",
                "CREATE FULLTEXT INDEX community_search IF NOT EXISTS FOR (c:Community) ON EACH [c.title, c.summary, c.themes_text]",
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
    # Delegation — GraphNodeRepository  (backward-compatible public API)
    # =========================================================================

    def create_video_node(self, video: VideoNode) -> str:
        """Create a Video node in the graph."""
        return self.nodes.create_video_node(video)

    def get_video_node(self, video_id: str) -> dict | None:
        """Retrieve a Video node by its video_id (or legacy id)."""
        return self.nodes.get_video_node(video_id)

    def get_video_summary(self, video_id: str) -> tuple[str | None, list[str]]:
        """Get video summary and topics from the knowledge graph."""
        return self.nodes.get_video_summary(video_id)

    def update_video_summary(self, video_id: str, summary: str, topics: list[str]):
        """Update the AI summary and topics for a video."""
        return self.nodes.update_video_summary(video_id, summary, topics)

    def create_scene_node(self, scene: SceneNode) -> str:
        """Create a Scene node and connect it to its Video."""
        return self.nodes.create_scene_node(scene)

    def get_video_scenes(self, video_id: str) -> list[dict]:
        """Retrieve all scenes for a video, ordered by start time."""
        return self.nodes.get_video_scenes(video_id)

    def get_scene_frames(self, scene_id: str) -> list[dict]:
        """Retrieve all frames for a scene, ordered by timestamp."""
        return self.nodes.get_scene_frames(scene_id)

    def get_video_frames(self, video_id: str) -> list[dict]:
        """Retrieve all frames for a video together with their descriptions."""
        return self.nodes.get_video_frames(video_id)

    def create_frame_node(self, frame: FrameNode) -> str:
        """Create a Frame node and connect it to its Scene (if present) or Video."""
        return self.nodes.create_frame_node(frame)

    def create_frames_batch(self, frames: list[FrameNode]) -> int:
        """Create multiple Frame nodes in a single batch for better performance."""
        return self.nodes.create_frames_batch(frames)

    def create_entity_node(self, entity: EntityNode, frame_id: str) -> str:
        """Create an Entity node and connect it to the Frame where it was detected."""
        return self.nodes.create_entity_node(entity, frame_id)

    def create_entities_batch(self, entities: list[tuple[EntityNode, str]]) -> int:
        """Create multiple Entity nodes in a single batch."""
        return self.nodes.create_entities_batch(entities)

    def get_entity_by_name(self, name: str, entity_type: EntityType | None = None) -> dict | None:
        """Look up an entity by its normalized name."""
        return self.nodes.get_entity_by_name(name, entity_type)

    def create_audio_segment(self, segment: AudioSegmentNode) -> str:
        """Create an AudioSegment (transcript) node and connect it to its Video."""
        return self.nodes.create_audio_segment(segment)

    def create_audio_segments_batch(
        self, segments: list[AudioSegmentNode], batch_size: int = 100
    ) -> int:
        """Create multiple AudioSegment nodes in batches."""
        return self.nodes.create_audio_segments_batch(segments, batch_size)

    def get_video_transcripts(self, video_id: str) -> list[dict]:
        """Retrieve all transcript segments for a video."""
        return self.nodes.get_video_transcripts(video_id)

    def search_transcripts(
        self, query_text: str, video_id: str | None = None, limit: int = 20
    ) -> list[dict]:
        """Search audio transcripts for a given text."""
        return self.nodes.search_transcripts(query_text, video_id, limit)

    def delete_video_transcripts(self, video_id: str) -> int:
        """Delete all transcript segments for a video."""
        return self.nodes.delete_video_transcripts(video_id)

    def create_relation(
        self,
        source_id: str,
        target_id: str,
        relation_type: RelationType,
        properties: dict | None = None,
    ) -> bool:
        """Create a relation between two nodes."""
        return self.nodes.create_relation(source_id, target_id, relation_type, properties)

    def create_relations_batch(self, relations: list[dict]) -> int:
        """Create multiple relations in batched UNWIND operations, grouped by type."""
        return self.nodes.create_relations_batch(relations)

    def create_temporal_relation(
        self,
        source_id: str,
        target_id: str,
        relation_type: RelationType,
        time_gap: float | None = None,
    ):
        """Create a temporal relation between two nodes."""
        return self.nodes.create_temporal_relation(source_id, target_id, relation_type, time_gap)

    def create_entity_cooccurrence(self, frame_id: str):
        """Create APPEARS_WITH relations between entities in the same frame."""
        return self.nodes.create_entity_cooccurrence(frame_id)

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
    # Delegation — GraphExpander  (backward-compatible public API)
    # =========================================================================

    def expand_context(
        self,
        node_id: str,
        hops: int = 2,
        relation_types: list[RelationType] | None = None,
        max_nodes: int = 50,
    ) -> dict:
        """Expand the context of a node for RAG."""
        return self.expander.expand_context(node_id, hops, relation_types, max_nodes)

    def get_entity_timeline(self, entity_name: str, video_id: str) -> list[dict]:
        """Retrieve the appearance timeline of an entity within a video."""
        return self.expander.get_entity_timeline(entity_name, video_id)

    def get_related_entities(
        self,
        entity_id: str,
        relation_types: list[RelationType] | None = None,
        limit: int = 20,
    ) -> list[dict]:
        """Retrieve entities related to a given entity."""
        return self.expander.get_related_entities(entity_id, relation_types, limit)

    def find_common_entities(
        self,
        video_ids: list[str],
        entity_type: str | None = None,
        limit: int = 20,
    ) -> list[dict]:
        """Find entities that appear in multiple videos."""
        return self.expander.find_common_entities(video_ids, entity_type, limit)

    def get_video_topics(self, video_ids: list[str]) -> list[dict]:
        """Get topics and summaries for multiple videos."""
        return self.expander.get_video_topics(video_ids)

    def get_stats(self) -> GraphStats:
        """Retrieve statistics for the Knowledge Graph."""
        return self.expander.get_stats()

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

    def get_video_subgraph(
        self,
        video_id: str,
        depth: int = 2,
        include_entities: bool = True,
        max_nodes: int = 200,
    ) -> dict:
        """Return a balanced subgraph for a video as nodes + relationships."""
        return self.expander.get_video_subgraph(video_id, depth, include_entities, max_nodes)

    def expand_node_subgraph(
        self,
        node_id: str,
        hops: int = 1,
        max_nodes: int = 50,
    ) -> dict:
        """Expand a single node's neighborhood, returning nodes + relationships."""
        return self.expander.expand_node_subgraph(node_id, hops, max_nodes)

    def delete_video_graph(self, video_id: str) -> int:
        """Delete the entire subgraph for a video."""
        return self.expander.delete_video_graph(video_id)

    # =========================================================================
    # Delegation — Community operations
    # =========================================================================

    def create_community_node(self, community: CommunityNode) -> str:
        """Create a Community node and link it to its Video."""
        return self.nodes.create_community_node(community)

    def create_communities_batch(self, communities: list[CommunityNode]) -> int:
        """Create multiple Community nodes in a single batch."""
        return self.nodes.create_communities_batch(communities)

    def link_entities_to_community(self, community_id: str, entity_ids: list[str]) -> int:
        """Create IN_COMMUNITY relationships from entities to a community."""
        return self.nodes.link_entities_to_community(community_id, entity_ids)

    def get_video_communities(self, video_id: str) -> list[dict]:
        """Retrieve all communities for a video."""
        return self.nodes.get_video_communities(video_id)

    def get_community_members(self, community_id: str) -> list[dict]:
        """Retrieve all entities belonging to a community."""
        return self.nodes.get_community_members(community_id)

    def delete_video_communities(self, video_id: str) -> int:
        """Delete all Community nodes for a video."""
        return self.nodes.delete_video_communities(video_id)

    def get_community_context(self, video_id: str, topic: str | None = None) -> list[dict]:
        """Retrieve community summaries for a video, optionally filtered by topic."""
        return self.expander.get_community_context(video_id, topic)

    # ----- Dense Temporal Chain delegation -----

    def create_frame_chain(self, video_id: str) -> int:
        """Create NEXT_FRAME linked-list edges between consecutive frames."""
        return self.nodes.create_frame_chain(video_id)

    def create_segment_chain(self, video_id: str) -> int:
        """Create NEXT_SEGMENT linked-list edges between consecutive audio segments."""
        return self.nodes.create_segment_chain(video_id)

    def create_scene_chain(self, video_id: str) -> int:
        """Create NEXT_SCENE linked-list edges between consecutive scenes."""
        return self.nodes.create_scene_chain(video_id)

    def create_temporal_chains(self, video_id: str) -> dict[str, int]:
        """Create all dense temporal chains (frames, segments, scenes) for a video."""
        return {
            "frame_chains": self.create_frame_chain(video_id),
            "segment_chains": self.create_segment_chain(video_id),
            "scene_chains": self.create_scene_chain(video_id),
        }

    def walk_temporal_chain(
        self,
        node_id: str,
        chain_type: str = "NEXT_FRAME",
        direction: str = "forward",
        hops: int = 10,
    ) -> list[dict]:
        """Walk a temporal chain from a node. Delegates to GraphExpander."""
        return self.expander.walk_temporal_chain(node_id, chain_type, direction, hops)

    def clear_all(self) -> None:
        """Delete all data from the graph. USE WITH CAUTION."""
        return self.expander.clear_all()


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
