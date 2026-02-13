"""
Structure Service

Business logic for video structure (scenes, chapters) generation.
Extracted from structure_routes.py to maintain proper layering.
"""

import json
import logging
import re

logger = logging.getLogger(__name__)


class StructureService:
    """Service for generating video structure from graph and legacy data."""

    def __init__(self, graph_service, blob_service=None, storage_container: str = ""):
        self.graph_service = graph_service
        self.blob_service = blob_service
        self.storage_container = storage_container

    def _generate_scene_title(self, scene: dict, scene_frames: list[dict]) -> str | None:
        """Generate a scene title from its first frame description."""
        title = scene.get("title")
        if title:
            return title

        if not scene_frames:
            return None

        first_desc = scene_frames[0].get("description", "")
        if not first_desc:
            return None

        clean_desc = re.sub(r"^\d+\.\s*\*?\*?", "", first_desc)
        clean_desc = clean_desc.replace("**", "")
        for skip in [
            "General scene description:",
            "General description:",
            "Scene description:",
            "Descripción general de la escena:",
            "Descripción general:",
        ]:
            clean_desc = clean_desc.replace(skip, "")
        clean_desc = clean_desc.strip()
        if clean_desc:
            first_sentence = clean_desc.split(".")[0][:100]
            return first_sentence.strip()
        return None

    def _generate_scene_summary(self, scene: dict, scene_frames: list[dict]) -> str | None:
        """Generate a scene summary from its frame descriptions."""
        summary = scene.get("description")
        if summary:
            return summary

        if not scene_frames:
            return None

        descriptions = [f.get("description", "") for f in scene_frames[:3] if f.get("description")]
        if descriptions:
            return " ".join(descriptions)[:500]
        return None

    def _build_chapters(
        self, scene_list: list[dict], max_scenes_per_chapter: int = 5
    ) -> list[dict]:
        """Group scenes into chapters."""
        chapters = []
        for i in range(0, len(scene_list), max_scenes_per_chapter):
            chunk = scene_list[i : i + max_scenes_per_chapter]
            if not chunk:
                continue
            chapter_id = len(chapters)

            first_scene_title = chunk[0].get("title", "")
            chapter_title = (
                first_scene_title[:60] if first_scene_title else f"Part {chapter_id + 1}"
            )

            scene_summaries = [s.get("summary", "") for s in chunk if s.get("summary")]
            chapter_summary = " ".join(scene_summaries)[:300] if scene_summaries else None

            chapters.append(
                {
                    "chapter_id": chapter_id,
                    "title": chapter_title,
                    "summary": chapter_summary,
                    "start_time": chunk[0]["start_time"],
                    "end_time": chunk[-1]["end_time"],
                    "duration": max(0.0, chunk[-1]["end_time"] - chunk[0]["start_time"]),
                    "scene_ids": [s["scene_id"] for s in chunk],
                    "scene_count": len(chunk),
                }
            )
        return chapters

    @staticmethod
    def _is_valid_content(desc: str) -> bool:
        """Check if a frame description contains meaningful content."""
        if not desc:
            return False
        desc_lower = desc.lower()
        skip_phrases = [
            "black screen",
            "completely black",
            "no visible",
            "no information",
            "imagen negra",
            "completamente negra",
            "no contiene elementos",
            "no hay información",
        ]
        return not any(phrase in desc_lower for phrase in skip_phrases)

    def _generate_video_summary(self, video_node: dict, all_frames: list[dict]) -> str | None:
        """Generate a video summary from frame descriptions."""
        video_summary = video_node.get("ai_summary")
        if video_summary:
            return video_summary

        valid_frames = [f for f in all_frames if self._is_valid_content(f.get("description", ""))]
        if not valid_frames:
            return None

        sample_count = min(5, len(valid_frames))
        step = max(1, len(valid_frames) // sample_count)
        sampled_frames = [valid_frames[i] for i in range(0, len(valid_frames), step)][:sample_count]

        summaries = []
        for f in sampled_frames:
            desc = f.get("description", "")
            clean = re.sub(r"^\d+\.\s*\*?\*?", "", desc)
            clean = clean.replace("**", "").replace("\n", " ")
            for prefix in [
                "General scene description:",
                "The image shows",
                "Descripción general de la escena:",
                "La imagen muestra",
            ]:
                if clean.startswith(prefix):
                    clean = clean[len(prefix) :].strip()
            if clean:
                summaries.append(clean[:150])

        return " ".join(summaries)[:600] if summaries else None

    def _extract_key_topics(self, video_node: dict, all_frames: list[dict]) -> list[str]:
        """Extract key topics from frame descriptions."""
        key_topics = video_node.get("topics") or []
        if key_topics:
            return key_topics

        if not all_frames:
            return []

        all_text = " ".join([f.get("description", "") for f in all_frames if f.get("description")])
        words = all_text.split()
        stop_words = {
            "the",
            "this",
            "that",
            "there",
            "here",
            "where",
            "what",
            "which",
            "when",
            "image",
            "video",
            "frame",
        }
        topic_candidates = [
            w.strip(".,!?:;()[]")
            for w in words
            if w and w[0].isupper() and len(w) > 3 and w.lower() not in stop_words
        ]

        seen = set()
        key_topics = []
        for t in topic_candidates:
            t_lower = t.lower()
            if t_lower not in seen and len(key_topics) < 10:
                seen.add(t_lower)
                key_topics.append(t)
        return key_topics

    def get_structure_from_graph(self, media_id: str) -> dict | None:
        """
        Build video structure from Neo4j graph data.

        Returns None if the video is not in the graph.
        """
        video_node = self.graph_service.get_video_node(media_id)
        if not video_node:
            return None

        scenes = self.graph_service.get_video_scenes(media_id)
        if not scenes:
            return None

        all_frames = self.graph_service.get_video_frames(media_id)

        # Build scene list
        scene_list = []
        for s in scenes:
            start = float(s.get("start_time", 0) or 0)
            end = float(s.get("end_time", 0) or 0)

            scene_frames = [
                f
                for f in all_frames
                if f.get("timestamp") is not None and start <= f["timestamp"] < end
            ]

            scene_title = self._generate_scene_title(s, scene_frames)
            scene_summary = self._generate_scene_summary(s, scene_frames)

            scene_list.append(
                {
                    "scene_id": int(s.get("scene_index", 0) or 0),
                    "start_time": start,
                    "end_time": end,
                    "duration": max(0.0, end - start),
                    "title": scene_title or f"Scene {int(s.get('scene_index', 0) or 0) + 1}",
                    "summary": scene_summary,
                    "detected_objects": s.get("detected_objects") or [],
                    "transcript_segment": s.get("transcript_segment"),
                    "frame_count": len(scene_frames),
                }
            )

        chapters = self._build_chapters(scene_list)
        video_summary = self._generate_video_summary(video_node, all_frames)
        key_topics = self._extract_key_topics(video_node, all_frames)

        return {
            "structure": {
                "scenes": scene_list,
                "chapters": chapters,
                "video_summary": video_summary,
                "video_title": video_node.get("title"),
                "key_topics": key_topics,
                "total_frames": len(all_frames),
            },
            "processing_method": "graph_scene_based",
            "processed_at": video_node.get("created_at"),
            "video_user_id": video_node.get("user_id"),
        }

    def get_structure_from_legacy(self, media_dict: dict) -> dict | None:
        """
        Build video structure from legacy PostgreSQL data.

        Returns None if no structure data is available.
        """
        legacy_structure = media_dict.get("structure") or (
            media_dict.get("processing_result") or {}
        ).get("structure")
        if legacy_structure:
            return {
                "structure": legacy_structure,
                "processing_method": media_dict.get("processing_method"),
                "processed_at": media_dict.get("last_updated"),
            }

        # Try loading from blob
        structure_blob = media_dict.get("structure_blob")
        if not structure_blob or not self.blob_service:
            return None

        blob_client = self.blob_service.get_blob_client(
            container=self.storage_container, blob=structure_blob
        )
        structure_json = blob_client.download_blob().readall()
        structure = json.loads(structure_json)

        return {
            "structure": structure,
            "processing_method": media_dict.get("processing_method"),
            "processed_at": media_dict.get("last_updated"),
        }
