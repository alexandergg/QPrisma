"""
Relation operations.

Covers creation (single, batch, temporal) of typed relationships between
graph nodes as well as batch semantic-relation creation for LLM-extracted
entity links.
"""

from __future__ import annotations

import logging
import re
from collections import defaultdict

from models.graph_models import RelationType

logger = logging.getLogger(__name__)

# Valid Neo4j relationship type: starts with uppercase letter, then uppercase
# letters, digits, or underscores.  Used to guard against Cypher injection when
# relationship types are interpolated into queries.
_VALID_REL_TYPE_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")


class RelationOpsMixin:
    """Mixin providing relation CRUD helpers."""

    # =====================================================================
    # Relation Operations
    # =====================================================================

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

        with self._get_session() as session:
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
        grouped: dict[str, list[dict]] = defaultdict(list)
        for rel in relations:
            grouped[rel["relation_type"]].append(rel)

        total_created = 0
        for rel_type, rels in grouped.items():
            if not _VALID_REL_TYPE_RE.match(rel_type):
                logger.warning("Skipping invalid relation type: %s", rel_type[:100])
                continue

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
                with self._get_session() as session:
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
    ) -> None:
        """Create a temporal relation between two nodes."""
        query = f"""
        MATCH (a {{id: $source_id}})
        MATCH (b {{id: $target_id}})
        CREATE (a)-[r:{relation_type.value} {{time_gap_seconds: $time_gap}}]->(b)
        RETURN type(r)
        """

        with self._get_session() as session:
            session.run(query, source_id=source_id, target_id=target_id, time_gap=time_gap)

    def create_semantic_relations_batch(self, relations: list[dict]) -> int:
        """Create semantic relations between entities extracted by the LLM.

        Each dict must contain: source_name, target_name, relation_type, frame_id.
        Optional: description, timestamp.

        Entities are matched via the Frame they both belong to (CONTAINS edge)
        to avoid cross-video ambiguity.  Uses MERGE to deduplicate edges and
        increments ``evidence_count`` on repeated observations.
        """
        if not relations:
            return 0

        grouped: dict[str, list[dict]] = defaultdict(list)
        for rel in relations:
            grouped[rel["relation_type"]].append(rel)

        total_created = 0
        for rel_type, rels in grouped.items():
            if not _VALID_REL_TYPE_RE.match(rel_type):
                logger.warning("Skipping invalid semantic relation type: %s", rel_type[:100])
                continue

            batch_data = [
                {
                    "source_name": r["source_name"],
                    "target_name": r["target_name"],
                    "frame_id": r["frame_id"],
                    "description": r.get("description", ""),
                    "timestamp": r.get("timestamp", 0.0),
                    "weight": r.get("weight", 0.5),
                }
                for r in rels
            ]

            query = f"""
            UNWIND $batch AS rel
            MATCH (f:Frame {{id: rel.frame_id}})-[:CONTAINS]->(src:Entity)
            WHERE src.normalized_name = rel.source_name
            MATCH (f)-[:CONTAINS]->(tgt:Entity)
            WHERE tgt.normalized_name = rel.target_name AND tgt.id <> src.id
            MERGE (src)-[r:{rel_type}]->(tgt)
            ON CREATE SET
                r.description = rel.description,
                r.weight = rel.weight,
                r.evidence_count = 1,
                r.first_seen = rel.timestamp
            ON MATCH SET
                r.evidence_count = r.evidence_count + 1,
                r.weight = CASE WHEN rel.weight > r.weight THEN rel.weight ELSE r.weight END,
                r.last_seen = rel.timestamp
            RETURN count(r) as created
            """

            try:
                with self._get_session() as session:
                    result = session.run(query, batch=batch_data)
                    record = result.single()
                    total_created += record["created"] if record else 0
            except Exception as e:
                logger.error(f"Semantic relation creation failed for type {rel_type}: {e}")

        return total_created
