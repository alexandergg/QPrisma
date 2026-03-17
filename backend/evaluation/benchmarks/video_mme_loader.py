"""
Video-MME benchmark data loader.

Video-MME (CVPR 2025): 900 videos, 2,700 MC questions across 3 duration tiers.
HuggingFace: lmms-lab/Video-MME
"""

import json
import logging
from pathlib import Path

from evaluation.models.eval_schemas import BenchmarkEntry, DurationTier

logger = logging.getLogger(__name__)

# Video-MME duration tier mapping
_DURATION_MAP = {
    "short": DurationTier.SHORT,
    "medium": DurationTier.MEDIUM,
    "long": DurationTier.LONG,
}

# Video-MME task types (12 total)
TASK_TYPES = [
    "Temporal Perception",
    "Spatial Perception",
    "Attribute Perception",
    "Action Recognition",
    "Object Recognition",
    "OCR Problems",
    "Counting Problem",
    "Temporal Reasoning",
    "Spatial Reasoning",
    "Action Reasoning",
    "Object Reasoning",
    "Information Synopsis",
]

# Video-MME domains (6 total)
DOMAINS = [
    "Knowledge",
    "Film & Television",
    "Sports Competition",
    "Artistic Performance",
    "Life Record",
    "Multilingual",
]


def load_from_huggingface(
    video_dir: str | None = None,
) -> list[BenchmarkEntry]:
    """Load Video-MME from HuggingFace datasets library.

    Requires: pip install datasets

    Args:
        video_dir: Directory containing downloaded video files ({videoID}.mp4).

    Returns:
        List of BenchmarkEntry objects.
    """
    try:
        from datasets import load_dataset
    except ImportError:
        raise ImportError("Install datasets: pip install datasets") from None

    logger.info("Loading Video-MME from HuggingFace (lmms-lab/Video-MME)...")
    dataset = load_dataset("lmms-lab/Video-MME", "videomme", split="test")

    entries = []
    for row in dataset:
        entry = _row_to_entry(row)
        entries.append(entry)

    logger.info("Loaded %d Video-MME entries", len(entries))
    return entries


def load_from_json(
    json_path: str | Path,
    video_dir: str | None = None,
) -> list[BenchmarkEntry]:
    """Load Video-MME from JSON (auto-detects grouped or flat format).

    Grouped format (official output_test_template.json):
      [{"video_id": "001", "questions": [{"question_id": "001-1", ...}]}]

    Flat format (pre-processed, one entry per question):
      [{"question_id": "001-1", "video_id": "001", "question": "...", ...}]

    Args:
        json_path: Path to the JSON annotation file.
        video_dir: Directory containing video files.

    Returns:
        List of BenchmarkEntry objects.
    """
    path = Path(json_path)
    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    if not data:
        return []

    # Auto-detect format: flat entries have "question" key at top level
    first = data[0]
    if "question" in first and "questions" not in first:
        return _load_flat_format(data, path)
    return _load_grouped_format(data, path)


def _load_flat_format(data: list[dict], path: Path) -> list[BenchmarkEntry]:
    """Load pre-processed flat format (one dict per question)."""
    entries = []
    for item in data:
        duration_str = item.get("duration_tier", item.get("duration", ""))
        entry = BenchmarkEntry(
            question_id=item["question_id"],
            video_id=item["video_id"],
            question=item["question"],
            choices=item.get("choices", item.get("options", [])),
            correct_answer=item.get("correct_answer", item.get("answer")),
            category=item.get("category", item.get("task_type")),
            domain=item.get("domain"),
            duration_tier=_DURATION_MAP.get(str(duration_str).lower()),
            video_duration_seconds=item.get("video_duration_seconds"),
            benchmark=item.get("benchmark", "video-mme"),
            metadata={
                "sub_category": item.get("sub_category"),
                "url": item.get("url"),
                "youtube_id": item.get("videoID"),
            },
        )
        entries.append(entry)

    logger.info("Loaded %d Video-MME entries (flat format) from %s", len(entries), path)
    return entries


def _load_grouped_format(data: list[dict], path: Path) -> list[BenchmarkEntry]:
    """Load official grouped format (questions nested under video objects)."""
    entries = []
    for video_obj in data:
        video_id = video_obj["video_id"]
        duration_str = video_obj.get("duration", "")
        domain = video_obj.get("domain", "")
        sub_category = video_obj.get("sub_category", "")

        for q in video_obj.get("questions", []):
            entry = BenchmarkEntry(
                question_id=q["question_id"],
                video_id=video_id,
                question=q["question"],
                choices=q.get("options", []),
                correct_answer=q.get("answer"),
                category=q.get("task_type"),
                domain=domain,
                duration_tier=_DURATION_MAP.get(duration_str.lower()),
                benchmark="video-mme",
                metadata={
                    "sub_category": sub_category,
                    "url": video_obj.get("url"),
                    "youtube_id": video_obj.get("videoID"),
                },
            )
            entries.append(entry)

    logger.info("Loaded %d Video-MME entries (grouped format) from %s", len(entries), path)
    return entries


def _row_to_entry(row: dict) -> BenchmarkEntry:
    """Convert a HuggingFace dataset row to BenchmarkEntry.

    HuggingFace schema (flat, one row per question):
    - video_id, duration, domain, sub_category, url, videoID
    - question_id, task_type, question, options, answer
    """
    duration_str = row.get("duration", "")

    return BenchmarkEntry(
        question_id=row["question_id"],
        video_id=row["video_id"],
        question=row["question"],
        choices=row.get("options", []),
        correct_answer=row.get("answer"),
        category=row.get("task_type"),
        domain=row.get("domain"),
        duration_tier=_DURATION_MAP.get(duration_str.lower()),
        benchmark="video-mme",
        metadata={
            "sub_category": row.get("sub_category"),
            "url": row.get("url"),
            "youtube_id": row.get("videoID"),
        },
    )


def get_video_path(entry: BenchmarkEntry, video_dir: str | Path) -> Path:
    """Resolve the video file path for a Video-MME entry.

    Video-MME stores videos as {videoID}.mp4.
    """
    youtube_id = (entry.metadata or {}).get("youtube_id", entry.video_id)
    return Path(video_dir) / f"{youtube_id}.mp4"
