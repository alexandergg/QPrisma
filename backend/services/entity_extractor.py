"""
Entity Extractor Service for QPrisma

Extrae entidades estructuradas de frames de video usando GPT-4o.
Detecta personas, objetos, lugares, acciones, texto (OCR), marcas y eventos.
"""

import base64
import json
import logging
import os
from datetime import datetime, UTC
from uuid import uuid4

import httpx
from openai import AzureOpenAI, APIError, APIConnectionError, RateLimitError
from tenacity import retry, stop_after_attempt, wait_exponential

from models.graph_models import (
    EntityNode,
    EntityType,
    ExtractedEntity,
    FrameAnalysisResult,
)

logger = logging.getLogger(__name__)


# Prompt del sistema para extracción de entidades
ENTITY_EXTRACTION_SYSTEM_PROMPT = """You are an expert visual analyst for a video understanding system. Your task is to analyze video frames and extract structured information about entities, relationships, and context.

For each frame, you must identify and extract:

1. **ENTITIES** - Things that can be named and tracked:
   - PERSON: People visible (describe appearance, estimated age, gender, clothing, role if apparent)
   - OBJECT: Physical objects (vehicles, furniture, tools, devices, etc.)
   - LOCATION: Places or settings (indoor/outdoor, type of location)
   - ACTION: Activities being performed
   - TEXT: Any visible text (signs, labels, screens)
   - BRAND: Recognizable brands or logos
   - CONCEPT: Abstract concepts represented visually

2. **RELATIONSHIPS** between entities:
   - Who is interacting with whom/what
   - Spatial relationships (near, on, inside, etc.)
   - Actions connecting entities

3. **TOPICS/THEMES** - What is this frame about?

4. **SCENE CONTEXT** - Indoor/outdoor, time of day, atmosphere

IMPORTANT RULES:
- Use specific, descriptive names for entities (e.g., "red sports car" not just "car")
- Normalize names consistently (lowercase, no special characters)
- Estimate confidence (0.0-1.0) based on visibility and certainty
- Include bounding box estimates as percentages (0-100) if possible
- Be thorough but avoid hallucinating entities that aren't clearly visible

Output ONLY valid JSON matching the specified schema."""


ENTITY_EXTRACTION_USER_PROMPT = """Analyze this video frame and extract all entities, relationships, and context.

Frame timestamp: {timestamp} seconds
Additional context: {context}

Respond with a JSON object following this exact schema:
{{
    "description": "Overall description of what's happening in the frame",
    "entities": [
        {{
            "entity_type": "person|object|location|action|text|brand|concept",
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
            "type": "INTERACTS_WITH|APPEARS_WITH|CONTAINS|CAUSES|NEAR|ON|INSIDE",
            "description": "brief description of relationship"
        }}
    ],
    "topics": ["topic1", "topic2"],
    "actions": ["action1", "action2"],
    "detected_text": ["text1", "text2"],
    "scene_type": "indoor|outdoor|mixed",
    "scene_context": "brief context description"
}}"""


