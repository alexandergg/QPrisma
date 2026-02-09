"""
MLVU benchmark data loader.

MLVU (CVPR 2025): ~2K videos, 3,102 questions across 9 task types.
HuggingFace: MLVU/MVLU (dev), MLVU/MLVU_Test (test)
GitHub: github.com/JUNJIE99/MLVU
"""

import json
import logging
from pathlib import Path

from evaluation.models.eval_schemas import BenchmarkEntry, DurationTier

logger = logging.getLogger(__name__)

# MLVU task configuration: file -> (question_type, task_type, is_generation)
TASK_FILES = {
    "1_plotQA.json": ("plotQA", "multiple_choice", False),
    "2_needle.json": ("findNeedle", "multiple_choice", False),
    "3_ego.json": ("ego", "multiple_choice", False),
    "4_count.json": ("count", "multiple_choice", False),
    "5_order.json": ("order", "multiple_choice", False),
    "6_anomaly_reco.json": ("anomaly_reco", "multiple_choice", False),
    "7_topic_reasoning.json": ("topic_reasoning", "multiple_choice", False),
    "8_sub_scene.json": ("subPlot", "generation", True),
    "9_summary.json": ("summary", "generation", True),
}

# Map question_type to the video subdirectory name
_VIDEO_SUBDIR = {
    "plotQA": "plotQA",
    "findNeedle": "needle",
    "ego": "ego",
    "count": "count",
    "order": "order",
    "anomaly_reco": "anomaly_reco",
    "topic_reasoning": "topic_reasoning",
    "subPlot": "plotQA",  # Sub-scene uses plotQA videos
    "summary": "topic_reasoning",  # Summary uses topic_reasoning videos
}


def load_from_directory(
    json_dir: str | Path,
    video_dir: str | Path | None = None,
    tasks: list[str] | None = None,
) -> list[BenchmarkEntry]:
    """Load MLVU from local JSON files.

    Args:
        json_dir: Directory containing the 9 task JSON files.
        video_dir: Root directory containing video subdirectories.
        tasks: Optional filter for specific task files (e.g., ["1_plotQA.json"]).
            None = load all tasks.

    Returns:
        List of BenchmarkEntry objects.
    """
    json_dir = Path(json_dir)
    entries = []
    question_counter = 0

    for filename, (question_type, task_type, is_gen) in TASK_FILES.items():
        if tasks and filename not in tasks:
            continue

        filepath = json_dir / filename
        if not filepath.exists():
            logger.warning("MLVU task file not found: %s", filepath)
            continue

        with open(filepath, encoding="utf-8") as f:
            data = json.load(f)

        for item in data:
            question_counter += 1
            entry = _item_to_entry(
                item,
                question_type=question_type,
                is_generation=is_gen,
                question_index=question_counter,
            )
            entries.append(entry)

        logger.info("Loaded %d entries from %s", len(data), filename)

    logger.info("Loaded %d total MLVU entries", len(entries))
    return entries


def load_mc_only(
    json_dir: str | Path,
    video_dir: str | Path | None = None,
) -> list[BenchmarkEntry]:
    """Load only the 7 multiple-choice tasks (exclude generation tasks)."""
    mc_tasks = [f for f, (_, _, is_gen) in TASK_FILES.items() if not is_gen]
    return load_from_directory(json_dir, video_dir, tasks=mc_tasks)


def load_generation_only(
    json_dir: str | Path,
    video_dir: str | Path | None = None,
) -> list[BenchmarkEntry]:
    """Load only the 2 generation tasks (sub-scene captioning + summary)."""
    gen_tasks = [f for f, (_, _, is_gen) in TASK_FILES.items() if is_gen]
    return load_from_directory(json_dir, video_dir, tasks=gen_tasks)


def _item_to_entry(
    item: dict,
    question_type: str,
    is_generation: bool,
    question_index: int,
) -> BenchmarkEntry:
    """Convert a single MLVU JSON item to BenchmarkEntry.

    MC schema: {video, duration, question, candidates, answer, question_type}
    Gen schema: {video, duration, question, answer, question_type, [scoring_points]}
    """
    duration_seconds = float(item.get("duration", 0))
    duration_tier = _seconds_to_tier(duration_seconds)

    # For MC tasks, candidates are raw text (no letter prefix)
    choices = item.get("candidates")

    # Correct answer: MLVU stores as full text, not letter index
    correct_answer = item.get("answer")

    question_id = f"mlvu_{question_type}_{question_index}"

    metadata = {
        "video_filename": item.get("video"),
        "question_type_raw": item.get("question_type", question_type),
    }

    # Generation tasks may have scoring_points
    scoring_points = item.get("scoring_points")
    if scoring_points:
        metadata["scoring_points"] = scoring_points

    return BenchmarkEntry(
        question_id=question_id,
        video_id=item.get("video", ""),
        question=item.get("question", ""),
        choices=choices,
        correct_answer=correct_answer,
        category=question_type,
        domain=None,  # MLVU doesn't have domain labels
        duration_tier=duration_tier,
        video_duration_seconds=duration_seconds,
        benchmark="mlvu",
        metadata=metadata,
    )


def get_video_path(
    entry: BenchmarkEntry,
    video_root: str | Path,
) -> Path:
    """Resolve the video file path for an MLVU entry.

    MLVU stores videos in subdirectories by task type:
    {video_root}/{task_subdir}/{filename}.mp4
    """
    video_root = Path(video_root)
    filename = (entry.metadata or {}).get("video_filename", entry.video_id)
    question_type = entry.category or ""
    subdir = _VIDEO_SUBDIR.get(question_type, question_type)

    return video_root / subdir / filename


def _seconds_to_tier(seconds: float) -> DurationTier:
    """Map duration in seconds to a tier."""
    if seconds < 120:
        return DurationTier.SHORT
    elif seconds < 900:
        return DurationTier.MEDIUM
    elif seconds < 3600:
        return DurationTier.LONG
    else:
        return DurationTier.VERY_LONG
