"""
Processing Routes

Handles video processing presets.
Uses PostgreSQL for metadata storage (replaces Cosmos DB).
"""

import logging

from fastapi import APIRouter, Depends

from api.dependencies import (
    get_current_user,
)
from models.ffmpeg_config import (
    ProcessingPreset,
    get_preset_config,
)
from models.user import User

router = APIRouter(tags=["Processing"])
logger = logging.getLogger(__name__)


def _get_preset_description(preset: ProcessingPreset) -> str:
    """Get description for a preset."""
    descriptions = {
        ProcessingPreset.FAST_PREVIEW: "Fast extraction with low resolution (640x360), ideal for quick previews",
        ProcessingPreset.BALANCED: "Balance between speed and quality (1280x720), 5s intervals, up to 200 frames",
        ProcessingPreset.HIGH_QUALITY: "Maximum quality, 3s intervals, up to 600 frames, slower processing",
        ProcessingPreset.KEYFRAMES_ONLY: "Only video keyframes, useful for main scene changes",
        ProcessingPreset.SCENE_ANALYSIS: "Automatic scene change detection, up to 150 frames",
        ProcessingPreset.TIMELINE_PREVIEW: "30 frames uniformly distributed, low resolution (320x180)",
        ProcessingPreset.DEEP_ANALYSIS: "Hybrid scene + uniform extraction for long videos (1280x720), up to 1000 frames",
        ProcessingPreset.ULTRA_DEEP: "Maximum extraction for very long videos (4+ hours), up to 2000 frames",
        ProcessingPreset.INTERVIEW_MODE: "Optimized for audio-focused content, fewer visual frames at 10s intervals",
        ProcessingPreset.ACTION_MODE: "Motion-heavy content, aggressive scene detection (1920x1080), up to 800 frames",
        ProcessingPreset.ADAPTIVE: "Automatic configuration based on video duration, adjusts method and frame count",
    }
    return descriptions.get(preset, "No description")


# =============================================================================
# Routes
# =============================================================================


@router.get("/presets")
async def get_available_presets(current_user: User = Depends(get_current_user)):
    """List all available presets with their descriptions."""
    presets = []

    for preset in ProcessingPreset:
        config = get_preset_config(preset)
        presets.append(
            {
                "name": preset.value,
                "description": _get_preset_description(preset),
                "config": {
                    "extraction_method": config.frame_extraction.method.value,
                    "max_frames": config.frame_extraction.max_frames,
                    "fps": config.frame_extraction.fps,
                    "interval_seconds": config.frame_extraction.interval_seconds,
                    "scale_width": config.video_filters.scale_width,
                    "scale_height": config.video_filters.scale_height,
                },
            }
        )

    return {"presets": presets}
