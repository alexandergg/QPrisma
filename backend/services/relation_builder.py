"""
Relation Builder Service for QPrisma

Construye relaciones temporales y semánticas entre nodos del Knowledge Graph.
Analiza patrones de co-ocurrencia, secuencias temporales y similitud semántica.
"""

import json
import logging
import os
from collections import defaultdict
from dataclasses import dataclass

from openai import AzureOpenAI, APIError, APIConnectionError, RateLimitError

from models.graph_models import (
    EntityType,
    FrameAnalysisResult,
    RelationType,
)
from services.knowledge_graph import KnowledgeGraphService

logger = logging.getLogger(__name__)


@dataclass
class EntityOccurrence:
    """Registro de aparición de una entidad."""

    entity_name: str
    normalized_name: str
    entity_type: EntityType
    frame_id: str
    timestamp: float
    confidence: float


@dataclass
class RelationCandidate:
    """Candidato a relación entre dos entidades."""

    source_name: str
    target_name: str
    relation_type: RelationType
    confidence: float
    evidence: list[str]  # Frame IDs donde se detectó la relación


class RelationBuilder:
    """
    Servicio para construir relaciones entre entidades en el Knowledge Graph.

    Tipos de relaciones:
    1. **Temporales**: BEFORE, AFTER, DURING, SIMULTANEOUS
       - Basadas en timestamps de aparición

    2. **Co-ocurrencia**: APPEARS_WITH
       - Entidades que aparecen en el mismo frame

    3. **Semánticas**: INTERACTS_WITH, RELATES_TO, SIMILAR_TO
       - Basadas en análisis de GPT-4o o reglas

    4. **Jerárquicas**: CONTAINS, BELONGS_TO
       - Video → Scene → Frame → Entity

    5. **Cross-video**: SAME_ENTITY, TOPIC_OVERLAP
       - Entidades que aparecen en múltiples videos
    """

    def __init__(
        self,
        graph_service: KnowledgeGraphService | None = None,
        openai_client: AzureOpenAI | None = None,
    ):
        """
        Inicializa el RelationBuilder.

        Args:
            graph_service: Servicio del Knowledge Graph
            openai_client: Cliente de Azure OpenAI para análisis semántico
        """
        self.graph_service = graph_service
        self._openai_client = openai_client

        # Tracking de entidades durante el procesamiento de un video
        self._entity_occurrences: list[EntityOccurrence] = []
        self._frame_entities: dict[str, list[str]] = defaultdict(list)  # frame_id -> [entity_names]

    @property
    def openai_client(self) -> AzureOpenAI:
        """Lazy initialization del cliente OpenAI."""
        if self._openai_client is None:
            self._openai_client = AzureOpenAI(
                api_key=os.getenv("AZURE_OPENAI_API_KEY"),
                api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-08-01-preview"),
                azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
            )
        return self._openai_client

    def reset(self):
        """Limpia el estado del builder para un nuevo video."""
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
        Registra una aparición de entidad para posterior análisis de relaciones.
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
        Registra todas las entidades de un FrameAnalysisResult.
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
        Construye relaciones APPEARS_WITH basadas en co-ocurrencia en frames.

        Args:
            min_cooccurrences: Mínimo de frames donde deben co-aparecer
            min_confidence: Confianza mínima para considerar

        Returns:
            Lista de RelationCandidate
        """
        # Contar co-ocurrencias
        cooccurrence_count: dict[tuple[str, str], list[str]] = defaultdict(list)

        for frame_id, entities in self._frame_entities.items():
            # Generar pares únicos ordenados
            unique_entities = list(set(entities))
            for i, e1 in enumerate(unique_entities):
                for e2 in unique_entities[i + 1 :]:
                    # Ordenar para consistencia
                    pair = tuple(sorted([e1, e2]))
                    cooccurrence_count[pair].append(frame_id)

        # Filtrar y crear candidatos
        candidates = []
        for (e1, e2), frames in cooccurrence_count.items():
            if len(frames) >= min_cooccurrences:
                # Calcular confianza basada en frecuencia
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
        time_threshold: float = 5.0,  # segundos
    ) -> list[RelationCandidate]:
        """
        Construye relaciones temporales entre entidades.

        Args:
            time_threshold: Ventana de tiempo para considerar entidades "cercanas"

        Returns:
            Lista de RelationCandidate con relaciones temporales
        """
        # Agrupar ocurrencias por entidad
        entity_times: dict[str, list[float]] = defaultdict(list)

        for occ in self._entity_occurrences:
            entity_times[occ.normalized_name].append(occ.timestamp)

        # Calcular rango temporal de cada entidad
        entity_ranges: dict[str, tuple[float, float]] = {}
        for entity, times in entity_times.items():
            entity_ranges[entity] = (min(times), max(times))

        candidates = []
        entities = list(entity_ranges.keys())

        for i, e1 in enumerate(entities):
            start1, end1 = entity_ranges[e1]

            for e2 in entities[i + 1 :]:
                start2, end2 = entity_ranges[e2]

                # Determinar tipo de relación temporal
                relation_type = None
                confidence = 0.8

                # BEFORE: e1 termina antes de que e2 empiece
                if end1 < start2 - time_threshold:
                    relation_type = RelationType.BEFORE
                    start2 - end1

                # AFTER: e1 empieza después de que e2 termine
                elif start1 > end2 + time_threshold:
                    relation_type = RelationType.AFTER
                    start1 - end2

                # SIMULTANEOUS: aparecen al mismo tiempo (dentro del threshold)
                elif abs(start1 - start2) <= time_threshold and abs(end1 - end2) <= time_threshold:
                    relation_type = RelationType.SIMULTANEOUS
                    confidence = 0.9

                # DURING: uno está contenido en el otro temporalmente
                elif start1 >= start2 and end1 <= end2:
                    relation_type = RelationType.DURING  # e1 during e2
                elif start2 >= start1 and end2 <= end1:
                    # Invertir para mantener e1 como contenido
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
        Infiere relaciones semánticas entre pares de entidades usando GPT-4o.

        Args:
            entity_pairs: Lista de tuplas (entity1, entity2) a analizar
            context: Contexto del video (transcripción, descripción, etc.)

        Returns:
            Lista de RelationCandidate con relaciones inferidas
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
                model=os.getenv("AZURE_OPENAI_DEPLOYMENT_GPT", "gpt-4o"),
                messages=[
                    {
                        "role": "system",
                        "content": "You are an expert at understanding relationships between entities in video content.",
                    },
                    {"role": "user", "content": prompt},
                ],
                max_tokens=1500,
                temperature=0.3,
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
        Encuentra entidades similares en otros videos.

        Requiere que el graph_service esté configurado.

        Args:
            video_id: ID del video actual
            similarity_threshold: Umbral de similitud para considerar "misma entidad"

        Returns:
            Lista de RelationCandidate con relaciones SAME_ENTITY
        """
        if not self.graph_service:
            logger.warning("Graph service not configured, skipping cross-video analysis")
            return []

        candidates = []

        # Obtener entidades únicas del video actual
        current_entities = set()
        for occ in self._entity_occurrences:
            current_entities.add((occ.normalized_name, occ.entity_type))

        # Buscar en otros videos
        for entity_name, entity_type in current_entities:
            try:
                # Buscar entidades similares en el grafo
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
        Construye todas las relaciones posibles.

        Args:
            include_semantic: Si incluir análisis semántico con GPT-4o
            include_cross_video: Si buscar entidades en otros videos
            video_context: Contexto del video para análisis semántico

        Returns:
            Dict con relaciones agrupadas por tipo
        """
        results = {}

        # 1. Co-ocurrencia
        results["cooccurrence"] = self.build_cooccurrence_relations()

        # 2. Temporal
        results["temporal"] = self.build_temporal_relations()

        # 3. Semántico (opcional, usa GPT-4o)
        if include_semantic and len(self._entity_occurrences) > 0:
            # Seleccionar pares para análisis semántico
            # (entidades que co-ocurren pero no tienen relación obvia)
            entity_names = list({o.normalized_name for o in self._entity_occurrences})

            # Limitar a 20 pares para no exceder tokens
            pairs_to_analyze = []
            for i, e1 in enumerate(entity_names[:10]):
                for e2 in entity_names[i + 1 : 15]:
                    pairs_to_analyze.append((e1, e2))

            results["semantic"] = self.infer_semantic_relations(
                entity_pairs=pairs_to_analyze[:20],
                context=video_context,
            )

        # 4. Cross-video (opcional)
        if include_cross_video and self.graph_service:
            # Necesitamos el video_id del contexto
            results["cross_video"] = []  # TODO: Implementar cuando tengamos video_id

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
        Persiste las relaciones en el Knowledge Graph using batched UNWIND operations.

        Args:
            relations: Lista de RelationCandidate
            graph_service: Servicio del grafo (usa self.graph_service si no se proporciona)

        Returns:
            Número de relaciones creadas
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
    """Obtiene la instancia singleton del RelationBuilder."""
    global _relation_builder
    if _relation_builder is None:
        _relation_builder = RelationBuilder(graph_service=graph_service)
    return _relation_builder
