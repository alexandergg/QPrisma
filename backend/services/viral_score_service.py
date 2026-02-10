"""
Viral Score Service
===================

Analyzes video content segments to calculate viral potential scores.
Uses transcription, audio features, and visual analysis to identify
the most engaging moments for short-form content.

Based on analysis of viral content patterns:
- Hook strength (first few seconds)
- Energy and pacing
- Topic engagement
- Completeness of idea
"""

import logging
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Keywords that tend to perform well in short-form content
HOOK_KEYWORDS = [
    # Curiosity triggers
    "secret",
    "hidden",
    "unknown",
    "discover",
    "revealed",
    "never",
    "always",
    "every",
    "nobody",
    "everyone",
    # Value indicators
    "mistake",
    "wrong",
    "right",
    "truth",
    "lie",
    "hack",
    "trick",
    "tip",
    "lesson",
    "learned",
    # Emotional triggers
    "shocked",
    "surprised",
    "amazing",
    "incredible",
    "insane",
    "changed",
    "transformed",
    "mind-blowing",
    "crazy",
    # Action words
    "stop",
    "start",
    "must",
    "need",
    "should",
    "here's",
    "this is",
    "let me",
    "watch",
    # Numbers and specifics
    "one",
    "three",
    "five",
    "number",
    "reason",
]

# Topics that typically engage audiences
ENGAGING_TOPICS = [
    "money",
    "wealth",
    "income",
    "rich",
    "success",
    "health",
    "fitness",
    "weight",
    "diet",
    "relationship",
    "dating",
    "love",
    "marriage",
    "career",
    "job",
    "business",
    "entrepreneur",
    "productivity",
    "time",
    "habit",
    "routine",
    "technology",
    "ai",
    "future",
    "innovation",
    "mindset",
    "psychology",
    "brain",
    "thinking",
]

# Words that indicate controversy or strong opinions
CONTROVERSY_WORDS = [
    "controversial",
    "debate",
    "disagree",
    "unpopular",
    "actually",
    "truth is",
    "most people",
    "nobody tells you",
    "wrong",
    "bad advice",
    "overrated",
    "underrated",
]


@dataclass
class ViralScoreResult:
    """Result of viral score calculation."""

    score: float  # 0-100
    reasons: list[str]
    components: dict[str, float]
    recommendations: list[str]


@dataclass
class TranscriptSegment:
    """A segment of transcript with timing."""

    start_time: float
    end_time: float
    text: str
    words: list[dict]  # Word-level timing


