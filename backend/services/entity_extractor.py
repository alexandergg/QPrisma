"""
Entity Extractor Service for QPrisma

Extracts structured entities from video frames using GPT-4o.
Detects people, objects, locations, actions, text (OCR), brands, and events.
"""

import base64
import json
import logging
from datetime import UTC, datetime
from uuid import uuid4

import httpx
from openai import APIConnectionError, APIError, AzureOpenAI, RateLimitError
from tenacity import retry, stop_after_attempt, wait_exponential

from core.azure_credentials import build_openai_client_kwargs
from core.config import settings
from models.graph_models import (
    EntityNode,
    EntityType,
    ExtractedEntity,
    FrameAnalysisResult,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Entity-type normalisation helpers
# ---------------------------------------------------------------------------

_ENTITY_TYPE_ALIASES: dict[str, str] = {
    # Common LLM hallucinations → closest valid EntityType value
    "lighting": "concept",
    "animal": "object",
    "vehicle": "object",
    "place": "location",
    "activity": "action",
    "thing": "object",
    "organization": "brand",
    "product": "object",
    "scene": "location",
    "setting": "location",
    "emotion": "concept",
    "weather": "concept",
    "time": "concept",
    "color": "concept",
    "sound": "concept",
    "music": "concept",
    "food": "object",
    "clothing": "object",
    "furniture": "object",
    "technology": "object",
    "nature": "location",
    "abstract": "concept",
    "gesture": "action",
    "movement": "action",
    "expression": "concept",
    "symbol": "concept",
    "logo": "brand",
    "company": "brand",
    "group": "person",
    "crowd": "person",
}


def _normalize_entity_type(raw_type: str) -> EntityType:
    """Normalize a raw entity type string to a valid EntityType.

    Tries direct enum lookup, then alias mapping, then falls back to CONCEPT
    so that the entity is never silently dropped.
    """
    normalized = raw_type.lower().strip()
    try:
        return EntityType(normalized)
    except ValueError:
        pass
    mapped = _ENTITY_TYPE_ALIASES.get(normalized)
    if mapped is not None:
        return EntityType(mapped)
    logger.warning(f"Unknown entity type '{raw_type}' normalized to 'concept'")
    return EntityType.CONCEPT


# ---------------------------------------------------------------------------
# Relation-type normalisation helpers
# ---------------------------------------------------------------------------

_VALID_SEMANTIC_RELATION_TYPES = frozenset(
    {
        "INTERACTS_WITH",
        "CONTAINS",
        "CAUSES",
        "CAUSED_BY",
        "RELATES_TO",
        "SIMILAR_TO",
        "MENTIONED_IN",
        "APPEARS_WITH",
    }
)

_RELATION_TYPE_MAP: dict[str, str] = {
    "NEAR": "RELATES_TO",
    "ON": "RELATES_TO",
    "INSIDE": "CONTAINS",
    "PART_OF": "CONTAINS",
    "HAS": "CONTAINS",
    "USES": "INTERACTS_WITH",
    "HOLDS": "INTERACTS_WITH",
    "WEARS": "INTERACTS_WITH",
}


def _normalize_relation_type(raw_type: str) -> str:
    """Normalize a relation type to a valid semantic edge label."""
    upper = raw_type.upper().strip()
    if upper in _VALID_SEMANTIC_RELATION_TYPES:
        return upper
    return _RELATION_TYPE_MAP.get(upper, "RELATES_TO")


# System prompt for entity extraction
ENTITY_EXTRACTION_SYSTEM_PROMPT = """You are an expert visual analyst for a video understanding system.
Your task is to extract structured entities, relationships, and context from video frames.

## ENTITY TYPES (use exactly one per entity)

| Type     | What to extract                                               | Name style                         |
|----------|---------------------------------------------------------------|-------------------------------------|
| person   | People: appearance, age estimate, clothing, role              | "woman in red jacket", "presenter" |
| object   | Physical objects: vehicles, furniture, tools, devices, food   | "red sports car", "laptop"          |
| location | Places or settings: indoor/outdoor, specific venue type       | "office meeting room", "park"       |
| action   | Activities being performed by people or machines              | "typing on keyboard", "running"     |
| text     | Visible text: signs, labels, screens, captions                | exact text content                  |
| brand    | Recognizable brands, logos, company names                     | "Nike", "Microsoft"                 |
| concept  | Abstract ideas, emotions, themes represented visually         | "teamwork", "celebration"           |
| event    | Notable events, incidents, or occurrences in the scene        | "press conference", "car accident"  |

## RELATIONSHIPS (between entities)
Use typed relationships to capture how entities relate:
- INTERACTS_WITH: direct interaction (person uses object, people talking)
- CONTAINS: spatial containment (room contains table, car contains person)
- CAUSES: causal link (rain causes umbrella use)
- RELATES_TO: general semantic connection
- SIMILAR_TO: visually or conceptually similar entities

## EXTRACTION RULES
1. Be specific: "woman in blue dress" not "person"; "wooden bookshelf" not "object"
2. Use lowercase names, no special characters
3. Extract ALL visible entities, even partially visible ones
4. Assign confidence 0.7-1.0 for clearly visible, 0.3-0.6 for partially visible
5. Create relationships between entities that interact or are spatially related
6. Never invent entities not supported by the description or visual content
7. Prefer the most specific entity_type — use "concept" only for truly abstract ideas

Output ONLY valid JSON matching the requested schema."""


ENTITY_EXTRACTION_USER_PROMPT = """Analyze this video frame and extract all entities, relationships, and context.

Frame timestamp: {timestamp} seconds
Additional context: {context}

Respond with a JSON object following this exact schema:
{{
    "description": "Overall description of what's happening in the frame",
    "entities": [
        {{
            "entity_type": "person|object|location|action|text|brand|concept|event",
            "name": "descriptive name for the entity",
            "confidence": 0.0-1.0,
            "bounding_box": {{"x": 0-100, "y": 0-100, "width": 0-100, "height": 0-100}} or null,
            "attributes": {{"key": "value"}},
            "description": "brief description"
        }}
    ],
    "relations": [
        {{
            "source": "entity name",
            "target": "entity name",
            "type": "INTERACTS_WITH|CONTAINS|CAUSES|RELATES_TO|SIMILAR_TO",
            "strength": 1-10,
            "description": "brief description of relationship"
        }}
    ],
    "topics": ["topic1", "topic2"],
    "actions": ["action1", "action2"],
    "detected_text": ["text1", "text2"],
    "scene_type": "indoor|outdoor|mixed",
    "scene_context": "brief context description"
}}"""


GLEANING_PROMPT = """Many entities and relationships may have been missed in the previous extraction.
Re-examine the description carefully and extract any additional entities and relationships
that were not captured above. Focus on:
- Subtle or background entities (objects, people, locations partially visible)
- Implicit relationships between already-extracted entities
- Events or actions that were overlooked
- Text, brands, or concepts not yet captured

If no additional entities were missed, respond with:
{{"entities": [], "relations": [], "topics": [], "actions": []}}

Otherwise, respond with the additional entities and relationships using the same JSON format as before."""


class EntityExtractor:
    """
    Service for extracting entities from video frames using GPT-4o.

    Features:
    - Image analysis with GPT-4o Vision
    - Structured entity extraction
    - Relationship detection between entities
    - Result caching to avoid re-processing
    - Batch processing for efficiency
    """

    def __init__(
        self,
        api_key: str | None = None,
        endpoint: str | None = None,
        deployment: str | None = None,
        api_version: str = "2024-08-01-preview",
    ):
        """
        Initialize the entity extractor.

        Args:
            api_key: Azure OpenAI API key.
            endpoint: Azure OpenAI endpoint.
            deployment: GPT-4o deployment name.
            api_version: API version.
        """
        self.api_key = api_key or settings.azure.openai_api_key
        self.endpoint = endpoint or settings.azure.openai_endpoint
        self.deployment = deployment or settings.azure.openai_deployment_gpt
        self.api_version = api_version

        self._client: AzureOpenAI | None = None

    @property
    def client(self) -> AzureOpenAI:
        """Lazy initialization of the Azure OpenAI client."""
        if self._client is None:
            client_kwargs = build_openai_client_kwargs(
                endpoint=self.endpoint,
                api_key=self.api_key,
                api_version=self.api_version,
                use_managed_identity=settings.azure.use_managed_identity,
            )
            if client_kwargs is None:
                raise ValueError("Azure OpenAI client is not configured")
            self._client = AzureOpenAI(**client_kwargs)
        return self._client

    def _encode_image_to_base64(self, image_path: str) -> str:
        """Encode an image to base64."""
        with open(image_path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")

    async def _fetch_image_as_base64(self, image_url: str) -> str:
        """Download an image from a URL and encode it to base64."""
        async with httpx.AsyncClient() as client:
            response = await client.get(image_url)
            response.raise_for_status()
            return base64.b64encode(response.content).decode("utf-8")

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
    )
    def extract_from_image(
        self,
        image_source: str,
        timestamp: float = 0.0,
        context: str = "",
        is_url: bool = True,
    ) -> FrameAnalysisResult:
        """
        Extract entities from an image using GPT-4o Vision.

        Args:
            image_source: Image URL or local path.
            timestamp: Frame timestamp in the video.
            context: Additional context (transcript, previous description, etc.).
            is_url: If True, image_source is a URL; if False, it is a local path.

        Returns:
            FrameAnalysisResult with extracted entities and relationships.
        """
        start_time = datetime.now(UTC)

        # Prepare the image
        if is_url:
            image_content = {
                "type": "image_url",
                "image_url": {"url": image_source, "detail": "high"},
            }
        else:
            base64_image = self._encode_image_to_base64(image_source)
            # Detect image format
            if image_source.lower().endswith(".png"):
                mime_type = "image/png"
            elif image_source.lower().endswith(".gif"):
                mime_type = "image/gif"
            else:
                mime_type = "image/jpeg"

            image_content = {
                "type": "image_url",
                "image_url": {"url": f"data:{mime_type};base64,{base64_image}"},
            }

        # Build the message
        user_message = ENTITY_EXTRACTION_USER_PROMPT.format(
            timestamp=timestamp,
            context=context or "No additional context provided",
        )

        messages = [
            {"role": "system", "content": ENTITY_EXTRACTION_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": user_message},
                    image_content,
                ],
            },
        ]

        # Call GPT-4o
        response = self.client.chat.completions.create(
            model=self.deployment,
            messages=messages,
            max_completion_tokens=2000,
            temperature=1,
            response_format={"type": "json_object"},
        )

        # Parse response
        response_text = response.choices[0].message.content
        analysis_time = (datetime.now(UTC) - start_time).total_seconds() * 1000

        try:
            data = json.loads(response_text)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse GPT-4o response: {e}")
            logger.error(f"Response: {response_text}")
            # Return empty result on error
            return FrameAnalysisResult(
                frame_id=str(uuid4()),
                timestamp=timestamp,
                description="Failed to analyze frame",
                entities=[],
                relations=[],
                topics=[],
                actions=[],
                analysis_time_ms=analysis_time,
            )

        # Convert to Pydantic models
        entities = []
        for e in data.get("entities", []):
            try:
                entity = ExtractedEntity(
                    entity_type=_normalize_entity_type(e.get("entity_type", "object")),
                    name=e.get("name", "unknown"),
                    confidence=float(e.get("confidence", 0.5)),
                    bounding_box=e.get("bounding_box"),
                    attributes=e.get("attributes", {}),
                    description=e.get("description"),
                )
                entities.append(entity)
            except Exception as ex:
                logger.warning(f"Failed to parse entity: {e}, error: {ex}")

        return FrameAnalysisResult(
            frame_id=str(uuid4()),
            timestamp=timestamp,
            description=data.get("description", ""),
            entities=entities,
            relations=data.get("relations", []),
            topics=data.get("topics", []),
            actions=data.get("actions", []),
            detected_text=data.get("detected_text", []),
            scene_type=data.get("scene_type"),
            model_used=self.deployment,
            analysis_time_ms=analysis_time,
        )

    def extract_from_description(
        self,
        description: str,
        timestamp: float = 0.0,
        context: str = "",
        max_gleanings: int = 0,
    ) -> FrameAnalysisResult:
        """
        Extract entities from an existing frame description.

        Useful for re-processing frames that already have a description but no structured entities.
        Supports multi-pass gleaning (GraphRAG pattern) to recover additional entities.

        Args:
            description: Textual description of the frame.
            timestamp: Frame timestamp.
            context: Additional context.
            max_gleanings: Number of continuation passes to recover missed entities
                (0 = disabled, 1 = recommended).

        Returns:
            FrameAnalysisResult with extracted entities.
        """
        start_time = datetime.now(UTC)

        prompt = f"""Given this description of a video frame, extract structured entities and relationships.

Frame timestamp: {timestamp} seconds
Description: {description}
Additional context: {context}

Extract entities, relationships, topics, and actions from the description.
Respond with JSON following this schema:
{{
    "entities": [
        {{
            "entity_type": "person|object|location|action|text|brand|concept|event",
            "name": "entity name",
            "confidence": 0.0-1.0,
            "attributes": {{}},
            "description": "brief description"
        }}
    ],
    "relations": [
        {{
            "source": "entity name",
            "target": "entity name",
            "type": "INTERACTS_WITH|CONTAINS|CAUSES|RELATES_TO|SIMILAR_TO",
            "strength": 1-10,
            "description": "relationship description"
        }}
    ],
    "topics": ["topic1", "topic2"],
    "actions": ["action1", "action2"]
}}"""

        messages = [
            {
                "role": "system",
                "content": ENTITY_EXTRACTION_SYSTEM_PROMPT,
            },
            {"role": "user", "content": prompt},
        ]

        response = self.client.chat.completions.create(
            model=self.deployment,
            messages=messages,
            max_completion_tokens=1500,
            temperature=1,
            response_format={"type": "json_object"},
        )

        response_text = response.choices[0].message.content
        analysis_time = (datetime.now(UTC) - start_time).total_seconds() * 1000

        try:
            data = json.loads(response_text)
        except json.JSONDecodeError:
            return FrameAnalysisResult(
                frame_id=str(uuid4()),
                timestamp=timestamp,
                description=description,
                entities=[],
                relations=[],
                topics=[],
                actions=[],
                analysis_time_ms=analysis_time,
            )

        entities = []
        for e in data.get("entities", []):
            try:
                entity = ExtractedEntity(
                    entity_type=_normalize_entity_type(e.get("entity_type", "object")),
                    name=e.get("name", "unknown"),
                    confidence=float(e.get("confidence", 0.5)),
                    attributes=e.get("attributes", {}),
                    description=e.get("description"),
                )
                entities.append(entity)
            except (ValueError, KeyError, TypeError) as err:
                logger.warning(f"Could not parse entity: {err}")
                continue

        relations = data.get("relations", [])

        # --- Gleaning passes ---
        for gleaning_pass in range(max_gleanings):
            gleaning_messages = [
                messages[0],  # system message
                messages[1],  # original user message
                {"role": "assistant", "content": response_text},
                {"role": "user", "content": GLEANING_PROMPT},
            ]

            try:
                gleaning_response = self.client.chat.completions.create(
                    model=self.deployment,
                    messages=gleaning_messages,
                    max_completion_tokens=1000,
                    temperature=1,
                    response_format={"type": "json_object"},
                )
                gleaning_text = gleaning_response.choices[0].message.content
                gleaning_data = json.loads(gleaning_text)

                new_entities: list[ExtractedEntity] = []
                for e in gleaning_data.get("entities", []):
                    try:
                        entity = ExtractedEntity(
                            entity_type=_normalize_entity_type(e.get("entity_type", "object")),
                            name=e.get("name", "unknown"),
                            confidence=float(e.get("confidence", 0.5)),
                            attributes=e.get("attributes", {}),
                            description=e.get("description"),
                        )
                        new_entities.append(entity)
                    except (ValueError, KeyError, TypeError) as err:
                        logger.warning(f"Could not parse gleaned entity: {err}")

                if not new_entities:
                    break  # No more entities found, stop gleaning

                # Deduplicate by normalized name
                existing_names = {e.name.lower().strip() for e in entities}
                for ent in new_entities:
                    if ent.name.lower().strip() not in existing_names:
                        entities.append(ent)
                        existing_names.add(ent.name.lower().strip())

                # Also merge new relations
                new_relations = gleaning_data.get("relations", [])
                relations.extend(new_relations)

                logger.info(
                    f"Gleaning pass {gleaning_pass + 1}: found {len(new_entities)} additional entities"
                )
            except Exception as e:
                logger.debug(f"Gleaning pass {gleaning_pass + 1} failed: {e}")
                break

        analysis_time = (datetime.now(UTC) - start_time).total_seconds() * 1000

        return FrameAnalysisResult(
            frame_id=str(uuid4()),
            timestamp=timestamp,
            description=description,
            entities=entities,
            relations=relations,
            topics=data.get("topics", []),
            actions=data.get("actions", []),
            model_used=self.deployment,
            analysis_time_ms=analysis_time,
        )

    def convert_to_entity_nodes(
        self,
        analysis: FrameAnalysisResult,
        video_id: str,
    ) -> list[EntityNode]:
        """
        Convert ExtractedEntity to EntityNode for graph storage.

        Args:
            analysis: Frame analysis result.
            video_id: Video ID.

        Returns:
            List of EntityNode ready for Neo4j insertion.
        """
        nodes = []

        for entity in analysis.entities:
            node = EntityNode(
                id=str(uuid4()),
                entity_type=entity.entity_type,
                name=entity.name,
                normalized_name=entity.name.lower().strip().replace(" ", "_"),
                description=entity.description,
                attributes=entity.attributes,
                confidence=entity.confidence,
                bounding_box=entity.bounding_box,
                first_seen_time=analysis.timestamp,
                last_seen_time=analysis.timestamp,
                metadata={"video_id": video_id},
            )
            nodes.append(node)

        return nodes

    def convert_relations_for_graph(
        self,
        analysis: FrameAnalysisResult,
        video_id: str,
        frame_id: str,
    ) -> list[dict]:
        """Convert extracted relations to graph-ready semantic edge data.

        Maps entity names to normalised names and relation types to valid
        RelationType values so they can be stored as typed Neo4j edges.

        Args:
            analysis: Frame analysis result containing relations.
            video_id: Video ID.
            frame_id: Frame node ID for scoping entity lookup.

        Returns:
            List of dicts ready for ``create_semantic_relations_batch``.
        """
        if not analysis.relations:
            return []

        edges: list[dict] = []
        for rel in analysis.relations:
            source = rel.get("source", "").strip()
            target = rel.get("target", "").strip()
            if not source or not target:
                continue

            edges.append(
                {
                    "source_name": source.lower().replace(" ", "_"),
                    "target_name": target.lower().replace(" ", "_"),
                    "relation_type": _normalize_relation_type(rel.get("type", "RELATES_TO")),
                    "description": rel.get("description", ""),
                    "weight": min(1.0, max(0.1, float(rel.get("strength", 5)) / 10.0)),
                    "frame_id": frame_id,
                    "timestamp": analysis.timestamp,
                }
            )

        return edges

    def batch_extract(
        self,
        frames: list[dict],
        max_concurrent: int = 5,
    ) -> list[FrameAnalysisResult]:
        """
        Extract entities from multiple frames.

        Args:
            frames: List of dicts with {"image_url": str, "timestamp": float, "context": str}.
            max_concurrent: Maximum concurrent requests.

        Returns:
            List of FrameAnalysisResult.
        """
        results = []

        # Sequential processing for now to avoid rate limits
        # TODO: Implement parallel processing with semaphore
        for frame in frames:
            try:
                result = self.extract_from_image(
                    image_source=frame.get("image_url") or frame.get("image_path"),
                    timestamp=frame.get("timestamp", 0.0),
                    context=frame.get("context", ""),
                    is_url="image_url" in frame,
                )
                results.append(result)
            except (APIError, APIConnectionError, RateLimitError) as e:
                logger.error(f"OpenAI API error at frame {frame.get('timestamp')}: {e}")
                results.append(
                    FrameAnalysisResult(
                        frame_id=str(uuid4()),
                        timestamp=frame.get("timestamp", 0.0),
                        description=f"API Error: {type(e).__name__}",
                        entities=[],
                        relations=[],
                        topics=[],
                        actions=[],
                    )
                )
            except (OSError, ValueError) as e:
                logger.error(f"Failed to extract from frame at {frame.get('timestamp')}: {e}")
                results.append(
                    FrameAnalysisResult(
                        frame_id=str(uuid4()),
                        timestamp=frame.get("timestamp", 0.0),
                        description=f"Error: {str(e)}",
                        entities=[],
                        relations=[],
                        topics=[],
                        actions=[],
                    )
                )

        return results


# =============================================================================
# Singleton
# =============================================================================

_entity_extractor: EntityExtractor | None = None


def get_entity_extractor() -> EntityExtractor:
    """Get the singleton EntityExtractor instance."""
    global _entity_extractor
    if _entity_extractor is None:
        _entity_extractor = EntityExtractor()
    return _entity_extractor
