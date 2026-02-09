"""
Download benchmark datasets for QPrisma evaluation.

Supports:
- Video-MME (CVPR 2025): From HuggingFace lmms-lab/Video-MME
- MLVU (CVPR 2025): From HuggingFace MLVU/MVLU

Usage:
    python -m evaluation.scripts.download_benchmarks --benchmark video_mme --output data/benchmarks
    python -m evaluation.scripts.download_benchmarks --benchmark mlvu --output data/benchmarks
    python -m evaluation.scripts.download_benchmarks --benchmark all --output data/benchmarks
"""

import argparse
import json
import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


def download_video_mme(output_dir: Path, subset: str = "test") -> Path:
    """Download Video-MME benchmark from HuggingFace.

    Dataset: lmms-lab/Video-MME
    Requires: pip install datasets

    Args:
        output_dir: Base output directory.
        subset: Dataset subset ('test' is the main evaluation set).

    Returns:
        Path to the downloaded benchmark data directory.
    """
    try:
        from datasets import load_dataset
    except ImportError:
        logger.error(
            "The 'datasets' package is required. Install with: pip install datasets"
        )
        sys.exit(1)

    bench_dir = output_dir / "video_mme"
    bench_dir.mkdir(parents=True, exist_ok=True)

    # Check if already downloaded
    data_file = bench_dir / "video_mme.json"
    if data_file.exists():
        logger.info("Video-MME data already exists at %s", data_file)
        return bench_dir

    logger.info("Downloading Video-MME from HuggingFace...")
    try:
        dataset = load_dataset("lmms-lab/Video-MME", split=subset)
    except Exception as e:
        logger.error("Failed to download Video-MME: %s", e)
        logger.info(
            "You may need to: 1) Accept terms at https://huggingface.co/datasets/lmms-lab/Video-MME "
            "2) Run: huggingface-cli login"
        )
        raise

    # Convert to our JSON format
    entries = []
    for row in dataset:
        entry = {
            "question_id": str(row.get("question_id", row.get("index", ""))),
            "video_id": row.get("video_id", row.get("videoID", "")),
            "question": row.get("question", ""),
            "choices": _parse_video_mme_choices(row),
            "correct_answer": row.get("answer", ""),
            "category": row.get("task_type", row.get("question_type", "")),
            "domain": row.get("domain", ""),
            "duration_tier": _map_duration_tier(row.get("duration", "")),
            "video_duration_seconds": row.get("duration_seconds", None),
            "benchmark": "video_mme",
        }
        entries.append(entry)

    # Save
    data_file.write_text(json.dumps(entries, indent=2))
    logger.info("Saved %d Video-MME entries to %s", len(entries), data_file)

    # Save metadata
    meta = {
        "benchmark": "Video-MME",
        "source": "lmms-lab/Video-MME",
        "total_entries": len(entries),
        "subset": subset,
    }
    (bench_dir / "metadata.json").write_text(json.dumps(meta, indent=2))

    return bench_dir


def download_mlvu(output_dir: Path) -> Path:
    """Download MLVU benchmark from HuggingFace.

    Dataset: MLVU/MVLU
    Requires: pip install datasets

    Args:
        output_dir: Base output directory.

    Returns:
        Path to the downloaded benchmark data directory.
    """
    try:
        from datasets import load_dataset
    except ImportError:
        logger.error(
            "The 'datasets' package is required. Install with: pip install datasets"
        )
        sys.exit(1)

    bench_dir = output_dir / "mlvu"
    bench_dir.mkdir(parents=True, exist_ok=True)

    # Check if already downloaded
    data_file = bench_dir / "mlvu.json"
    if data_file.exists():
        logger.info("MLVU data already exists at %s", data_file)
        return bench_dir

    logger.info("Downloading MLVU from HuggingFace...")

    # MLVU has multiple task files - try loading via datasets first
    all_entries = []

    # MC tasks
    mc_tasks = [
        "topic_reasoning", "anomaly_recognition", "needle_qa",
        "ego_reasoning", "plot_qa", "action_order", "action_count",
    ]
    # Generation tasks
    gen_tasks = ["sub_scene", "summary"]

    for task in mc_tasks + gen_tasks:
        try:
            dataset = load_dataset("MLVU/MVLU", task, split="test")
            for row in dataset:
                entry = {
                    "question_id": f"{task}_{row.get('index', len(all_entries))}",
                    "video_id": row.get("video", ""),
                    "question": row.get("question", ""),
                    "choices": row.get("candidates", None),
                    "correct_answer": row.get("answer", ""),
                    "category": task,
                    "duration_tier": _estimate_tier_from_seconds(
                        row.get("duration", 0)
                    ),
                    "video_duration_seconds": row.get("duration", None),
                    "benchmark": "mlvu",
                }
                all_entries.append(entry)
            logger.info("Loaded %s: %d entries", task, len(dataset))
        except Exception as e:
            logger.warning("Failed to load MLVU task %s: %s", task, e)

    if not all_entries:
        logger.error(
            "No MLVU data could be loaded. Try downloading manually from "
            "https://github.com/JUNJIE99/MLVU"
        )
        raise RuntimeError("MLVU download failed")

    # Save
    data_file.write_text(json.dumps(all_entries, indent=2))
    logger.info("Saved %d MLVU entries to %s", len(all_entries), data_file)

    meta = {
        "benchmark": "MLVU",
        "source": "MLVU/MVLU",
        "total_entries": len(all_entries),
        "tasks": mc_tasks + gen_tasks,
    }
    (bench_dir / "metadata.json").write_text(json.dumps(meta, indent=2))

    return bench_dir


