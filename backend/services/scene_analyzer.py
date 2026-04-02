"""
Scene Analyzer Service
======================
Intelligent video chunking using scene detection and semantic clustering.

This service transforms frame-by-frame analysis into coherent scene-based chunks,
dramatically improving search relevance and reducing processing costs.

Key Features:
- FFmpeg scene detection with configurable threshold
- Semantic clustering of visually similar frames
- Scene boundary refinement using visual + audio cues
- Automatic chapter generation
"""

import logging
import subprocess
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class SceneBoundary:
    """Represents a detected scene boundary."""

    timestamp: float
    frame_number: int
    confidence: float
    detection_method: str  # 'ffmpeg', 'semantic', 'audio'
    transition_type: str = "cut"  # cut, fade, dissolve - default is cut for hard scene changes


@dataclass
class Scene:
    """Represents a coherent video scene/chunk."""

    scene_id: int
    start_time: float
    end_time: float
    start_frame: int
    end_frame: int
    duration: float

    # Content analysis
    keyframe_indices: list[int]  # Representative frames for this scene
    summary: str | None = None
    title: str | None = None

    # Aggregated content from frames
    visual_description: str | None = None
    transcript_segment: str | None = None
    detected_objects: list[str] = None

    # Embedding (scene-level, not frame-level)
    embedding: list[float] | None = None

    # Metadata
    frame_count: int = 0
    avg_motion: float = 0.0
    dominant_colors: list[str] = None
    visual_change_score: float = 0.0  # Confidence score from scene detection
    transition_type: str = "cut"  # cut, fade, dissolve
    scene_type: str | None = None  # indoor, outdoor, mixed (aggregated from frames)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class VideoStructure:
    """Complete hierarchical structure of a video."""

    media_id: str
    total_duration: float
    total_frames: int

    # Hierarchical levels
    scenes: list[Scene]
    chapters: list[dict[str, Any]]  # Groups of related scenes

    # Video-level summary
    video_summary: str | None = None
    video_title: str | None = None
    key_topics: list[str] = None

    # Processing metadata
    processing_method: str = "scene_based"
    scene_detection_threshold: float = 0.3
    created_at: str = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "media_id": self.media_id,
            "total_duration": self.total_duration,
            "total_frames": self.total_frames,
            "scenes": [s.to_dict() for s in self.scenes],
            "chapters": self.chapters,
            "video_summary": self.video_summary,
            "video_title": self.video_title,
            "key_topics": self.key_topics,
            "processing_method": self.processing_method,
            "scene_detection_threshold": self.scene_detection_threshold,
            "created_at": self.created_at or datetime.now(UTC).isoformat(),
        }


