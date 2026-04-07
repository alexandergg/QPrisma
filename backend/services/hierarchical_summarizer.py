"""
Hierarchical Summarizer Service
===============================
Generates multi-level summaries for video content.

Hierarchy:
    Frame Analysis → Scene Summary → Chapter Summary → Video Summary

This approach provides:
- Better context for RAG (scene-level context instead of frame-level)
- Automatic chapter titles for navigation
- Executive summaries for quick understanding
- Key topic extraction for categorization
"""

import json
import logging
from dataclasses import dataclass
from typing import Any

from openai import APIConnectionError, APIError, AzureOpenAI, RateLimitError

from core.concurrency import map_concurrent
from core.config import create_azure_openai_client, get_settings
from services.scene_analyzer import Scene, VideoStructure

logger = logging.getLogger(__name__)


@dataclass
class SummaryConfig:
    """Configuration for summarization."""

    scene_summary_max_tokens: int = 200
    chapter_summary_max_tokens: int = 300
    video_summary_max_tokens: int = 500
    generate_titles: bool = True
    extract_topics: bool = True
    language: str = "en"  # or "es" for Spanish


class HierarchicalSummarizer:
    """
    Generates hierarchical summaries for video content.

    Uses GPT-4o to create coherent summaries at multiple levels,
    enabling better search context and navigation.
    """

    def __init__(self, azure_client: AzureOpenAI | None = None):
        """Initialize with Azure OpenAI client."""
        self.client = azure_client or create_azure_openai_client()
        self.deployment = get_settings().azure.openai_deployment_gpt

    async def summarize_scene(
        self, scene: Scene, config: SummaryConfig = SummaryConfig()
    ) -> dict[str, Any]:
        """
        Generate a summary for a single scene.

        Combines visual descriptions, transcript, and detected objects
        into a coherent scene summary.
        """
        # Build context from scene data
        context_parts = []

        if scene.visual_description:
            context_parts.append(f"Visual content: {scene.visual_description}")

        if scene.transcript_segment:
            context_parts.append(f"Audio/Speech: {scene.transcript_segment}")

        if scene.detected_objects:
            objects_str = ", ".join(scene.detected_objects[:10])
            context_parts.append(f"Objects detected: {objects_str}")

        context = "\n".join(context_parts)

        if not context.strip():
            return {
                "summary": f"Scene {scene.scene_id}: Visual content from {scene.start_time:.1f}s to {scene.end_time:.1f}s",
                "title": f"Scene {scene.scene_id + 1}",
                "key_elements": [],
            }

        prompt = f"""Analyze this video scene and provide:
1. A concise summary (2-3 sentences) describing what happens
2. A short title (3-5 words) for this scene
3. Key elements (up to 5 important things shown/mentioned)

Scene duration: {scene.duration:.1f} seconds
Timestamp: {scene.start_time:.1f}s - {scene.end_time:.1f}s

Content:
{context}

Respond in JSON format:
{{
    "summary": "...",
    "title": "...",
    "key_elements": ["...", "..."]
}}"""

        try:
            response = self.client.chat.completions.create(
                model=self.deployment,
                messages=[
                    {
                        "role": "system",
                        "content": "You are a video content analyst. Provide concise, accurate summaries.",
                    },
                    {"role": "user", "content": prompt},
                ],
                max_completion_tokens=config.scene_summary_max_tokens,
                temperature=1,
                response_format={"type": "json_object"},
            )

            result = json.loads(response.choices[0].message.content)
            return result

        except (APIError, APIConnectionError, RateLimitError) as e:
            logger.error(f"OpenAI API error in scene summarization: {e}")
            return {
                "summary": scene.visual_description or f"Scene {scene.scene_id}",
                "title": f"Scene {scene.scene_id + 1}",
                "key_elements": scene.detected_objects or [],
            }
        except json.JSONDecodeError as e:
            logger.error(f"JSON parsing error in scene summarization: {e}")
            return {
                "summary": scene.visual_description or f"Scene {scene.scene_id}",
                "title": f"Scene {scene.scene_id + 1}",
                "key_elements": scene.detected_objects or [],
            }

    async def summarize_chapter(
        self, chapter: dict[str, Any], scenes: list[Scene], config: SummaryConfig = SummaryConfig()
    ) -> dict[str, Any]:
        """
        Generate a summary for a chapter (group of scenes).
        """
        # Get scenes in this chapter
        chapter_scene_ids = set(chapter.get("scene_ids", []))
        chapter_scenes = [s for s in scenes if s.scene_id in chapter_scene_ids]

        if not chapter_scenes:
            return {
                "summary": f"Chapter {chapter.get('chapter_id', 0) + 1}",
                "title": f"Part {chapter.get('chapter_id', 0) + 1}",
                "themes": [],
            }

        # Build context from scene summaries
        scene_summaries = []
        for scene in chapter_scenes:
            if scene.summary:
                scene_summaries.append(f"- {scene.summary}")
            elif scene.visual_description:
                scene_summaries.append(f"- {scene.visual_description[:200]}")

        context = "\n".join(scene_summaries)

        prompt = f"""Summarize this video chapter containing {len(chapter_scenes)} scenes.

Duration: {chapter.get('duration', 0):.1f} seconds
Timestamp: {chapter.get('start_time', 0):.1f}s - {chapter.get('end_time', 0):.1f}s

Scene summaries:
{context}

Provide:
1. A chapter summary (3-4 sentences) capturing the main content
2. A chapter title (3-6 words)
3. Main themes/topics (up to 3)

Respond in JSON format:
{{
    "summary": "...",
    "title": "...",
    "themes": ["...", "..."]
}}"""

        try:
            response = self.client.chat.completions.create(
                model=self.deployment,
                messages=[
                    {
                        "role": "system",
                        "content": "You are a video content analyst creating chapter summaries.",
                    },
                    {"role": "user", "content": prompt},
                ],
                max_completion_tokens=config.chapter_summary_max_tokens,
                temperature=1,
                response_format={"type": "json_object"},
            )

            result = json.loads(response.choices[0].message.content)
            return result

        except (APIError, APIConnectionError, RateLimitError) as e:
            logger.error(f"OpenAI API error in chapter summarization: {e}")
            return {
                "summary": f"Chapter covering {chapter.get('start_time', 0):.0f}s to {chapter.get('end_time', 0):.0f}s",
                "title": f"Part {chapter.get('chapter_id', 0) + 1}",
                "themes": [],
            }
        except json.JSONDecodeError as e:
            logger.error(f"JSON parsing error in chapter summarization: {e}")
            return {
                "summary": f"Chapter covering {chapter.get('start_time', 0):.0f}s to {chapter.get('end_time', 0):.0f}s",
                "title": f"Part {chapter.get('chapter_id', 0) + 1}",
                "themes": [],
            }

    async def summarize_video(
        self, structure: VideoStructure, config: SummaryConfig = SummaryConfig()
    ) -> dict[str, Any]:
        """
        Generate a complete video summary from chapters.
        """
        # Build context from chapter summaries
        chapter_summaries = []
        all_themes = []

        for chapter in structure.chapters:
            if chapter.get("summary"):
                chapter_summaries.append(
                    f"- {chapter.get('title', 'Part')}: {chapter.get('summary')}"
                )
                all_themes.extend(chapter.get("themes", []))

        # Fallback to scene summaries if no chapter summaries
        if not chapter_summaries:
            for scene in structure.scenes[:10]:  # Limit to first 10 scenes
                if scene.summary:
                    chapter_summaries.append(f"- {scene.summary}")

        context = "\n".join(chapter_summaries)

        prompt = f"""Create a comprehensive summary for this video.

Total duration: {structure.total_duration:.1f} seconds ({structure.total_duration/60:.1f} minutes)
Number of scenes: {len(structure.scenes)}
Number of chapters: {len(structure.chapters)}

Chapter summaries:
{context}

Provide:
1. An executive summary (4-6 sentences) of the entire video
2. A descriptive title for the video
3. Key topics covered (up to 5)
4. Target audience or content type

Respond in JSON format:
{{
    "summary": "...",
    "title": "...",
    "key_topics": ["...", "..."],
    "content_type": "..."
}}"""

        try:
            response = self.client.chat.completions.create(
                model=self.deployment,
                messages=[
                    {
                        "role": "system",
                        "content": "You are a video content analyst creating executive summaries.",
                    },
                    {"role": "user", "content": prompt},
                ],
                max_completion_tokens=config.video_summary_max_tokens,
                temperature=1,
                response_format={"type": "json_object"},
            )

            result = json.loads(response.choices[0].message.content)
            return result

        except (APIError, APIConnectionError, RateLimitError) as e:
            logger.error(f"OpenAI API error in video summarization: {e}")
            return {
                "summary": f"Video with {len(structure.scenes)} scenes covering {structure.total_duration/60:.1f} minutes",
                "title": "Untitled Video",
                "key_topics": list(set(all_themes))[:5],
                "content_type": "unknown",
            }
        except json.JSONDecodeError as e:
            logger.error(f"JSON parsing error in video summarization: {e}")
            return {
                "summary": f"Video with {len(structure.scenes)} scenes covering {structure.total_duration/60:.1f} minutes",
                "title": "Untitled Video",
                "key_topics": list(set(all_themes))[:5],
                "content_type": "unknown",
            }

    async def generate_scene_embedding_text(self, scene: Scene) -> str:
        """
        Generate optimized text for scene embedding.

        This creates a rich text representation that captures
        the scene's content for vector search.
        """
        parts = []

        # Title and summary first (most important)
        if scene.title:
            parts.append(scene.title)

        if scene.summary:
            parts.append(scene.summary)

        # Visual description
        if scene.visual_description:
            parts.append(f"Visual: {scene.visual_description}")

        # Transcript
        if scene.transcript_segment:
            parts.append(f"Speech: {scene.transcript_segment}")

        # Objects as context
        if scene.detected_objects:
            parts.append(f"Contains: {', '.join(scene.detected_objects)}")

        # Temporal context
        parts.append(f"Timestamp: {scene.start_time:.1f}s to {scene.end_time:.1f}s")

        return " | ".join(parts)

    async def process_video_hierarchy(
        self,
        structure: VideoStructure,
        config: SummaryConfig = SummaryConfig(),
        generate_embeddings_callback=None,
    ) -> VideoStructure:
        """
        Complete hierarchical summarization pipeline.

        1. Summarize each scene
        2. Summarize each chapter
        3. Summarize the entire video
        4. Optionally generate scene-level embeddings

        Args:
            structure: VideoStructure with scenes and chapters
            config: Summarization configuration
            generate_embeddings_callback: Optional async function to generate embeddings

        Returns:
            Updated VideoStructure with summaries
        """
        logger.info(f"Starting hierarchical summarization for {len(structure.scenes)} scenes")

        # Step 1: Summarize scenes with bounded concurrency (TaskGroup).
        # Uses map_concurrent for proper cancellation: if the LLM API is
        # unreachable, remaining scenes are cancelled immediately instead
        # of wasting time on doomed requests.
        async def _summarize_one(scene: Scene) -> dict[str, Any]:
            return await self.summarize_scene(scene, config)

        try:
            scene_results: list[dict[str, Any]] = await map_concurrent(
                _summarize_one,
                structure.scenes,
                max_concurrency=5,
                task_name_prefix="scene-summarize",
            )
        except* (APIError, APIConnectionError, RateLimitError) as eg:
            logger.error(
                f"Scene summarization failed (API errors): " f"{[str(e) for e in eg.exceptions]}"
            )
            raise
        except* Exception as eg:
            logger.error(f"Scene summarization failed: " f"{[str(e) for e in eg.exceptions]}")
            raise

        for scene_idx, result in enumerate(scene_results):
            scene = structure.scenes[scene_idx]
            scene.summary = result.get("summary", "")
            scene.title = result.get("title", f"Scene {scene_idx + 1}")

            # Add key elements to detected objects
            key_elements = result.get("key_elements", [])
            if key_elements:
                existing = set(scene.detected_objects or [])
                scene.detected_objects = list(existing | set(key_elements))

        logger.info("Completed scene summarization")

        # Step 2: Summarize chapters
        for chapter in structure.chapters:
            result = await self.summarize_chapter(chapter, structure.scenes, config)
            chapter["summary"] = result.get("summary", "")
            chapter["title"] = result.get("title", f"Part {chapter['chapter_id'] + 1}")
            chapter["themes"] = result.get("themes", [])

        logger.info("Completed chapter summarization")

        # Step 3: Summarize entire video
        video_result = await self.summarize_video(structure, config)
        structure.video_summary = video_result.get("summary", "")
        structure.video_title = video_result.get("title", "Untitled")
        structure.key_topics = video_result.get("key_topics", [])

        logger.info("Completed video summarization")

        # Step 4: Generate scene embeddings if callback provided
        if generate_embeddings_callback:
            embedding_texts = [
                await self.generate_scene_embedding_text(scene) for scene in structure.scenes
            ]

            embeddings = await generate_embeddings_callback(embedding_texts)

            for i, embedding in enumerate(embeddings):
                if i < len(structure.scenes):
                    structure.scenes[i].embedding = embedding

            logger.info(f"Generated {len(embeddings)} scene embeddings")

        return structure
