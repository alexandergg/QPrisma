"""
Relation Builder Service for QPrisma

Builds temporal and semantic relations between nodes in the Knowledge Graph.
Analyses co-occurrence patterns, temporal sequences, and semantic similarity.
"""

import json
import logging
from collections import defaultdict
from dataclasses import dataclass

from openai import APIConnectionError, APIError, AzureOpenAI, RateLimitError

from core.config import settings
from models.graph_models import (
    EntityType,
    FrameAnalysisResult,
    RelationType,
)
from services.knowledge_graph import KnowledgeGraphService

logger = logging.getLogger(__name__)


@dataclass
class EntityOccurrence:
    """Record of a single entity appearance."""

    entity_name: str
    normalized_name: str
    entity_type: EntityType
    frame_id: str
    timestamp: float
    confidence: float


@dataclass
class RelationCandidate:
    """Candidate relation between two entities."""

    source_name: str
    target_name: str
    relation_type: RelationType
    confidence: float
    evidence: list[str]  # Frame IDs where the relation was detected


class RelationBuilder:
    """
    Service for building relations between entities in the Knowledge Graph.

    Relation types:
    1. **Temporal**: BEFORE, AFTER, DURING, SIMULTANEOUS
       - Derived from appearance timestamps

    2. **Co-occurrence**: APPEARS_WITH
       - Entities that appear in the same frame

    3. **Semantic**: INTERACTS_WITH, RELATES_TO, SIMILAR_TO
       - Derived from GPT-4o analysis or rules

    4. **Hierarchical**: CONTAINS, BELONGS_TO
       - Video -> Scene -> Frame -> Entity

    5. **Cross-video**: SAME_ENTITY, TOPIC_OVERLAP
       - Entities that appear across multiple videos
    """

    def __init__(
        self,
        graph_service: KnowledgeGraphService | None = None,
        openai_client: AzureOpenAI | None = None,
    ):
        """
        Initialize the RelationBuilder.

        Args:
            graph_service: Knowledge Graph service
            openai_client: Azure OpenAI client for semantic analysis
        """
        self.graph_service = graph_service
        self._openai_client = openai_client

        # Entity tracking during video processing
        self._entity_occurrences: list[EntityOccurrence] = []
        self._frame_entities: dict[str, list[str]] = defaultdict(list)  # frame_id -> [entity_names]

    @property
    def openai_client(self) -> AzureOpenAI:
        """Lazy initialization of the OpenAI client."""
        if self._openai_client is None:
            self._openai_client = AzureOpenAI(
                api_key=settings.azure.openai_api_key,
                api_version=settings.azure.openai_api_version,
                azure_endpoint=settings.azure.openai_endpoint,
            )
        return self._openai_client

    def reset(self):
        """Clear the builder state for a new video."""
        self._entity_occurrences = []
        self._frame_entities = defaultdict(list)

    # =========================================================================
    # Entity Tracking
    # =========================================================================

    def track_entity(
        self,
        entity_name: str,
        entity_type: EntityType,
        frame_id: str,
        timestamp: float,
        confidence: float = 1.0,
    ):
        """
        Record an entity appearance for subsequent relation analysis.
        """
        normalized = entity_name.lower().strip().replace(" ", "_")

        occurrence = EntityOccurrence(
            entity_name=entity_name,
            normalized_name=normalized,
            entity_type=entity_type,
            frame_id=frame_id,
            timestamp=timestamp,
            confidence=confidence,
        )

        self._entity_occurrences.append(occurrence)
        self._frame_entities[frame_id].append(normalized)

    def track_from_analysis(self, analysis: FrameAnalysisResult, frame_id: str):
        """
        Record all entities from a FrameAnalysisResult.
        """
        for entity in analysis.entities:
            self.track_entity(
                entity_name=entity.name,
                entity_type=entity.entity_type,
                frame_id=frame_id,
                timestamp=analysis.timestamp,
                confidence=entity.confidence,
            )

    # =========================================================================
    # Co-occurrence Relations (APPEARS_WITH)
    # =========================================================================

    def build_cooccurrence_relations(
        self,
        min_cooccurrences: int = 2,
        min_confidence: float = 0.5,
    ) -> list[RelationCandidate]:
        """
        Build APPEARS_WITH relations based on frame co-occurrence.

        Args:
            min_cooccurrences: Minimum number of frames in which entities must co-appear
            min_confidence: Minimum confidence to consider

        Returns:
            List of RelationCandidate
        """
        # Count co-occurrences
        cooccurrence_count: dict[tuple[str, str], list[str]] = defaultdict(list)

        for frame_id, entities in self._frame_entities.items():
            # Generate unique sorted pairs
            unique_entities = list(set(entities))
            for i, e1 in enumerate(unique_entities):
                for e2 in unique_entities[i + 1 :]:
                    # Ordenar para consistencia
                    pair = tuple(sorted([e1, e2]))
                    cooccurrence_count[pair].append(frame_id)

        # Filter and create candidates
        candidates = []
        for (e1, e2), frames in cooccurrence_count.items():
            if len(frames) >= min_cooccurrences:
                # Calculate confidence based on frequency
                confidence = min(1.0, len(frames) / 10)  # Normalizar a 10 frames

                candidate = RelationCandidate(
                    source_name=e1,
                    target_name=e2,
                    relation_type=RelationType.APPEARS_WITH,
                    confidence=confidence,
                    evidence=frames,
                )
                candidates.append(candidate)

        logger.info(f"Built {len(candidates)} co-occurrence relations")
        return candidates

    # =========================================================================
    # Temporal Relations (BEFORE, AFTER, DURING, SIMULTANEOUS)
    # =========================================================================

    def build_temporal_relations(
        self,
        time_threshold: float = 5.0,  # seconds
    ) -> list[RelationCandidate]:
        """
        Build temporal relations between entities.

        Args:
            time_threshold: Time window for considering entities "close in time"

        Returns:
            List of RelationCandidate with temporal relations
        """
        # Group occurrences by entity
        entity_times: dict[str, list[float]] = defaultdict(list)

        for occ in self._entity_occurrences:
            entity_times[occ.normalized_name].append(occ.timestamp)

        # Calculate the temporal range of each entity
        entity_ranges: dict[str, tuple[float, float]] = {}
        for entity, times in entity_times.items():
            entity_ranges[entity] = (min(times), max(times))

        candidates = []
        entities = list(entity_ranges.keys())

        for i, e1 in enumerate(entities):
            start1, end1 = entity_ranges[e1]

            for e2 in entities[i + 1 :]:
                start2, end2 = entity_ranges[e2]

                # Determine the type of temporal relation
                relation_type = None
                confidence = 0.8

                # BEFORE: e1 termina antes de que e2 empiece
                if end1 < start2 - time_threshold:
                    relation_type = RelationType.BEFORE
                    start2 - end1

                # AFTER: e1 starts after e2 ends
                elif start1 > end2 + time_threshold:
                    relation_type = RelationType.AFTER
                    start1 - end2

                # SIMULTANEOUS: appear at the same time (within the threshold)
                elif abs(start1 - start2) <= time_threshold and abs(end1 - end2) <= time_threshold:
                    relation_type = RelationType.SIMULTANEOUS
                    confidence = 0.9

                # DURING: one is temporally contained within the other
                elif start1 >= start2 and end1 <= end2:
                    relation_type = RelationType.DURING  # e1 during e2
                elif start2 >= start1 and end2 <= end1:
                    # Swap to keep e1 as the contained entity
                    e1, e2 = e2, e1
                    relation_type = RelationType.DURING

                if relation_type:
                    candidate = RelationCandidate(
                        source_name=e1,
                        target_name=e2,
                        relation_type=relation_type,
                        confidence=confidence,
                        evidence=[],
                    )
                    candidates.append(candidate)

        logger.info(f"Built {len(candidates)} temporal relations")
        return candidates

    # =========================================================================
    # Semantic Relations (GPT-4o powered)
    # =========================================================================

    def infer_semantic_relations(
        self,
        entity_pairs: list[tuple[str, str]],
        context: str = "",
    ) -> list[RelationCandidate]:
        """
        Infer semantic relations between entity pairs using GPT-4o.

        Args:
            entity_pairs: List of (entity1, entity2) tuples to analyse
            context: Video context (transcript, description, etc.)

        Returns:
            List of RelationCandidate with inferred relations
        """
        if not entity_pairs:
            return []

        # Preparar prompt
        pairs_text = "\n".join([f"- {e1} <-> {e2}" for e1, e2 in entity_pairs])

        prompt = f"""Analyze the following pairs of entities that appear in a video and determine if there are meaningful relationships between them.

Entity pairs:
{pairs_text}

Video context: {context or "No additional context"}

For each pair, determine:
1. Is there a meaningful relationship? (yes/no)
2. What type? Choose from: INTERACTS_WITH, RELATES_TO, CAUSES, CAUSED_BY, CONTAINS
3. Brief description of the relationship
4. Confidence (0.0-1.0)

Respond with JSON:
{{
    "relations": [
        {{
            "source": "entity1",
            "target": "entity2",
            "has_relation": true,
            "type": "INTERACTS_WITH",
            "description": "description",
            "confidence": 0.8
        }}
    ]
}}

Only include pairs where has_relation is true."""

        try:
            response = self.openai_client.chat.completions.create(
                model=settings.azure.openai_deployment_gpt,
                messages=[
                    {
                        "role": "system",
                        "content": "You are an expert at understanding relationships between entities in video content.",
                    },
                    {"role": "user", "content": prompt},
                ],
                max_completion_tokens=1500,
                temperature=1,
                response_format={"type": "json_object"},
            )

            data = json.loads(response.choices[0].message.content)
            candidates = []

            for rel in data.get("relations", []):
                if rel.get("has_relation", False):
                    try:
                        relation_type = RelationType(rel["type"])
                    except ValueError:
                        relation_type = RelationType.RELATES_TO

                    candidate = RelationCandidate(
                        source_name=rel["source"].lower().strip().replace(" ", "_"),
                        target_name=rel["target"].lower().strip().replace(" ", "_"),
                        relation_type=relation_type,
                        confidence=float(rel.get("confidence", 0.5)),
                        evidence=[],
                    )
                    candidates.append(candidate)

            logger.info(f"Inferred {len(candidates)} semantic relations")
            return candidates

        except (APIError, APIConnectionError, RateLimitError) as e:
            logger.error(f"OpenAI API error inferring semantic relations: {e}")
            return []
        except json.JSONDecodeError as e:
            logger.error(f"JSON parsing error in semantic relations: {e}")
            return []

    # =========================================================================
    # Cross-Video Relations
    # =========================================================================

    def find_cross_video_entities(
        self,
        video_id: str,
        similarity_threshold: float = 0.85,
    ) -> list[RelationCandidate]:
        """
        Find similar entities across other videos.

        Requires graph_service to be configured.

        Args:
            video_id: Current video ID
            similarity_threshold: Similarity threshold for considering entities the "same entity"

        Returns:
            List of RelationCandidate with SAME_ENTITY relations
        """
        if not self.graph_service:
            logger.warning("Graph service not configured, skipping cross-video analysis")
            return []

        candidates = []

        # Retrieve unique entities from the current video
        current_entities = set()
        for occ in self._entity_occurrences:
            current_entities.add((occ.normalized_name, occ.entity_type))

        # Buscar en otros videos
        for entity_name, entity_type in current_entities:
            try:
                # Search for similar entities in the graph
                similar = self.graph_service.search_entities(
                    query_text=entity_name.replace("_", " "),
                    entity_types=[entity_type],
                    limit=5,
                )

                for result in similar:
                    other_entity = result["entity"]
                    # Ignorar si es del mismo video
                    if other_entity.get("metadata", {}).get("video_id") == video_id:
                        continue

                    # Calcular similitud simple (nombre)
                    other_name = other_entity.get("normalized_name", "")
                    if entity_name == other_name:
                        candidate = RelationCandidate(
                            source_name=entity_name,
                            target_name=f"{other_name}@{other_entity.get('id')}",
                            relation_type=RelationType.SAME_ENTITY,
                            confidence=0.95,
                            evidence=[other_entity.get("id")],
                        )
                        candidates.append(candidate)

            except Exception as e:
                logger.debug(f"Error searching for {entity_name}: {e}")

        logger.info(f"Found {len(candidates)} cross-video entity matches")
        return candidates

    # =========================================================================
    # Build All Relations
    # =========================================================================

    def build_all_relations(
        self,
        include_semantic: bool = True,
        include_cross_video: bool = False,
        video_context: str = "",
    ) -> dict[str, list[RelationCandidate]]:
        """
        Build all possible relations.

        Args:
            include_semantic: Whether to include semantic analysis with GPT-4o
            include_cross_video: Whether to search for entities in other videos
            video_context: Video context for semantic analysis

        Returns:
            Dict of relations grouped by type
        """
        results = {}

        # 1. Co-occurrence
        results["cooccurrence"] = self.build_cooccurrence_relations()

        # 2. Temporal relations
        results["temporal"] = self.build_temporal_relations()

        # 3. Semantic (optional, uses GPT-4o)
        if include_semantic and len(self._entity_occurrences) > 0:
            # Select pairs for semantic analysis
            # (entities that co-occur but have no obvious relation)
            entity_names = list({o.normalized_name for o in self._entity_occurrences})

            # Limit to 20 pairs to avoid exceeding token budget
            pairs_to_analyze = []
            for i, e1 in enumerate(entity_names[:10]):
                for e2 in entity_names[i + 1 : 15]:
                    pairs_to_analyze.append((e1, e2))

            results["semantic"] = self.infer_semantic_relations(
                entity_pairs=pairs_to_analyze[:20],
                context=video_context,
            )

        # 4. Cross-video (optional, requires video_id from context)
        if include_cross_video and self.graph_service:
            results["cross_video"] = []  # Deferred: needs video_id from context

        return results

    # =========================================================================
    # Persist Relations to Graph
    # =========================================================================

    def persist_relations(
        self,
        relations: list[RelationCandidate],
        graph_service: KnowledgeGraphService | None = None,
    ) -> int:
        """
        Persist relations in the Knowledge Graph using batched UNWIND operations.

        Args:
            relations: List of RelationCandidate
            graph_service: Graph service (uses self.graph_service if not provided)

        Returns:
            Number of relations created
        """
        service = graph_service or self.graph_service
        if not service:
            raise ValueError("No graph service configured")

        if not relations:
            return 0

        batch_data = [
            {
                "source_id": rel.source_name,
                "target_id": rel.target_name,
                "relation_type": rel.relation_type.value,
                "confidence": rel.confidence,
                "evidence_count": len(rel.evidence),
            }
            for rel in relations
        ]

        try:
            created = service.create_relations_batch(batch_data)
        except Exception as e:
            logger.error(f"Batch relation persistence failed: {e}")
            created = 0

        logger.info(f"Persisted {created}/{len(relations)} relations to graph")
        return created


# =============================================================================
# Singleton
# =============================================================================

_relation_builder: RelationBuilder | None = None


def get_relation_builder(
    graph_service: KnowledgeGraphService | None = None,
) -> RelationBuilder:
    """Return the singleton instance of RelationBuilder."""
    global _relation_builder
    if _relation_builder is None:
        _relation_builder = RelationBuilder(graph_service=graph_service)
    return _relation_builder
