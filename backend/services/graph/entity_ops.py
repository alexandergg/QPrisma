"""
Entity and Topic node operations.

Covers creation, lookup, co-occurrence, cross-video resolution of Entity
nodes as well as Topic node batch creation and entity–topic linking.
"""

from __future__ import annotations

import logging

from models.graph_models import EntityNode, EntityType, TopicNode

logger = logging.getLogger(__name__)


class EntityOpsMixin:
    """Mixin providing Entity / Topic CRUD and cross-video resolution."""

    # =====================================================================
    # Entity Node Operations
    # =====================================================================

    def create_entity_node(self, entity: EntityNode, frame_id: str) -> str:
        """Create an Entity node and connect it to the Frame where it was detected."""
        query = """
        MATCH (f:Frame {id: $frame_id})
        MERGE (e:Entity {
            normalized_name: $normalized_name,
            entity_type: $entity_type,
            video_id: f.video_id
        })
        ON CREATE SET
            e.id = $id,
            e.name = $name,
            e.video_id = f.video_id,
            e.user_id = COALESCE($user_id, f.user_id),
            e.description = $description,
            e.description_list = CASE WHEN $description IS NOT NULL THEN [$description] ELSE [] END,
            e.attributes = $attributes,
            e.confidence = $confidence,
            e.occurrence_count = 1,
            e.first_seen_time = f.timestamp,
            e.last_seen_time = f.timestamp,
            e.created_at = datetime($created_at)
        ON MATCH SET
            e.occurrence_count = e.occurrence_count + 1,
            e.last_seen_time = f.timestamp,
            e.confidence = CASE WHEN $confidence > e.confidence THEN $confidence ELSE e.confidence END,
            e.description = CASE
                WHEN $description IS NOT NULL AND size($description) > size(coalesce(e.description, ''))
                THEN $description ELSE e.description END,
            e.description_list = CASE
                WHEN $description IS NOT NULL
                    AND NOT $description IN coalesce(e.description_list, [])
                    AND size(coalesce(e.description_list, [])) < 5
                THEN coalesce(e.description_list, []) + $description
                ELSE coalesce(e.description_list, []) END
        CREATE (f)-[:CONTAINS {confidence: $confidence, bounding_box: $bounding_box}]->(e)
        RETURN e.id as id
        """

        with self._get_session() as session:
            result = session.run(
                query,
                id=entity.id,
                frame_id=frame_id,
                name=entity.name,
                normalized_name=entity.normalized_name,
                entity_type=entity.entity_type.value,
                user_id=entity.user_id,
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
        MERGE (e:Entity {
            normalized_name: entity.normalized_name,
            entity_type: entity.entity_type,
            video_id: f.video_id
        })
        ON CREATE SET
            e.id = entity.id,
            e.name = entity.name,
            e.video_id = f.video_id,
            e.user_id = COALESCE(entity.user_id, f.user_id),
            e.description = entity.description,
            e.description_list = CASE WHEN entity.description IS NOT NULL THEN [entity.description] ELSE [] END,
            e.confidence = entity.confidence,
            e.occurrence_count = 1,
            e.first_seen_time = f.timestamp,
            e.created_at = datetime(entity.created_at)
        ON MATCH SET
            e.occurrence_count = e.occurrence_count + 1,
            e.last_seen_time = f.timestamp,
            e.description = CASE
                WHEN entity.description IS NOT NULL AND size(entity.description) > size(coalesce(e.description, ''))
                THEN entity.description ELSE e.description END,
            e.description_list = CASE
                WHEN entity.description IS NOT NULL
                    AND NOT entity.description IN coalesce(e.description_list, [])
                    AND size(coalesce(e.description_list, [])) < 5
                THEN coalesce(e.description_list, []) + entity.description
                ELSE coalesce(e.description_list, []) END
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
                "user_id": e.user_id,
                "description": e.description,
                "confidence": e.confidence,
                "created_at": e.created_at.isoformat(),
            }
            for e, frame_id in entities
        ]

        with self._get_session() as session:
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

    # =====================================================================
    # Entity Co-occurrence & Cross-video Resolution
    # =====================================================================

    def create_entity_cooccurrence(self, frame_id: str) -> int:
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

        with self._get_session() as session:
            result = session.run(query, frame_id=frame_id)
            record = result.single()
            return record["relations_created"]

    def resolve_cross_video_entities(self, video_id: str) -> int:
        """Find and link entities that likely represent the same real-world entity
        across different videos using name similarity.

        Creates SAME_ENTITY edges between entity pairs from different videos
        that share the same entity_type and have matching or overlapping
        normalized_names. Uses conservative matching to avoid false positives.

        Only compares entities from the given video_id against entities from
        other videos, so this is called once per newly processed video.
        """
        query = """
        MATCH (e1:Entity {video_id: $video_id})
        WHERE e1.user_id IS NOT NULL
        MATCH (e2:Entity)
        WHERE e2.video_id <> $video_id
          AND e2.user_id = e1.user_id
          AND e1.entity_type = e2.entity_type
          AND e1.id <> e2.id
          AND (
            e1.normalized_name = e2.normalized_name
            OR (size(e1.normalized_name) > 3 AND size(e2.normalized_name) > 3
                AND (e1.normalized_name CONTAINS e2.normalized_name
                     OR e2.normalized_name CONTAINS e1.normalized_name))
          )
        WITH e1, e2,
             CASE
               WHEN e1.normalized_name = e2.normalized_name THEN 1.0
               ELSE 0.7
             END AS similarity
        MERGE (e1)-[r:SAME_ENTITY]-(e2)
        ON CREATE SET
            r.similarity_score = similarity,
            r.source_video_id = e1.video_id,
            r.target_video_id = e2.video_id,
            r.created_at = datetime()
        ON MATCH SET
            r.similarity_score = CASE
                WHEN similarity > r.similarity_score
                THEN similarity ELSE r.similarity_score END
        RETURN count(r) as linked
        """

        with self._get_session() as session:
            result = session.run(query, video_id=video_id)
            record = result.single()
            count = record["linked"] if record else 0
            if count > 0:
                logger.info(f"Resolved {count} cross-video entity matches for video {video_id}")
            return count

    # =====================================================================
    # Topic Node Operations
    # =====================================================================

    def create_topic_nodes_batch(self, topics: list[TopicNode], video_id: str) -> int:
        """Create Topic nodes and link them to the Video.

        Uses MERGE on ``(video_id, normalized_name)`` so topics are unique per-video.
        Links each topic to the Video via an ABOUT relationship.
        """
        if not topics:
            return 0

        topics_data = [
            {
                "id": t.id,
                "name": t.name,
                "normalized_name": t.normalized_name,
                "description": t.description,
                "keywords": t.keywords,
                "relevance_score": t.relevance_score,
                "user_id": t.user_id,
                "created_at": t.created_at.isoformat(),
            }
            for t in topics
        ]

        query = """
        MATCH (v:Video {video_id: $video_id})
        UNWIND $topics AS topic
        MERGE (t:Topic {normalized_name: topic.normalized_name, video_id: $video_id})
        ON CREATE SET
            t.id = topic.id,
            t.name = topic.name,
            t.description = topic.description,
            t.keywords = topic.keywords,
            t.relevance_score = topic.relevance_score,
            t.user_id = COALESCE(topic.user_id, v.user_id),
            t.created_at = datetime(topic.created_at)
        ON MATCH SET
            t.relevance_score = CASE
                WHEN topic.relevance_score > t.relevance_score
                THEN topic.relevance_score ELSE t.relevance_score END
        WITH v, t
        MERGE (v)-[:ABOUT]->(t)
        RETURN count(t) as created
        """

        with self._get_session() as session:
            result = session.run(query, topics=topics_data, video_id=video_id)
            record = result.single()
            count = record["created"] if record else 0
            logger.info(f"Created {count} Topic nodes for video {video_id}")
            return count

    def link_entities_to_topics(self, video_id: str) -> int:
        """Link entities to topics based on matching keywords and names.

        Creates ABOUT edges from Entity → Topic when the entity name or
        description matches topic keywords or name.
        """
        query = """
        MATCH (v:Video {video_id: $video_id})-[:ABOUT]->(t:Topic)
        MATCH (e:Entity)
        WHERE e.video_id = $video_id
          AND (
            e.normalized_name CONTAINS t.normalized_name
            OR t.normalized_name CONTAINS e.normalized_name
            OR ANY(kw IN coalesce(t.keywords, []) WHERE e.normalized_name CONTAINS toLower(kw))
          )
        MERGE (e)-[:ABOUT]->(t)
        RETURN count(*) as linked
        """

        with self._get_session() as session:
            result = session.run(query, video_id=video_id)
            record = result.single()
            count = record["linked"] if record else 0
            logger.info(f"Linked {count} entity-topic pairs for video {video_id}")
            return count