def download_videos_manifest(bench_dir: Path, benchmark: str) -> Path:
    """Generate a video download manifest.

    Since videos are large, we generate a manifest of required video files
    with their URLs/paths rather than downloading them directly.

    Args:
        bench_dir: Benchmark data directory.
        benchmark: Benchmark name.

    Returns:
        Path to the manifest file.
    """
    data_file = bench_dir / f"{benchmark}.json"
    if not data_file.exists():
        logger.error("Benchmark data not found at %s", data_file)
        raise FileNotFoundError(f"Benchmark data not found: {data_file}")

    entries = json.loads(data_file.read_text())

    # Extract unique video IDs
    video_ids = sorted({e["video_id"] for e in entries if e.get("video_id")})

    manifest = {
        "benchmark": benchmark,
        "total_videos": len(video_ids),
        "video_dir": str(bench_dir / "videos"),
        "videos": [
            {
                "video_id": vid,
                "expected_path": f"videos/{vid}.mp4",
                "downloaded": (bench_dir / "videos" / f"{vid}.mp4").exists(),
            }
            for vid in video_ids
        ],
    }

    manifest_path = bench_dir / "video_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))
    logger.info(
        "Video manifest: %d videos (%d downloaded)",
        len(video_ids),
        sum(1 for v in manifest["videos"] if v["downloaded"]),
    )

    return manifest_path


# =============================================================================
# Helpers
# =============================================================================


def _parse_video_mme_choices(row: dict) -> list[str]:
    """Parse choices from Video-MME row (various formats)."""
    # Format 1: "options" field with "A. ...", "B. ..."
    if "options" in row and isinstance(row["options"], list):
        return row["options"]

    # Format 2: Separate option_A, option_B, etc.
    choices = []
    for letter in ["A", "B", "C", "D"]:
        key = f"option_{letter}"
        if key in row:
            choices.append(row[key])

    if choices:
        return choices

    # Format 3: "candidates" field
    if "candidates" in row and isinstance(row["candidates"], list):
        return row["candidates"]

    return []


def _map_duration_tier(duration_str: str) -> str:
    """Map Video-MME duration string to our tier."""
    duration_str = duration_str.lower().strip()
    if "short" in duration_str:
        return "short"
    elif "medium" in duration_str:
        return "medium"
    elif "long" in duration_str:
        return "long"
    return "medium"


def _estimate_tier_from_seconds(duration_secs: float | int | None) -> str:
    """Estimate duration tier from seconds."""
    if duration_secs is None:
        return "medium"
    if duration_secs < 120:
        return "short"
    elif duration_secs < 900:
        return "medium"
    elif duration_secs < 3600:
        return "long"
    return "very_long"


# =============================================================================
# CLI
# =============================================================================


def main():
    parser = argparse.ArgumentParser(
        description="Download benchmark datasets for QPrisma evaluation"
    )
    parser.add_argument(
        "--benchmark",
        type=str,
        required=True,
        choices=["video_mme", "mlvu", "all"],
        help="Benchmark to download",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="data/benchmarks",
        help="Output directory",
    )
    parser.add_argument(
        "--generate-manifest",
        action="store_true",
        help="Generate video download manifest",
    )
    parser.add_argument("-v", "--verbose", action="store_true")

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    output_dir = Path(args.output)

    if args.benchmark in ("video_mme", "all"):
        bench_dir = download_video_mme(output_dir)
        if args.generate_manifest:
            download_videos_manifest(bench_dir, "video_mme")

    if args.benchmark in ("mlvu", "all"):
        bench_dir = download_mlvu(output_dir)
        if args.generate_manifest:
            download_videos_manifest(bench_dir, "mlvu")

    logger.info("Download complete. Output: %s", output_dir)


if __name__ == "__main__":
    main()