class ViralScoreService:
    """
    Service for analyzing content segments and calculating viral potential.
    """

    def __init__(self):
        """Initialize the service."""
        self.hook_keywords = set(HOOK_KEYWORDS)
        self.engaging_topics = set(ENGAGING_TOPICS)
        self.controversy_words = set(CONTROVERSY_WORDS)

    def calculate_viral_score(
        self,
        transcript_segment: TranscriptSegment,
        audio_energy: float | None = None,
        has_face: bool | None = None,
        scene_changes: int = 0,
    ) -> ViralScoreResult:
        """
        Calculate viral potential score for a content segment.

        Args:
            transcript_segment: The transcript segment to analyze
            audio_energy: Optional audio energy level (0-1)
            has_face: Whether the segment contains a face
            scene_changes: Number of visual scene changes

        Returns:
            ViralScoreResult with score, reasons, and recommendations
        """
        text = transcript_segment.text.lower()
        words = text.split()
        duration = transcript_segment.end_time - transcript_segment.start_time

        components = {}
        reasons = []
        recommendations = []

        # 1. Hook Score (25% weight)
        # Check if the beginning has strong hooks
        hook_score = self._calculate_hook_score(text, words[:30])
        components["hook"] = hook_score
        if hook_score >= 70:
            reasons.append("Strong opening hook")
        elif hook_score < 40:
            recommendations.append("Add a stronger hook in the first few seconds")

        # 2. Topic Engagement Score (20% weight)
        topic_score = self._calculate_topic_score(text)
        components["topic"] = topic_score
        if topic_score >= 70:
            reasons.append("High-interest topic")

        # 3. Pacing Score (15% weight)
        pacing_score = self._calculate_pacing_score(transcript_segment, words, duration)
        components["pacing"] = pacing_score
        if pacing_score >= 70:
            reasons.append("Good energy and pacing")
        elif pacing_score < 40:
            recommendations.append("Consider faster pacing or shorter pauses")

        # 4. Completeness Score (15% weight)
        completeness_score = self._calculate_completeness_score(text, duration)
        components["completeness"] = completeness_score
        if completeness_score >= 70:
            reasons.append("Complete, standalone idea")
        elif completeness_score < 40:
            recommendations.append("Ensure the clip contains a complete thought")

        # 5. Controversy/Opinion Score (10% weight)
        controversy_score = self._calculate_controversy_score(text)
        components["controversy"] = controversy_score
        if controversy_score >= 60:
            reasons.append("Strong opinion or contrarian view")

        # 6. Duration Score (10% weight)
        duration_score = self._calculate_duration_score(duration)
        components["duration"] = duration_score
        if duration_score < 50:
            if duration > 60:
                recommendations.append("Consider trimming to under 60 seconds")
            elif duration < 10:
                recommendations.append("Consider extending to at least 15 seconds")

        # 7. Visual Score (5% weight) - based on available data
        visual_score = self._calculate_visual_score(has_face, scene_changes)
        components["visual"] = visual_score
        if visual_score >= 70:
            reasons.append("Engaging visuals")

        # Calculate weighted total
        total_score = (
            hook_score * 0.25
            + topic_score * 0.20
            + pacing_score * 0.15
            + completeness_score * 0.15
            + controversy_score * 0.10
            + duration_score * 0.10
            + visual_score * 0.05
        )

        # Apply bonuses
        if audio_energy and audio_energy > 0.7:
            total_score = min(100, total_score + 5)
            reasons.append("High audio energy")

        # Ensure reasons if score is high but no reasons
        if total_score >= 60 and not reasons:
            reasons.append("Good overall content balance")

        return ViralScoreResult(
            score=round(total_score, 1),
            reasons=reasons,
            components=components,
            recommendations=recommendations,
        )

    def _calculate_hook_score(self, text: str, first_words: list[str]) -> float:
        """Calculate hook strength based on first words."""
        score = 40  # Base score

        first_text = " ".join(first_words)

        # Check for hook keywords
        hook_count = sum(1 for word in first_words if word in self.hook_keywords)
        score += min(30, hook_count * 10)

        # Check for questions (hooks that engage)
        if "?" in first_text:
            score += 15

        # Check for "you" addressing the viewer
        if "you" in first_words[:10]:
            score += 10

        # Check for numbers (specificity increases engagement)
        if any(c.isdigit() for c in first_text):
            score += 5

        return min(100, score)

    def _calculate_topic_score(self, text: str) -> float:
        """Calculate topic engagement potential."""
        score = 30  # Base score

        # Count engaging topics mentioned
        topic_count = sum(1 for topic in self.engaging_topics if topic in text)
        score += min(40, topic_count * 10)

        # Bonus for combining multiple topics
        if topic_count >= 2:
            score += 15

        # Check for specific/concrete examples
        if re.search(r"\$[\d,]+|\d+%|\d+ (year|month|day)", text):
            score += 15

        return min(100, score)

    def _calculate_pacing_score(
        self, segment: TranscriptSegment, words: list[str], duration: float
    ) -> float:
        """Calculate pacing based on words per minute."""
        if duration <= 0:
            return 50

        wpm = (len(words) / duration) * 60

        # Ideal WPM for engaging content is 130-170
        if 130 <= wpm <= 170:
            return 100
        elif 100 <= wpm < 130 or 170 < wpm <= 200:
            return 70
        elif 80 <= wpm < 100 or 200 < wpm <= 220:
            return 50
        else:
            return 30

    def _calculate_completeness_score(self, text: str, duration: float) -> float:
        """Check if the segment contains a complete thought."""
        score = 50  # Base score

        # Check for sentence structure
        sentences = text.count(".") + text.count("!") + text.count("?")
        if sentences >= 2:
            score += 20

        # Check for conclusion indicators
        conclusion_words = ["so", "therefore", "that's why", "in conclusion", "the point is"]
        if any(word in text.lower() for word in conclusion_words):
            score += 20

        # Penalize if text seems cut off
        if text.rstrip().endswith((",", "and", "but", "or", "the", "a", "an")):
            score -= 20

        # Ideal duration for completeness
        if 20 <= duration <= 60:
            score += 10

        return max(0, min(100, score))

    def _calculate_controversy_score(self, text: str) -> float:
        """Calculate controversy/opinion strength."""
        score = 20  # Base score

        # Check for controversy words
        controversy_count = sum(1 for word in self.controversy_words if word in text)
        score += min(40, controversy_count * 15)

        # Check for strong opinion indicators
        opinion_words = ["i think", "i believe", "in my opinion", "honestly", "the problem is"]
        if any(word in text for word in opinion_words):
            score += 20

        # Check for contrarian patterns
        if re.search(r"but (most|many|everyone|nobody)", text):
            score += 20

        return min(100, score)

    def _calculate_duration_score(self, duration: float) -> float:
        """Score based on ideal clip duration."""
        # Optimal durations for different platforms:
        # TikTok: 21-34 seconds (sweet spot)
        # Reels: 15-30 seconds
        # Shorts: 30-60 seconds

        if 21 <= duration <= 45:
            return 100
        elif 15 <= duration < 21 or 45 < duration <= 60:
            return 80
        elif 10 <= duration < 15 or 60 < duration <= 90:
            return 60
        elif 5 <= duration < 10 or 90 < duration <= 120:
            return 40
        else:
            return 20

    def _calculate_visual_score(self, has_face: bool | None, scene_changes: int) -> float:
        """Score based on visual engagement factors."""
        score = 50  # Base score

        if has_face is True:
            score += 25  # Faces are engaging

        # Some scene changes are good (dynamic), too many are distracting
        if 1 <= scene_changes <= 3:
            score += 25
        elif scene_changes > 5:
            score -= 10

        return max(0, min(100, score))

    def find_potential_clips(
        self,
        full_transcript: list[dict],
        min_duration: float = 15,
        max_duration: float = 60,
        min_score: float = 50,
        max_clips: int = 10,
    ) -> list[dict]:
        """
        Find potential viral clips from a full transcript.

        Args:
            full_transcript: List of transcript segments with word-level timing
            min_duration: Minimum clip duration in seconds
            max_duration: Maximum clip duration in seconds
            min_score: Minimum viral score to include
            max_clips: Maximum number of clips to return

        Returns:
            List of potential clips with scores and timing
        """
        potential_clips = []

        if not full_transcript:
            return []

        # Group transcript into potential clip segments
        segments = self._segment_transcript(full_transcript, min_duration, max_duration)

        for segment in segments:
            result = self.calculate_viral_score(segment)

            if result.score >= min_score:
                potential_clips.append(
                    {
                        "start_time": segment.start_time,
                        "end_time": segment.end_time,
                        "duration": segment.end_time - segment.start_time,
                        "text_preview": (
                            segment.text[:100] + "..." if len(segment.text) > 100 else segment.text
                        ),
                        "viral_score": result.score,
                        "reasons": result.reasons,
                        "recommendations": result.recommendations,
                    }
                )

        # Sort by score and return top clips
        potential_clips.sort(key=lambda x: x["viral_score"], reverse=True)

        # Remove overlapping clips (keep higher scored ones)
        filtered_clips = self._remove_overlapping_clips(potential_clips)

        return filtered_clips[:max_clips]

    def _segment_transcript(
        self, full_transcript: list[dict], min_duration: float, max_duration: float
    ) -> list[TranscriptSegment]:
        """Segment transcript into potential clips."""
        segments = []

        if not full_transcript:
            return segments

        # For now, use a sliding window approach
        # In a more advanced version, we'd detect natural break points

        # Get total duration
        first_start = full_transcript[0].get("start", 0)
        last_end = full_transcript[-1].get("end", 0)
        total_duration = last_end - first_start

        if total_duration < min_duration:
            return segments

        # Create segments at various positions
        window_sizes = [30, 45, 60]  # Different potential lengths
        step_size = 10  # Seconds between segment starts

        current_start = first_start

        while current_start < last_end - min_duration:
            for window_size in window_sizes:
                if window_size < min_duration or window_size > max_duration:
                    continue

                end_time = min(current_start + window_size, last_end)

                # Get text for this segment
                segment_text = self._get_text_in_range(full_transcript, current_start, end_time)

                if segment_text:
                    segments.append(
                        TranscriptSegment(
                            start_time=current_start,
                            end_time=end_time,
                            text=segment_text,
                            words=[],
                        )
                    )

            current_start += step_size

        return segments

    def _get_text_in_range(self, transcript: list[dict], start: float, end: float) -> str:
        """Extract text from transcript within time range."""
        words = []

        for item in transcript:
            item_start = item.get("start", 0)
            item_end = item.get("end", 0)

            # Check if this item overlaps with our range
            if item_end >= start and item_start <= end:
                text = item.get("text", item.get("word", ""))
                if text:
                    words.append(text)

        return " ".join(words)

    def _remove_overlapping_clips(
        self, clips: list[dict], overlap_threshold: float = 0.5
    ) -> list[dict]:
        """Remove clips that overlap too much, keeping higher scored ones."""
        if not clips:
            return []

        filtered = []

        for clip in clips:
            overlaps = False
            for existing in filtered:
                # Calculate overlap
                overlap_start = max(clip["start_time"], existing["start_time"])
                overlap_end = min(clip["end_time"], existing["end_time"])

                if overlap_start < overlap_end:
                    overlap_duration = overlap_end - overlap_start
                    clip_duration = clip["end_time"] - clip["start_time"]

                    if overlap_duration / clip_duration > overlap_threshold:
                        overlaps = True
                        break

            if not overlaps:
                filtered.append(clip)

        return filtered


# Singleton instance
_viral_score_service: ViralScoreService | None = None


def get_viral_score_service() -> ViralScoreService:
    """Get the singleton viral score service instance."""
    global _viral_score_service
    if _viral_score_service is None:
        _viral_score_service = ViralScoreService()
    return _viral_score_service
