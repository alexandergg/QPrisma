"""
Auto-Clip Tools
================

Tools for AI-powered automatic clip generation.
These tools analyze the video content and suggest viral-worthy clips.
"""

import logging
from typing import Any

from agent.tools.base import BaseTool, ToolParameter, format_timestamp
from api.dependencies import get_graph_search_service
from models.graph_models import NodeType
from services.database_service import get_database_service
from services.viral_score_service import get_viral_score_service, TranscriptSegment

logger = logging.getLogger(__name__)


class GenerateAutoClipsTool(BaseTool):
    """
    Generate AI-suggested clips based on content analysis.

    Analyzes the video to find moments that are:
    - High energy (audio analysis)
    - Good hooks (strong opening statements)
    - Complete ideas (standalone content)
    - Visually engaging (scene changes, faces)
    """

    name = "generate_auto_clips"
    description = (
        "Automatically find and suggest the best moments for clips based on AI analysis. "
        "Use this when the user asks for 'viral clips', 'best moments', 'auto-generate clips', "
        "'find highlights', or 'suggest clips for TikTok/Reels'."
    )
    parameters = [
        ToolParameter(
            name="max_clips",
            type="integer",
            description="Maximum number of clips to suggest (default: 5, max: 10)",
            required=False,
            default=5,
        ),
        ToolParameter(
            name="min_duration",
            type="number",
            description="Minimum clip duration in seconds (default: 15)",
            required=False,
            default=15,
        ),
        ToolParameter(
            name="max_duration",
            type="number",
            description="Maximum clip duration in seconds (default: 60)",
            required=False,
            default=60,
        ),
        ToolParameter(
            name="focus",
            type="string",
            description="What to focus on: 'hooks' for strong openings, 'energy' for exciting moments, 'topics' for complete ideas, 'all' for balanced",
            required=False,
            enum=["all", "hooks", "energy", "topics"],
            default="all",
        ),
    ]

    async def execute(
        self,
        media_id: str | None,
        max_clips: int = 5,
        min_duration: float = 15,
        max_duration: float = 60,
        focus: str = "all",
        project_id: str | None = None,
        **kwargs,
    ) -> dict[str, Any]:
        """Generate auto-clip suggestions."""
        if not media_id:
            return {
                "error": "No video context available. Please select a video first.",
                "suggestions": [],
            }

        max_clips = min(max_clips, 10)  # Cap at 10

        try:
            db = get_database_service()
            search_service = get_graph_search_service()

            # Get video metadata
            media = db.get_media(media_id)
            if not media:
                return {"error": "Video not found.", "suggestions": []}

            video_duration = 0
            if media.video_metadata:
                video_duration = media.video_metadata.get("duration", 0)

            # Ensure graph connection
            if not search_service.graph_service.is_connected:
                search_service.graph_service.connect()

            suggestions = []

            # Strategy 1: Find high-scoring audio segments (hooks and key statements)
            hook_queries = [
                "important point key insight",
                "surprising revelation",
                "strong statement opinion",
                "call to action",
                "question hook",
            ]

            for query in hook_queries:
                try:
                    response = search_service.hybrid_search(
                        query_text=query,
                        node_types=[NodeType.AUDIO_SEGMENT],
                        video_id=media_id,
                        limit=max_clips * 2,
                        use_reranking=True,
                    )

                    for result in response.results:
                        ts = result.content.get("timestamp", 0)
                        text = result.content.get("text", "")

                        if not text or len(text) < 20:
                            continue

                        # Calculate suggested clip boundaries
                        start_time = max(0, ts - 2)  # Start 2 seconds before
                        end_time = min(
                            video_duration if video_duration > 0 else ts + max_duration,
                            ts + max_duration
                        )

                        # Adjust to target duration
                        duration = end_time - start_time
                        if duration < min_duration:
                            end_time = start_time + min_duration
                        elif duration > max_duration:
                            end_time = start_time + max_duration

                        # Calculate viral score based on multiple factors
                        viral_score = self._calculate_viral_score(
                            text=text,
                            search_score=result.combined_score,
                            focus=focus,
                            start_time=start_time,
                            end_time=end_time,
                        )

                        # Extract hook (first words)
                        words = text.split()
                        hook_text = " ".join(words[:8]) + "..." if len(words) > 8 else text

                        suggestions.append({
                            "start_time": round(start_time, 1),
                            "end_time": round(end_time, 1),
                            "start_formatted": format_timestamp(start_time),
                            "end_formatted": format_timestamp(end_time),
                            "duration": round(end_time - start_time, 1),
                            "viral_score": viral_score,
                            "hook_text": hook_text,
                            "transcript_snippet": text[:200],
                            "viral_reasons": self._get_viral_reasons(text, viral_score),
                        })

                except Exception as e:
                    logger.warning(f"Search query failed: {e}")
                    continue

            # Strategy 2: Find visually interesting scenes
            try:
                visual_response = search_service.hybrid_search(
                    query_text="interesting dynamic engaging scene action",
                    node_types=[NodeType.FRAME, NodeType.SCENE],
                    video_id=media_id,
                    limit=max_clips,
                    use_reranking=True,
                )

                for result in visual_response.results:
                    ts = result.content.get("timestamp", 0)
                    description = result.content.get("description", "")

                    start_time = max(0, ts - 5)
                    end_time = min(
                        video_duration if video_duration > 0 else ts + 30,
                        ts + 30
                    )

                    viral_score = min(95, int(result.combined_score * 100) + 10)

                    suggestions.append({
                        "start_time": round(start_time, 1),
                        "end_time": round(end_time, 1),
                        "start_formatted": format_timestamp(start_time),
                        "end_formatted": format_timestamp(end_time),
                        "duration": round(end_time - start_time, 1),
                        "viral_score": viral_score,
                        "hook_text": f"[Visual] {description[:50]}...",
                        "transcript_snippet": description[:200],
                        "viral_reasons": ["visual_interest", "scene_change"],
                    })

            except Exception as e:
                logger.warning(f"Visual search failed: {e}")

            # Remove duplicates (overlapping time ranges)
            suggestions = self._remove_overlapping(suggestions)

            # Sort by viral score
            suggestions.sort(key=lambda x: x["viral_score"], reverse=True)

            # Take top suggestions
            top_suggestions = suggestions[:max_clips]

            return {
                "total_found": len(suggestions),
                "suggestions": top_suggestions,
                "message": f"Found {len(top_suggestions)} potential clips ranked by viral score.",
                "tip": "Use 'create_clip' to add any of these to your project.",
            }

        except Exception as e:
            logger.error(f"Auto-clip generation error: {e}")
            return {"error": f"Failed to generate clips: {str(e)}", "suggestions": []}

    def _calculate_viral_score(
        self,
        text: str,
        search_score: float,
        focus: str,
        start_time: float = 0,
        end_time: float = 30,
    ) -> int:
        """Calculate viral score using the ViralScoreService."""
        try:
            viral_service = get_viral_score_service()
            
            # Create a transcript segment for analysis
            segment = TranscriptSegment(
                start_time=start_time,
                end_time=end_time,
                text=text,
                words=[],
            )
            
            # Get detailed viral analysis
            result = viral_service.calculate_viral_score(segment)
            
            # Adjust based on search relevance
            adjusted_score = result.score * 0.7 + (search_score * 100) * 0.3
            
            # Apply focus bonus
            if focus == "hooks" and result.components.get("hook", 0) > 60:
                adjusted_score += 10
            elif focus == "energy" and result.components.get("pacing", 0) > 60:
                adjusted_score += 10
            elif focus == "topics" and result.components.get("topic", 0) > 60:
                adjusted_score += 10
            
            return min(99, max(1, int(adjusted_score)))
            
        except Exception as e:
            logger.warning(f"Viral score calculation fallback: {e}")
            # Fallback to simple calculation
            return self._calculate_viral_score_simple(text, search_score, focus)

    def _calculate_viral_score_simple(
        self,
        text: str,
        search_score: float,
        focus: str,
    ) -> int:
        """Simple viral score calculation as fallback."""
        score = int(search_score * 60)
        text_lower = text.lower()

        hook_words = ["secret", "truth", "mistake", "never", "always", "best", "worst", 
                      "how to", "why", "what if", "imagine", "here's", "this is"]
        for word in hook_words:
            if word in text_lower:
                score += 5
                if focus == "hooks":
                    score += 10

        energy_indicators = ["!", "?", "amazing", "incredible", "crazy", "insane"]
        for indicator in energy_indicators:
            if indicator in text_lower:
                score += 3
                if focus == "energy":
                    score += 7

        if text_lower.endswith((".", "!", "?")):
            score += 5
            if focus == "topics":
                score += 10

        word_count = len(text.split())
        if 15 <= word_count <= 50:
            score += 10

        return min(99, max(1, score))

    def _get_viral_reasons(self, text: str, score: int) -> list[str]:
        """Get reasons why this clip might be viral."""
        reasons = []
        text_lower = text.lower()

        if any(w in text_lower for w in ["secret", "truth", "never", "always"]):
            reasons.append("strong_hook")
        if any(w in text_lower for w in ["!", "amazing", "incredible"]):
            reasons.append("high_energy")
        if any(w in text_lower for w in ["how to", "here's", "this is"]):
            reasons.append("educational")
        if "?" in text:
            reasons.append("engaging_question")
        if score >= 80:
            reasons.append("high_relevance")

        return reasons if reasons else ["content_match"]

    def _remove_overlapping(
        self,
        suggestions: list[dict],
        overlap_threshold: float = 10.0,
    ) -> list[dict]:
        """Remove suggestions that overlap too much."""
        if not suggestions:
            return []

        # Sort by start time
        sorted_suggestions = sorted(suggestions, key=lambda x: x["start_time"])
        filtered = [sorted_suggestions[0]]

        for suggestion in sorted_suggestions[1:]:
            last = filtered[-1]
            # Check if there's significant overlap
            overlap_start = max(last["start_time"], suggestion["start_time"])
            overlap_end = min(last["end_time"], suggestion["end_time"])
            overlap = max(0, overlap_end - overlap_start)

            if overlap < overlap_threshold:
                filtered.append(suggestion)
            elif suggestion["viral_score"] > last["viral_score"]:
                # Replace with higher scored one
                filtered[-1] = suggestion

        return filtered