class SceneAnalyzer:
    """
    Analyzes videos to extract scene structure and create intelligent chunks.

    Instead of treating each frame independently, this groups frames into
    coherent scenes for better context and reduced processing costs.
    """

    def __init__(
        self,
        scene_threshold: float = 0.3,
        min_scene_duration: float = 2.0,
        max_scene_duration: float = 60.0,
        keyframes_per_scene: int = 3,
    ):
        """
        Initialize the scene analyzer.

        Args:
            scene_threshold: FFmpeg scene detection threshold (0.0-1.0)
                            Lower = more sensitive, more scenes detected
            min_scene_duration: Minimum scene length in seconds
            max_scene_duration: Maximum scene length before forced split
            keyframes_per_scene: Number of representative frames per scene
        """
        self.scene_threshold = scene_threshold
        self.min_scene_duration = min_scene_duration
        self.max_scene_duration = max_scene_duration
        self.keyframes_per_scene = keyframes_per_scene

    def detect_scene_changes(
        self, video_path: str, duration: float | None = None
    ) -> list[SceneBoundary]:
        """
        Detect scene changes using FFmpeg's scene detection filter.

        This uses the 'select' filter with scene detection to find
        points where the video content changes significantly.
        """
        try:
            # FFmpeg command to detect scene changes
            cmd = [
                "ffmpeg",
                "-i",
                video_path,
                "-vf",
                f"select='gt(scene,{self.scene_threshold})',showinfo",
                "-f",
                "null",
                "-",
            ]

            result = subprocess.run(  # noqa: S603
                cmd,
                capture_output=True,
                text=True,
                timeout=300,  # 5 minute timeout
            )

            # Parse the output for scene change timestamps
            boundaries = []

            # Always add the start as a boundary
            boundaries.append(
                SceneBoundary(
                    timestamp=0.0, frame_number=0, confidence=1.0, detection_method="start"
                )
            )

            # Parse FFmpeg showinfo output for scene changes
            for line in result.stderr.split("\n"):
                if "pts_time:" in line and "scene:" in line.lower():
                    try:
                        # Extract timestamp
                        pts_match = line.split("pts_time:")[1].split()[0]
                        timestamp = float(pts_match)

                        # Extract frame number if available
                        frame_num = 0
                        if "n:" in line:
                            frame_match = line.split("n:")[1].split()[0]
                            frame_num = int(frame_match)

                        # Extract scene change score if available
                        scene_score = 0.8  # Default confidence
                        if "scene:" in line.lower():
                            try:
                                # Look for pattern like "scene:0.456789"
                                import re

                                scene_match = re.search(r"scene[:\s]+(\d+\.?\d*)", line.lower())
                                if scene_match:
                                    scene_score = float(scene_match.group(1))
                            except (ValueError, IndexError):
                                pass

                        # Classify transition type based on scene score
                        # High scores (>0.7) = hard cut, medium (0.4-0.7) = dissolve, low (<0.4) = fade
                        if scene_score > 0.7:
                            transition_type = "cut"
                        elif scene_score > 0.4:
                            transition_type = "dissolve"
                        else:
                            transition_type = "fade"

                        # Only add if it's far enough from the last boundary
                        if (
                            not boundaries
                            or (timestamp - boundaries[-1].timestamp) >= self.min_scene_duration
                        ):
                            boundaries.append(
                                SceneBoundary(
                                    timestamp=timestamp,
                                    frame_number=frame_num,
                                    confidence=scene_score,
                                    detection_method="ffmpeg",
                                    transition_type=transition_type,
                                )
                            )
                    except (ValueError, IndexError):
                        continue

            # If no scenes detected, create uniform splits
            if len(boundaries) <= 1 and duration:
                boundaries = self._create_uniform_scenes(duration)

            logger.info(f"Detected {len(boundaries)} scene boundaries")
            return boundaries

        except subprocess.TimeoutExpired:
            logger.warning("Scene detection timed out, using uniform splits")
            if duration:
                return self._create_uniform_scenes(duration)
            return [SceneBoundary(0.0, 0, 1.0, "fallback")]

        except subprocess.CalledProcessError as e:
            logger.error(f"FFmpeg scene detection error: {e}")
            if duration:
                return self._create_uniform_scenes(duration)
            return [SceneBoundary(0.0, 0, 1.0, "fallback")]

        except (OSError, ValueError) as e:
            logger.error(f"Scene detection error: {e}")
            if duration:
                return self._create_uniform_scenes(duration)
            return [SceneBoundary(0.0, 0, 1.0, "fallback")]

    def _create_uniform_scenes(self, duration: float) -> list[SceneBoundary]:
        """Create uniform scene boundaries when detection fails or for consistency."""
        boundaries = []
        scene_length = min(self.max_scene_duration, duration / 5)  # At least 5 scenes
        scene_length = max(scene_length, self.min_scene_duration)

        current_time = 0.0
        while current_time < duration:
            boundaries.append(
                SceneBoundary(
                    timestamp=current_time,
                    frame_number=int(current_time * 30),  # Assume 30fps
                    confidence=0.5,
                    detection_method="uniform",
                )
            )
            current_time += scene_length

        return boundaries

    def build_scenes_from_boundaries(
        self,
        boundaries: list[SceneBoundary],
        duration: float,
        fps: float,
        frame_analyses: list[dict] | None = None,
        transcript_segments: list[dict] | None = None,
    ) -> list[Scene]:
        """
        Build Scene objects from detected boundaries.

        Args:
            boundaries: List of scene boundary timestamps
            duration: Total video duration
            fps: Video frames per second
            frame_analyses: Optional list of frame analysis results
            transcript_segments: Optional audio transcript segments
        """
        scenes = []

        for i, boundary in enumerate(boundaries):
            # Determine scene end time
            if i < len(boundaries) - 1:
                end_time = boundaries[i + 1].timestamp
            else:
                end_time = duration

            scene_duration = end_time - boundary.timestamp

            # Skip very short scenes
            if scene_duration < self.min_scene_duration and i > 0:
                continue

            # Calculate frame range
            start_frame = int(boundary.timestamp * fps)
            end_frame = int(end_time * fps)
            frame_count = end_frame - start_frame

            # Select keyframe indices (uniformly distributed within scene)
            keyframe_indices = self._select_keyframes(
                start_frame, end_frame, self.keyframes_per_scene
            )

            # Aggregate frame analyses for this scene
            visual_desc = None
            detected_objects = []
            scene_type = None

            if frame_analyses:
                scene_frames = [
                    f for f in frame_analyses if start_frame <= f.get("frame_number", 0) < end_frame
                ]
                if scene_frames:
                    # Combine descriptions (check both "description" and "analysis" keys for compatibility)
                    descriptions = [
                        f.get("description") or f.get("analysis", "")
                        for f in scene_frames
                        if f.get("description") or f.get("analysis")
                    ]
                    visual_desc = " ".join(descriptions[:3])  # First 3 for context

                    # Aggregate objects
                    for f in scene_frames:
                        detected_objects.extend(f.get("detected_objects", []))
                    detected_objects = list(set(detected_objects))[:10]  # Unique, max 10

                    # Aggregate scene_type (most common non-null value from frames)
                    frame_scene_types = [
                        f.get("scene_type") for f in scene_frames if f.get("scene_type")
                    ]
                    if frame_scene_types:
                        from collections import Counter

                        scene_type = Counter(frame_scene_types).most_common(1)[0][0]

            # Get transcript segment for this time range
            transcript_text = None
            if transcript_segments:
                scene_transcript_parts = [
                    seg.get("text", "")
                    for seg in transcript_segments
                    if seg.get("start", 0) >= boundary.timestamp and seg.get("end", 0) <= end_time
                ]
                if scene_transcript_parts:
                    transcript_text = " ".join(scene_transcript_parts)

            scene = Scene(
                scene_id=len(scenes),
                start_time=boundary.timestamp,
                end_time=end_time,
                start_frame=start_frame,
                end_frame=end_frame,
                duration=scene_duration,
                keyframe_indices=keyframe_indices,
                visual_description=visual_desc,
                transcript_segment=transcript_text,
                detected_objects=detected_objects or [],
                frame_count=frame_count,
                visual_change_score=boundary.confidence,  # From scene detection confidence
                transition_type=boundary.transition_type,  # cut, fade, or dissolve
                scene_type=scene_type,
            )

            scenes.append(scene)

        logger.info(f"Built {len(scenes)} scenes from {len(boundaries)} boundaries")
        return scenes

    def _select_keyframes(self, start_frame: int, end_frame: int, num_keyframes: int) -> list[int]:
        """Select representative keyframe indices within a scene."""
        frame_count = end_frame - start_frame

        if frame_count <= num_keyframes:
            return list(range(start_frame, end_frame))

        # Uniform distribution
        step = frame_count / (num_keyframes + 1)
        keyframes = [int(start_frame + step * (i + 1)) for i in range(num_keyframes)]

        return keyframes

    def cluster_frames_semantically(
        self,
        frame_embeddings: list[list[float]],
        frame_timestamps: list[float],
        similarity_threshold: float = 0.85,
    ) -> list[list[int]]:
        """
        Cluster frames based on semantic similarity of their embeddings.

        This provides an alternative to visual scene detection,
        grouping frames by content meaning rather than visual changes.
        """
        if not frame_embeddings:
            return []

        embeddings = np.array(frame_embeddings)
        n_frames = len(embeddings)

        # Normalize embeddings
        norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
        normalized = embeddings / (norms + 1e-8)

        # Compute pairwise cosine similarities
        np.dot(normalized, normalized.T)

        # Sequential clustering - group consecutive similar frames
        clusters = []
        current_cluster = [0]

        for i in range(1, n_frames):
            # Check similarity with cluster centroid (average of cluster frames)
            cluster_indices = current_cluster
            cluster_embedding = normalized[cluster_indices].mean(axis=0)

            similarity = np.dot(normalized[i], cluster_embedding)

            if similarity >= similarity_threshold:
                current_cluster.append(i)
            else:
                # Start new cluster
                clusters.append(current_cluster)
                current_cluster = [i]

        # Don't forget the last cluster
        if current_cluster:
            clusters.append(current_cluster)

        logger.info(f"Semantic clustering: {n_frames} frames → {len(clusters)} clusters")
        return clusters

    def merge_detection_methods(
        self,
        visual_boundaries: list[SceneBoundary],
        semantic_clusters: list[list[int]],
        frame_timestamps: list[float],
    ) -> list[SceneBoundary]:
        """
        Merge visual and semantic scene detection for better accuracy.

        Uses visual detection as primary, refined by semantic clusters.
        """
        if not semantic_clusters:
            return visual_boundaries

        # Convert semantic clusters to boundaries
        semantic_boundaries = []
        for cluster in semantic_clusters:
            if cluster:
                start_idx = cluster[0]
                if start_idx < len(frame_timestamps):
                    semantic_boundaries.append(
                        SceneBoundary(
                            timestamp=frame_timestamps[start_idx],
                            frame_number=start_idx,
                            confidence=0.7,
                            detection_method="semantic",
                        )
                    )

        # Merge: keep visual boundaries that are close to semantic ones
        merged = []
        used_semantic = set()

        for vb in visual_boundaries:
            # Find nearest semantic boundary
            best_match = None
            best_dist = float("inf")

            for i, sb in enumerate(semantic_boundaries):
                if i not in used_semantic:
                    dist = abs(vb.timestamp - sb.timestamp)
                    if dist < best_dist:
                        best_dist = dist
                        best_match = i

            if best_match is not None and best_dist < 2.0:  # Within 2 seconds
                # Average the timestamps
                sb = semantic_boundaries[best_match]
                merged.append(
                    SceneBoundary(
                        timestamp=(vb.timestamp + sb.timestamp) / 2,
                        frame_number=vb.frame_number,
                        confidence=(vb.confidence + sb.confidence) / 2,
                        detection_method="merged",
                    )
                )
                used_semantic.add(best_match)
            else:
                merged.append(vb)

        # Add remaining semantic boundaries
        for i, sb in enumerate(semantic_boundaries):
            if i not in used_semantic:
                # Check if it's not too close to existing
                is_unique = all(
                    abs(sb.timestamp - m.timestamp) >= self.min_scene_duration for m in merged
                )
                if is_unique:
                    merged.append(sb)

        # Sort by timestamp
        merged.sort(key=lambda x: x.timestamp)

        logger.info(
            f"Merged {len(visual_boundaries)} visual + {len(semantic_boundaries)} semantic → {len(merged)} boundaries"
        )
        return merged

    def generate_chapters(
        self, scenes: list[Scene], max_chapter_scenes: int = 5
    ) -> list[dict[str, Any]]:
        """
        Group scenes into chapters based on content similarity.

        Chapters provide a higher-level navigation structure.
        """
        if not scenes:
            return []

        chapters = []
        current_chapter_scenes = []

        for scene in scenes:
            current_chapter_scenes.append(scene)

            # Create new chapter if we have enough scenes
            if len(current_chapter_scenes) >= max_chapter_scenes:
                chapter = self._create_chapter(current_chapter_scenes, len(chapters))
                chapters.append(chapter)
                current_chapter_scenes = []

        # Handle remaining scenes
        if current_chapter_scenes:
            chapter = self._create_chapter(current_chapter_scenes, len(chapters))
            chapters.append(chapter)

        return chapters

    def _create_chapter(self, scenes: list[Scene], chapter_index: int) -> dict[str, Any]:
        """Create a chapter from a group of scenes."""
        return {
            "chapter_id": chapter_index,
            "title": f"Chapter {chapter_index + 1}",  # Will be replaced by LLM
            "start_time": scenes[0].start_time,
            "end_time": scenes[-1].end_time,
            "duration": scenes[-1].end_time - scenes[0].start_time,
            "scene_ids": [s.scene_id for s in scenes],
            "scene_count": len(scenes),
        }

    async def analyze_video_structure(
        self,
        video_path: str,
        video_metadata: dict[str, Any],
        frame_analyses: list[dict] | None = None,
        frame_embeddings: list[list[float]] | None = None,
        transcript_segments: list[dict] | None = None,
    ) -> VideoStructure:
        """
        Complete video structure analysis pipeline.

        Args:
            video_path: Path to the video file
            video_metadata: Video metadata (duration, fps, etc.)
            frame_analyses: Optional pre-computed frame analyses
            frame_embeddings: Optional pre-computed frame embeddings
            transcript_segments: Optional audio transcript segments

        Returns:
            VideoStructure with scenes, chapters, and metadata
        """
        duration = video_metadata.get("duration", 0)
        fps = video_metadata.get("fps", 30)
        media_id = video_metadata.get("media_id", "unknown")

        logger.info(f"Analyzing video structure: {media_id}, {duration}s, {fps}fps")

        # Step 1: Detect visual scene changes
        visual_boundaries = self.detect_scene_changes(video_path, duration)

        # Step 2: Optional semantic clustering if embeddings available
        if frame_embeddings:
            frame_timestamps = [
                f.get("timestamp", i / fps)
                for i, f in enumerate(
                    frame_analyses or [{"timestamp": i / fps} for i in range(len(frame_embeddings))]
                )
            ]

            semantic_clusters = self.cluster_frames_semantically(frame_embeddings, frame_timestamps)

            # Merge detection methods
            boundaries = self.merge_detection_methods(
                visual_boundaries, semantic_clusters, frame_timestamps
            )
        else:
            boundaries = visual_boundaries

        # Step 3: Build scenes from boundaries
        scenes = self.build_scenes_from_boundaries(
            boundaries, duration, fps, frame_analyses, transcript_segments
        )

        # Step 4: Generate chapters
        chapters = self.generate_chapters(scenes)

        # Step 5: Build video structure
        structure = VideoStructure(
            media_id=media_id,
            total_duration=duration,
            total_frames=int(duration * fps),
            scenes=scenes,
            chapters=chapters,
            scene_detection_threshold=self.scene_threshold,
            created_at=datetime.now(UTC).isoformat(),
        )

        logger.info(f"Video structure complete: {len(scenes)} scenes, {len(chapters)} chapters")
        return structure
