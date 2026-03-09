"""
Coverage Analyzer

Calculates video coverage metrics from frame timestamps.
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)


class CoverageAnalyzer:
    """Analyze frame coverage of a video."""

    def calculate_coverage_metrics(
        self, timestamps: list[float], video_duration: float
    ) -> dict[str, Any]:
        """
        Calculate video coverage metrics.

        Args:
            timestamps: List of extracted timestamps.
            video_duration: Total video duration in seconds.

        Returns:
            Dict with coverage metrics:
            - coverage_score: 0-100, how well the video is covered
            - average_gap: Average gap between frames
            - max_gap: Maximum gap (indicates possible blind spots)
            - gaps_over_threshold: List of problematic gaps
            - density_per_minute: Average frames per minute
            - recommendations: Suggestions to improve coverage
        """
        if not timestamps or video_duration <= 0:
            return {
                "coverage_score": 0,
                "average_gap": 0,
                "max_gap": video_duration,
                "gaps_over_threshold": [],
                "density_per_minute": 0,
                "recommendations": ["No frames extracted"],
            }

        sorted_ts = sorted(timestamps)

        # Calculate gaps
        gaps: list[dict[str, float]] = []
        for i in range(len(sorted_ts) - 1):
            gap = sorted_ts[i + 1] - sorted_ts[i]
            gaps.append(
                {
                    "start": sorted_ts[i],
                    "end": sorted_ts[i + 1],
                    "duration": gap,
                }
            )

        # Add leading and trailing gaps
        if sorted_ts[0] > 1.0:  # If there is more than 1 second at the start
            gaps.insert(0, {"start": 0, "end": sorted_ts[0], "duration": sorted_ts[0]})
        if video_duration - sorted_ts[-1] > 1.0:
            gaps.append(
                {
                    "start": sorted_ts[-1],
                    "end": video_duration,
                    "duration": video_duration - sorted_ts[-1],
                }
            )

        # Basic metrics
        gap_durations = [g["duration"] for g in gaps]
        avg_gap = sum(gap_durations) / len(gap_durations) if gap_durations else 0
        max_gap = max(gap_durations) if gap_durations else 0

        # Dynamic threshold based on video duration
        # For short videos, gaps >10s are problematic
        # For long videos, gaps >30s are problematic
        if video_duration < 300:  # < 5 min
            gap_threshold = 10.0
        elif video_duration < 1800:  # < 30 min
            gap_threshold = 20.0
        elif video_duration < 3600:  # < 1 hour
            gap_threshold = 30.0
        else:  # > 1 hour
            gap_threshold = 45.0

        problematic_gaps = [g for g in gaps if g["duration"] > gap_threshold]

        # Coverage score (0-100)
        # Based on: frame density, maximum gaps, distribution
        density = len(timestamps) / (video_duration / 60)  # frames per minute
        ideal_density = 10  # 10 frames/min is ideal for analysis
        density_score = min(density / ideal_density * 100, 100)

        # Penalty for large gaps
        gap_penalty = min(len(problematic_gaps) * 10, 50)
        max_gap_penalty = (
            min((max_gap / gap_threshold - 1) * 20, 30) if max_gap > gap_threshold else 0
        )

        coverage_score = max(0, density_score - gap_penalty - max_gap_penalty)

        # Recommendations
        recommendations: list[str] = []
        if coverage_score < 50:
            recommendations.append(
                "Consider using DEEP_ANALYSIS or ADAPTIVE preset for better coverage"
            )
        if max_gap > gap_threshold * 2:
            recommendations.append(
                f"Large gap detected ({max_gap:.1f}s) - use HYBRID extraction to fill gaps"
            )
        if density < 5:
            recommendations.append("Low frame density - increase max_frames or reduce interval")
        if len(problematic_gaps) > 5:
            recommendations.append(
                f"{len(problematic_gaps)} gaps over {gap_threshold}s - content may be missed"
            )
        if not recommendations:
            recommendations.append("Good coverage achieved")

        return {
            "coverage_score": round(coverage_score, 1),
            "average_gap": round(avg_gap, 2),
            "max_gap": round(max_gap, 2),
            "gap_threshold": gap_threshold,
            "gaps_over_threshold": problematic_gaps[:10],  # Limit to 10
            "total_problematic_gaps": len(problematic_gaps),
            "density_per_minute": round(density, 2),
            "total_frames": len(timestamps),
            "video_duration": video_duration,
            "recommendations": recommendations,
        }