class AddSuggestedClipsTool(BaseTool):
    """
    Add AI-suggested clips to the project.
    """

    name = "add_suggested_clips"
    description = (
        "Add one or more AI-suggested clips to the current project. "
        "Use after 'generate_auto_clips' when the user approves suggestions. "
        "Can add specific clips by index or all of them."
    )
    parameters = [
        ToolParameter(
            name="suggestion_indices",
            type="string",
            description="Comma-separated indices of suggestions to add (e.g., '1,3,5') or 'all' for all",
            required=True,
        ),
        ToolParameter(
            name="suggestions_data",
            type="string",
            description="JSON string of the suggestions array from generate_auto_clips",
            required=True,
        ),
    ]

    async def execute(
        self,
        media_id: str | None,
        suggestion_indices: str,
        suggestions_data: str,
        project_id: str | None = None,
        **kwargs,
    ) -> dict[str, Any]:
        """Add suggested clips to the project."""
        import json

        if not project_id:
            return {
                "error": "No project context. Please create or select a project first.",
                "success": False,
            }

        try:
            db = get_database_service()

            # Parse suggestions
            try:
                suggestions = json.loads(suggestions_data)
            except json.JSONDecodeError:
                return {"error": "Invalid suggestions data.", "success": False}

            if not suggestions:
                return {"error": "No suggestions provided.", "success": False}

            # Determine which to add
            if suggestion_indices.lower() == "all":
                indices = list(range(len(suggestions)))
            else:
                try:
                    indices = [int(i.strip()) - 1 for i in suggestion_indices.split(",")]
                except ValueError:
                    return {"error": "Invalid indices format.", "success": False}

            # Validate indices
            valid_indices = [i for i in indices if 0 <= i < len(suggestions)]
            if not valid_indices:
                return {"error": "No valid suggestion indices.", "success": False}

            # Create clips
            clips_data = []
            for idx in valid_indices:
                suggestion = suggestions[idx]
                clips_data.append({
                    "start_time": suggestion["start_time"],
                    "end_time": suggestion["end_time"],
                    "title": suggestion.get("hook_text", f"Auto-clip {idx + 1}"),
                    "is_ai_suggested": True,
                    "viral_score": suggestion.get("viral_score"),
                    "viral_reasons": suggestion.get("viral_reasons"),
                    "transcript_snippet": suggestion.get("transcript_snippet"),
                })

            created_clips = db.bulk_create_clips(project_id, clips_data)

            return {
                "success": True,
                "message": f"Added {len(created_clips)} clips to your project.",
                "clips": [
                    {
                        "id": clip.id,
                        "title": clip.title,
                        "range": f"{format_timestamp(clip.start_time)} - {format_timestamp(clip.end_time)}",
                        "viral_score": clip.viral_score,
                    }
                    for clip in created_clips
                ],
            }

        except Exception as e:
            logger.error(f"Add suggested clips error: {e}")
            return {"error": f"Failed to add clips: {str(e)}", "success": False}


# Tool instances
generate_auto_clips = GenerateAutoClipsTool()
add_suggested_clips = AddSuggestedClipsTool()