class EntityExtractor:
    """
    Servicio para extraer entidades de frames de video usando GPT-4o.

    Características:
    - Análisis de imágenes con GPT-4o Vision
    - Extracción estructurada de entidades
    - Detección de relaciones entre entidades
    - Cache de resultados para evitar re-procesamiento
    - Batch processing para eficiencia
    """

    def __init__(
        self,
        api_key: str | None = None,
        endpoint: str | None = None,
        deployment: str | None = None,
        api_version: str = "2024-08-01-preview",
    ):
        """
        Inicializa el extractor de entidades.

        Args:
            api_key: Azure OpenAI API key
            endpoint: Azure OpenAI endpoint
            deployment: Nombre del deployment de GPT-4o
            api_version: Versión del API
        """
        self.api_key = api_key or os.getenv("AZURE_OPENAI_API_KEY")
        self.endpoint = endpoint or os.getenv("AZURE_OPENAI_ENDPOINT")
        self.deployment = deployment or os.getenv("AZURE_OPENAI_DEPLOYMENT_GPT", "gpt-4o")
        self.api_version = api_version

        self._client: AzureOpenAI | None = None

    @property
    def client(self) -> AzureOpenAI:
        """Lazy initialization del cliente Azure OpenAI."""
        if self._client is None:
            self._client = AzureOpenAI(
                api_key=self.api_key,
                api_version=self.api_version,
                azure_endpoint=self.endpoint,
            )
        return self._client

    def _encode_image_to_base64(self, image_path: str) -> str:
        """Codifica una imagen a base64."""
        with open(image_path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")

    async def _fetch_image_as_base64(self, image_url: str) -> str:
        """Descarga una imagen desde URL y la codifica a base64."""
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
        Extrae entidades de una imagen usando GPT-4o Vision.

        Args:
            image_source: URL de la imagen o path local
            timestamp: Timestamp del frame en el video
            context: Contexto adicional (transcripción, descripción previa, etc.)
            is_url: Si True, image_source es una URL; si False, es un path local

        Returns:
            FrameAnalysisResult con entidades y relaciones extraídas
        """
        start_time = datetime.now(UTC)

        # Preparar la imagen
        if is_url:
            image_content = {
                "type": "image_url",
                "image_url": {"url": image_source, "detail": "high"},
            }
        else:
            base64_image = self._encode_image_to_base64(image_source)
            # Detectar formato de imagen
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

        # Construir el mensaje
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

        # Llamar a GPT-4o
        response = self.client.chat.completions.create(
            model=self.deployment,
            messages=messages,
            max_completion_tokens=2000,
            temperature=1,
            response_format={"type": "json_object"},
        )

        # Parsear respuesta
        response_text = response.choices[0].message.content
        analysis_time = (datetime.now(UTC) - start_time).total_seconds() * 1000

        try:
            data = json.loads(response_text)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse GPT-4o response: {e}")
            logger.error(f"Response: {response_text}")
            # Retornar resultado vacío en caso de error
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

        # Convertir a modelos Pydantic
        entities = []
        for e in data.get("entities", []):
            try:
                entity = ExtractedEntity(
                    entity_type=EntityType(e.get("entity_type", "object")),
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
            model_used=self.deployment,
            analysis_time_ms=analysis_time,
        )

    def extract_from_description(
        self,
        description: str,
        timestamp: float = 0.0,
        context: str = "",
    ) -> FrameAnalysisResult:
        """
        Extrae entidades de una descripción de frame existente.

        Útil para re-procesar frames que ya tienen descripción pero no entidades estructuradas.

        Args:
            description: Descripción textual del frame
            timestamp: Timestamp del frame
            context: Contexto adicional

        Returns:
            FrameAnalysisResult con entidades extraídas
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
            "entity_type": "person|object|location|action|text|brand|concept",
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
            "type": "INTERACTS_WITH|APPEARS_WITH|CONTAINS|CAUSES",
            "description": "relationship description"
        }}
    ],
    "topics": ["topic1", "topic2"],
    "actions": ["action1", "action2"]
}}"""

        messages = [
            {
                "role": "system",
                "content": "You are an expert at extracting structured information from text descriptions of video frames.",
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
                    entity_type=EntityType(e.get("entity_type", "object")),
                    name=e.get("name", "unknown"),
                    confidence=float(e.get("confidence", 0.5)),
                    attributes=e.get("attributes", {}),
                    description=e.get("description"),
                )
                entities.append(entity)
            except (ValueError, KeyError, TypeError) as err:
                logger.warning(f"Could not parse entity: {err}")
                continue

        return FrameAnalysisResult(
            frame_id=str(uuid4()),
            timestamp=timestamp,
            description=description,
            entities=entities,
            relations=data.get("relations", []),
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
        Convierte ExtractedEntity a EntityNode para almacenar en el grafo.

        Args:
            analysis: Resultado del análisis de frame
            video_id: ID del video

        Returns:
            Lista de EntityNode listos para insertar en Neo4j
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

    def batch_extract(
        self,
        frames: list[dict],
        max_concurrent: int = 5,
    ) -> list[FrameAnalysisResult]:
        """
        Extrae entidades de múltiples frames.

        Args:
            frames: Lista de dicts con {"image_url": str, "timestamp": float, "context": str}
            max_concurrent: Máximo de requests concurrentes

        Returns:
            Lista de FrameAnalysisResult
        """
        results = []

        # Por ahora, procesamiento secuencial para evitar rate limits
        # TODO: Implementar procesamiento paralelo con semáforo
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
    """Obtiene la instancia singleton del EntityExtractor."""
    global _entity_extractor
    if _entity_extractor is None:
        _entity_extractor = EntityExtractor()
    return _entity_extractor
