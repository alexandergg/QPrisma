"""
Structure Routes

Handles video structure (scenes, chapters) endpoints.
Uses PostgreSQL for metadata storage (replaces Cosmos DB).
"""

import json
import logging
import os
import re

from fastapi import APIRouter, Depends, HTTPException

from api.dependencies import get_blob_service, get_current_user
from models.user import User
from services.database_service import get_database_service

router = APIRouter(tags=["Structure"])
logger = logging.getLogger(__name__)


# =============================================================================
# Routes
# =============================================================================


@router.get("/media/{media_id}/structure")
async def get_video_structure(media_id: str, current_user: User = Depends(get_current_user)):
    """
    Get the scene/chapter structure for a video.

    Returns hierarchical video structure with:
    - Scenes with summaries and timestamps
    - Chapters grouping related scenes
    - Video-level summary and key topics
    """
    db = get_database_service()
    blob_service = get_blob_service()

    # First, try Neo4j graph (primary source for structure)
    try:
        from services.knowledge_graph import get_knowledge_graph_service

        graph = get_knowledge_graph_service()
        video_node = graph.get_video_node(media_id)

        if video_node:
            # Video exists in Neo4j - verify ownership
            video_user_id = video_node.get("user_id")
            if video_user_id and video_user_id != current_user.id:
                raise HTTPException(status_code=403, detail="Access denied")

            scenes = graph.get_video_scenes(media_id)
            if scenes:
                # Build structure from Neo4j data
                all_frames = graph.get_video_frames(media_id)

                # Group frames by their timestamp ranges to match with scenes
                def get_frames_for_scene(scene_start: float, scene_end: float) -> list[dict]:
                    return [
                        f
                        for f in all_frames
                        if f.get("timestamp") is not None
                        and scene_start <= f["timestamp"] < scene_end
                    ]

                scene_list = []
                for s in scenes:
                    start = float(s.get("start_time", 0) or 0)
                    end = float(s.get("end_time", 0) or 0)

                    # Get frames in this scene
                    scene_frames = get_frames_for_scene(start, end)

                    # Generate scene title from first frame description
                    scene_title = s.get("title")
                    scene_summary = s.get("description")

                    if not scene_title and scene_frames:
                        # Use first frame's description to create a title
                        first_desc = scene_frames[0].get("description", "")
                        if first_desc:
                            # Clean up numbered list format and extract meaningful content
                            clean_desc = re.sub(r"^\d+\.\s*\*?\*?", "", first_desc)
                            clean_desc = clean_desc.replace("**", "")
                            for skip in [
                                "Descripción general de la escena:",
                                "Descripción general:",
                                "General description:",
                                "Scene description:",
                            ]:
                                clean_desc = clean_desc.replace(skip, "")
                            clean_desc = clean_desc.strip()
                            if clean_desc:
                                first_sentence = clean_desc.split(".")[0][:100]
                                scene_title = first_sentence.strip()

                    if not scene_summary and scene_frames:
                        # Combine frame descriptions for summary
                        descriptions = [
                            f.get("description", "")
                            for f in scene_frames[:3]
                            if f.get("description")
                        ]
                        if descriptions:
                            scene_summary = " ".join(descriptions)[:500]

                    scene_list.append(
                        {
                            "scene_id": int(s.get("scene_index", 0) or 0),
                            "start_time": start,
                            "end_time": end,
                            "duration": max(0.0, end - start),
                            "title": scene_title
                            or f"Scene {int(s.get('scene_index', 0) or 0) + 1}",
                            "summary": scene_summary,
                            "detected_objects": s.get("detected_objects") or [],
                            "transcript_segment": s.get("transcript_segment"),
                            "frame_count": len(scene_frames),
                        }
                    )

                # Generate chapters with descriptive titles based on scene content
                chapters = []
                max_chapter_scenes = 5
                for i in range(0, len(scene_list), max_chapter_scenes):
                    chunk = scene_list[i : i + max_chapter_scenes]
                    if not chunk:
                        continue
                    chapter_id = len(chapters)

                    # Generate chapter title from first scene's title
                    first_scene_title = chunk[0].get("title", "")
                    chapter_title = (
                        first_scene_title[:60] if first_scene_title else f"Part {chapter_id + 1}"
                    )

                    # Generate chapter summary from scene summaries
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

                # Generate video summary from all frame descriptions if not available
                video_summary = video_node.get("ai_summary")
                if not video_summary and all_frames:
                    # Filter out black screen descriptions and take diverse frames
                    def is_valid_content(desc: str) -> bool:
                        if not desc:
                            return False
                        desc_lower = desc.lower()
                        skip_phrases = [
                            "imagen negra",
                            "completamente negra",
                            "no contiene elementos",
                            "black screen",
                            "completely black",
                            "no visible",
                            "no hay información",
                        ]
                        return not any(phrase in desc_lower for phrase in skip_phrases)

                    valid_frames = [
                        f for f in all_frames if is_valid_content(f.get("description", ""))
                    ]

                    if valid_frames:
                        # Take frames distributed across the video for better coverage
                        sample_count = min(5, len(valid_frames))
                        step = max(1, len(valid_frames) // sample_count)
                        sampled_frames = [
                            valid_frames[i] for i in range(0, len(valid_frames), step)
                        ][:sample_count]

                        # Clean up descriptions for summary
                        summaries = []
                        for f in sampled_frames:
                            desc = f.get("description", "")
                            clean = re.sub(r"^\d+\.\s*\*?\*?", "", desc)
                            clean = clean.replace("**", "").replace("\n", " ")
                            for prefix in [
                                "Descripción general de la escena:",
                                "La imagen muestra",
                            ]:
                                if clean.startswith(prefix):
                                    clean = clean[len(prefix) :].strip()
                            if clean:
                                summaries.append(clean[:150])

                        video_summary = " ".join(summaries)[:600] if summaries else None

                # Extract key topics from frame descriptions
                key_topics = video_node.get("topics") or []
                if not key_topics and all_frames:
                    all_text = " ".join(
                        [f.get("description", "") for f in all_frames if f.get("description")]
                    )
                    words = all_text.split()
                    topic_candidates = [
                        w.strip(".,!?:;()[]")
                        for w in words
                        if w
                        and w[0].isupper()
                        and len(w) > 3
                        and w.lower()
                        not in {
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
                    ]
                    # Get unique topics
                    seen = set()
                    key_topics = []
                    for t in topic_candidates:
                        t_lower = t.lower()
                        if t_lower not in seen and len(key_topics) < 10:
                            seen.add(t_lower)
                            key_topics.append(t)

                structure = {
                    "scenes": scene_list,
                    "chapters": chapters,
                    "video_summary": video_summary,
                    "video_title": video_node.get("title"),
                    "key_topics": key_topics,
                    "total_frames": len(all_frames),
                }

                return {
                    "media_id": media_id,
                    "structure": structure,
                    "processing_method": "graph_scene_based",
                    "processed_at": video_node.get("created_at"),
                }

    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"Graph structure not available, falling back to PostgreSQL: {e}")

    # Fallback to PostgreSQL for legacy data
    try:
        media = db.get_media(media_id)
        if not media:
            raise HTTPException(status_code=404, detail="Media not found")

        if media.user_id != current_user.id:
            raise HTTPException(status_code=403, detail="Access denied")

        item = media.to_dict()

        # Legacy structure (stored inline in PostgreSQL as JSON)
        legacy_structure = (
            item.get("structure")
            or (item.get("processing_result") or {}).get("structure")
        )
        if legacy_structure:
            return {
                "media_id": media_id,
                "structure": legacy_structure,
                "processing_method": item.get("processing_method"),
                "processed_at": item.get("last_updated"),
            }

        # Check if blob structure exists (legacy)
        structure_blob = item.get("structure_blob")
        if not structure_blob:
            raise HTTPException(status_code=404, detail="Video structure not available yet.")

        # Load structure from blob
        storage_container = os.getenv("AZURE_STORAGE_CONTAINER_NAME", "media")
        blob_client = blob_service.get_blob_client(container=storage_container, blob=structure_blob)

        structure_json = blob_client.download_blob().readall()
        structure = json.loads(structure_json)

        return {
            "media_id": media_id,
            "structure": structure,
            "processing_method": item.get("processing_method"),
            "processed_at": item.get("last_updated"),
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")
