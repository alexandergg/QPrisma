"""
Formatting Utilities
====================

Helper functions for formatting timestamps and other data types.
"""

from typing import Any


def get_timestamp_from_content(content: dict[str, Any], default: float = 0.0) -> float:
    """
    Extract timestamp from node content, handling different node types.

    - Frame nodes use 'timestamp'
    - AudioSegment nodes use 'start_time'
    - Scene nodes use 'start_time'
    - Entity nodes may have 'timestamp' from associated frames

    Args:
        content: Node content dictionary
        default: Default value if no timestamp found

    Returns:
        Timestamp in seconds
    """
    # Try 'timestamp' first (Frame, Entity)
    ts = content.get("timestamp")
    if ts is not None:
        return float(ts)

    # Try 'start_time' (AudioSegment, Scene)
    start_time = content.get("start_time")
    if start_time is not None:
        return float(start_time)

    return default


def format_timestamp(seconds: float) -> str:
    """Format seconds as MM:SS or HH:MM:SS."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)

    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def parse_timestamp(timestamp_str: str) -> float:
    """Parse MM:SS or HH:MM:SS to seconds."""
    parts = timestamp_str.split(":")
    if len(parts) == 2:
        return int(parts[0]) * 60 + int(parts[1])
    elif len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
    return float(timestamp_str)
