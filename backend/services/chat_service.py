"""
Chat Service

Business logic for conversational AI chat with video context.
Extracted from chat_routes.py to maintain proper layering.
"""

import logging

from openai import AsyncAzureOpenAI

from core.config import settings
from models.graph_models import NodeType

logger = logging.getLogger(__name__)

# System prompt for chat interactions
CHAT_SYSTEM_PROMPT = """You are QPrisma, an AI assistant specialized in analyzing and explaining video content.

Your role is to help users understand what happens in their videos by using the context provided from video analysis.

## How to respond:
1. **Always cite timestamps** - Reference specific moments like [0:45] or [2:30] so users can navigate to them
2. **Start with the big picture** - Use the VIDEO SUMMARY to understand the overall content before diving into details
3. **Synthesize information** - Combine visual descriptions with audio/speech content for complete answers
4. **Be specific** - Use details from the context rather than generic descriptions
5. **Acknowledge limitations** - If the context doesn't contain relevant information, say so clearly
6. **Structure longer answers** - Use bullet points or sections for complex responses

## Context interpretation:
- **VIDEO SUMMARY** = High-level overview of what the entire video is about
- **KEY TOPICS** = Main subjects covered in the video
- **VISUAL CONTENT** = What is shown/seen in the video at each timestamp
- **AUDIO/SPEECH** = What is said/spoken in the video (transcript)
- **ENTITIES** = People, objects, brands, or concepts detected

When the user asks about the video, base your answer on the provided context. Use the VIDEO SUMMARY to give context for your answers. If you need to make inferences, make it clear you're interpreting the available information."""


class ChatService:
    """Service for handling chat interactions with video context."""

    def __init__(self, openai_client: AsyncAzureOpenAI, graph_search_service):
        self.openai_client = openai_client
        self.graph_search_service = graph_search_service
        self.deployment = settings.azure.openai_deployment_gpt

    async def _load_video_summary(self, media_id: str) -> tuple[str, list[str]]:
        """Load video summary and topics from Neo4j."""
        video_summary = ""
        video_topics = []
        try:
            gs = self.graph_search_service
            if not gs.graph_service.is_connected:
                gs.graph_service.connect()

            if gs.graph_service.is_connected:
                with gs.graph_service.get_session() as session:
                    result = session.run(
                        """
                        MATCH (v:Video)
                        WHERE v.video_id = $media_id OR v.id = $media_id
                        RETURN v.summary as summary, v.topics as topics
                        """,
                        media_id=media_id,
                    )
                    record = result.single()
                    if record:
                        video_summary = record.get("summary") or ""
                        video_topics = record.get("topics") or []
                        if video_summary:
                            logger.info(
                                f"Loaded video summary ({len(video_summary)} chars) "
                                f"and {len(video_topics)} topics from Neo4j"
                            )
        except Exception as e:
            logger.warning(f"Could not load video summary from Neo4j: {e}")

        return video_summary, video_topics

    async def _build_video_context(self, message: str, media_id: str) -> tuple[str, list[dict]]:
        """Build context string and sources from video search results."""
        context = ""
        sources = []
        video_summary, video_topics = await self._load_video_summary(media_id)

        try:
            gs = self.graph_search_service
            if not gs.graph_service.is_connected:
                gs.graph_service.connect()

            if not gs.graph_service.is_connected:
                logger.warning("Neo4j not connected - cannot search video context")
                return context, sources

            search_response = await gs.hybrid_search(
                query_text=message,
                node_types=[NodeType.FRAME, NodeType.AUDIO_SEGMENT, NodeType.ENTITY],
                video_id=media_id,
                limit=20,
                expansion_hops=2,
                use_reranking=True,
            )

            logger.info(
                f"Hybrid search: {search_response.total_results} results, "
                f"vector_time={search_response.vector_search_time_ms:.0f}ms"
            )

            visual_context = []
            audio_context = []
            entity_context = []

            for result in search_response.results:
                ts = result.content.get("timestamp")

                if result.node_type == NodeType.FRAME:
                    desc = result.content.get("description", "")
                    if ts is not None and desc:
                        visual_context.append(f"[{ts:.1f}s] {desc[:400]}")
                        sources.append(
                            {
                                "timestamp": float(ts),
                                "type": "visual",
                                "description": desc[:200],
                                "score": result.combined_score,
                            }
                        )
                elif result.node_type == NodeType.AUDIO_SEGMENT:
                    text = result.content.get("text", "")
                    if ts is not None and text:
                        audio_context.append(f'[{ts:.1f}s] "{text[:300]}"')
                        sources.append(
                            {
                                "timestamp": float(ts),
                                "type": "audio",
                                "description": text[:200],
                                "score": result.combined_score,
                            }
                        )
                elif result.node_type == NodeType.ENTITY:
                    name = result.content.get("name", "")
                    entity_type = result.content.get("type", "entity")
                    if name:
                        entity_context.append(f"{entity_type}: {name}")
                        sources.append(
                            {
                                "timestamp": ts or 0,
                                "type": "entity",
                                "description": f"{entity_type}: {name}",
                                "score": result.combined_score,
                            }
                        )

            # Build structured context string
            if video_summary:
                context += "**VIDEO SUMMARY:**\n"
                context += video_summary + "\n"
                if video_topics:
                    context += f"\n**KEY TOPICS:** {', '.join(video_topics)}\n"

            if visual_context:
                context += "\n\n**VISUAL CONTENT (what's shown in the video):**\n"
                context += "\n".join(visual_context[:10])

            if audio_context:
                context += "\n\n**AUDIO/SPEECH (what's said in the video):**\n"
                context += "\n".join(audio_context[:10])

            if entity_context:
                context += "\n\n**ENTITIES DETECTED:**\n"
                context += ", ".join(set(entity_context[:15]))

            sources.sort(key=lambda x: x.get("timestamp", 0))

        except Exception as e:
            logger.warning(f"Error getting video context from Neo4j: {e}")

        return context, sources

    async def chat(
        self,
        message: str,
        media_id: str | None = None,
        chat_history: list[dict] | None = None,
    ) -> tuple[str, list[dict]]:
        """
        Process a chat message, optionally with video context via RAG.

        Returns:
            Tuple of (assistant_response, sources)
        """
        context = ""
        sources = []

        if media_id:
            logger.info(f"Chat search: query='{message}', media_id={media_id}")
            context, sources = await self._build_video_context(message, media_id)

        # Build messages
        messages = [{"role": "system", "content": CHAT_SYSTEM_PROMPT}]

        if chat_history:
            for msg in chat_history:
                messages.append(
                    {"role": msg.get("role", "user"), "content": msg.get("content", "")}
                )

        if context:
            user_message = (
                f"User question: {message}\n\n"
                f"---\n**RELEVANT VIDEO CONTEXT:**\n{context}\n---\n\n"
                f"Please answer the user's question based on the video context above."
            )
        else:
            user_message = message

        messages.append({"role": "user", "content": user_message})

        response = await self.openai_client.chat.completions.create(
            model=self.deployment,
            messages=messages,
            max_completion_tokens=800,
            temperature=1,
        )
        assistant_message = response.choices[0].message.content

        return assistant_message, sources
