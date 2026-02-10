"""
Index benchmark videos through QPrisma's processing pipeline.

Uploads videos to Azure Blob Storage, creates metadata entries,
and queues Celery processing tasks (frame extraction, GPT-4o analysis,
Whisper transcription, KG indexing).

Prerequisites:
- Running infrastructure: Redis, PostgreSQL, Neo4j, Azure Blob
- Celery worker running: celery -A tasks.video_tasks worker
- Benchmark data downloaded (evaluation/scripts/download_benchmarks.py)
- Videos placed in the benchmark video directory

Usage:
    python -m evaluation.scripts.index_videos \\
        --benchmark video_mme \\
        --video-dir data/benchmarks/video_mme/videos \\
        --max-frames 20

    python -m evaluation.scripts.index_videos \\
        --benchmark mlvu \\
        --video-dir data/benchmarks/mlvu/videos \\
        --max-frames 30 \\
        --preset balanced
"""

import argparse
import json
import logging
import sys
import time
import uuid
from pathlib import Path

logger = logging.getLogger(__name__)


def index_videos_via_api(
    video_dir: Path,
    benchmark_data_path: Path,
    api_url: str = "http://localhost:8000",
    max_frames: int = 20,
    preset: str = "balanced",
    user_token: str | None = None,
) -> dict:
    """Index benchmark videos by calling QPrisma's API.

    This is the recommended approach as it goes through the full
    upload → process → index pipeline.

    Args:
        video_dir: Directory containing video files.
        benchmark_data_path: Path to benchmark JSON with video_id mappings.
        api_url: QPrisma API base URL.
        max_frames: Max frames to extract per video.
        preset: FFmpeg extraction preset (fast/balanced/quality).
        user_token: JWT token for authentication.

    Returns:
        Dict mapping video_id -> processing status.
    """
    import httpx

    # Load benchmark data to get video IDs
    entries = json.loads(benchmark_data_path.read_text())
    video_ids = sorted({e["video_id"] for e in entries if e.get("video_id")})
    logger.info("Found %d unique videos to index", len(video_ids))

    headers = {}
    if user_token:
        headers["Authorization"] = f"Bearer {user_token}"

    results = {}

    with httpx.Client(base_url=api_url, timeout=300, headers=headers) as client:
        for i, video_id in enumerate(video_ids):
            # Find the video file
            video_path = _find_video_file(video_dir, video_id)
            if not video_path:
                logger.warning("Video not found: %s", video_id)
                results[video_id] = {"status": "not_found"}
                continue

            # Check if already indexed
            try:
                check = client.get(f"/media/{video_id}")
                if check.status_code == 200:
                    status = check.json().get("processing_status", "")
                    if status == "completed":
                        logger.info("[%d/%d] Already indexed: %s", i + 1, len(video_ids), video_id)
                        results[video_id] = {"status": "already_indexed"}
                        continue
            except Exception:
                pass

            # Upload via API
            logger.info(
                "[%d/%d] Uploading %s (%s)...",
                i + 1,
                len(video_ids),
                video_id,
                _format_size(video_path.stat().st_size),
            )

            try:
                with open(video_path, "rb") as f:
                    response = client.post(
                        "/upload",
                        files={"file": (video_path.name, f, "video/mp4")},
                        data={"max_frames": str(max_frames), "preset": preset},
                    )

                if response.status_code == 200:
                    data = response.json()
                    results[video_id] = {
                        "status": "queued",
                        "media_id": data.get("media_id"),
                        "job_id": data.get("job_id"),
                    }
                    logger.info(
                        "  → Queued: media_id=%s, job_id=%s",
                        data.get("media_id"),
                        data.get("job_id"),
                    )
                else:
                    results[video_id] = {
                        "status": "upload_failed",
                        "error": response.text,
                    }
                    logger.error("  → Upload failed: %s", response.text[:200])

            except Exception as e:
                results[video_id] = {"status": "error", "error": str(e)}
                logger.error("  → Error: %s", e)

    return results


def index_videos_direct(
    video_dir: Path,
    benchmark_data_path: Path,
    max_frames: int = 20,
    preset: str = "balanced",
) -> dict:
    """Index benchmark videos directly via Celery tasks (bypasses API).

    Use this when running on the same machine as the backend services.
    Requires direct access to Azure Blob Storage and database.

    Args:
        video_dir: Directory containing video files.
        benchmark_data_path: Path to benchmark JSON.
        max_frames: Max frames per video.
        preset: FFmpeg preset.

    Returns:
        Dict mapping video_id -> processing result.
    """
    # Lazy imports to avoid loading backend deps when not needed
    try:
        from api.dependencies import get_blob_service, get_database_service
        from services.storage import get_storage_container_name
    except ImportError as e:
        logger.error("Backend services not available: %s", e)
        logger.info("Use --mode api to index via API instead.")
        sys.exit(1)

    entries = json.loads(benchmark_data_path.read_text())
    video_ids = sorted({e["video_id"] for e in entries if e.get("video_id")})
    logger.info("Found %d unique videos to index (direct mode)", len(video_ids))

    blob_service = get_blob_service()
    db = get_database_service()
    container_name = get_storage_container_name()

    results = {}

    for i, video_id in enumerate(video_ids):
        video_path = _find_video_file(video_dir, video_id)
        if not video_path:
            logger.warning("Video not found: %s", video_id)
            results[video_id] = {"status": "not_found"}
            continue

        # Check if already in DB
        try:
            existing = db.get_media(video_id)
            if existing and existing.get("processing_status") == "completed":
                logger.info("[%d/%d] Already indexed: %s", i + 1, len(video_ids), video_id)
                results[video_id] = {"status": "already_indexed"}
                continue
        except Exception:
            pass

        logger.info(
            "[%d/%d] Indexing %s (%s)...",
            i + 1,
            len(video_ids),
            video_id,
            _format_size(video_path.stat().st_size),
        )

        try:
            # 1. Upload to Azure Blob
            file_ext = video_path.suffix.lstrip(".")
            blob_name = f"{video_id}.{file_ext}"

            blob_client = blob_service.get_blob_client(
                container=container_name, blob=blob_name
            )
            with open(video_path, "rb") as f:
                blob_client.upload_blob(f, overwrite=True)

            file_size = video_path.stat().st_size

            # 2. Create DB entry
            media_data = {
                "id": video_id,
                "user_id": "eval_benchmark",
                "blob_name": blob_name,
                "original_filename": video_path.name,
                "media_type": "video",
                "file_size": file_size,
                "content_type": "video/mp4",
                "processing_status": "queued",
            }
            db.create_media(media_data)

            # 3. Queue Celery task
            from tasks.video_tasks import process_video_pipeline

            celery_config = {
                "max_frames": max_frames,
                "custom_prompt": None,
                "index_graph": True,
                "preset": preset,
            }
            async_result = process_video_pipeline.apply_async(
                args=[video_id, blob_name, celery_config]
            )

            results[video_id] = {
                "status": "queued",
                "media_id": video_id,
                "job_id": async_result.id,
            }
            logger.info("  → Queued: job_id=%s", async_result.id)

        except Exception as e:
            results[video_id] = {"status": "error", "error": str(e)}
            logger.error("  → Error: %s", e)

    return results


def monitor_indexing(results: dict, api_url: str = "http://localhost:8000", timeout: int = 3600):
    """Monitor indexing progress until all videos are processed.

    Args:
        results: Dict from index_videos_* with job_ids.
        api_url: QPrisma API URL.
        timeout: Max wait time in seconds.
    """
    import httpx

    queued = {
        vid: info
        for vid, info in results.items()
        if info.get("status") == "queued" and info.get("job_id")
    }

    if not queued:
        logger.info("No queued jobs to monitor")
        return

    logger.info("Monitoring %d jobs (timeout: %ds)...", len(queued), timeout)
    start = time.time()

    with httpx.Client(base_url=api_url, timeout=30) as client:
        while queued and (time.time() - start) < timeout:
            for vid, info in list(queued.items()):
                try:
                    resp = client.get(f"/jobs/{info['job_id']}")
                    if resp.status_code == 200:
                        status = resp.json().get("status", "")
                        progress = resp.json().get("progress", 0)

                        if status == "completed":
                            logger.info("  ✓ %s completed", vid)
                            results[vid]["status"] = "completed"
                            del queued[vid]
                        elif status == "failed":
                            logger.error("  ✗ %s failed", vid)
                            results[vid]["status"] = "failed"
                            del queued[vid]
                        else:
                            logger.debug("  ... %s: %s (%d%%)", vid, status, progress)
                except Exception:
                    pass

            if queued:
                time.sleep(15)

    if queued:
        logger.warning("%d jobs still pending after timeout", len(queued))


# =============================================================================
# Helpers
# =============================================================================


def _find_video_file(video_dir: Path, video_id: str) -> Path | None:
    """Find video file by ID, trying multiple extensions and subdirectories."""
    for ext in [".mp4", ".mkv", ".webm", ".avi", ".mov"]:
        # Direct match
        candidate = video_dir / f"{video_id}{ext}"
        if candidate.exists():
            return candidate

        # With subdirectories (e.g., short/, medium/, long/)
        for subdir in video_dir.iterdir():
            if subdir.is_dir():
                candidate = subdir / f"{video_id}{ext}"
                if candidate.exists():
                    return candidate

    return None


def _format_size(size_bytes: int) -> str:
    """Format file size as human-readable string."""
    for unit in ["B", "KB", "MB", "GB"]:
        if size_bytes < 1024:
            return f"{size_bytes:.1f}{unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f}TB"


# =============================================================================
# CLI
# =============================================================================


def main():
    parser = argparse.ArgumentParser(
        description="Index benchmark videos through QPrisma's processing pipeline"
    )
    parser.add_argument(
        "--benchmark",
        type=str,
        required=True,
        help="Benchmark name (used to find data file)",
    )
    parser.add_argument(
        "--video-dir",
        type=str,
        required=True,
        help="Directory containing video files",
    )
    parser.add_argument(
        "--data-path",
        type=str,
        help="Path to benchmark JSON (default: data/benchmarks/{benchmark}/{benchmark}.json)",
    )
    parser.add_argument(
        "--mode",
        choices=["api", "direct"],
        default="api",
        help="Indexing mode: 'api' (via HTTP) or 'direct' (via Celery)",
    )
    parser.add_argument(
        "--api-url",
        type=str,
        default="http://localhost:8000",
        help="QPrisma API URL (for api mode)",
    )
    parser.add_argument(
        "--token",
        type=str,
        help="JWT auth token (for api mode)",
    )
    parser.add_argument(
        "--max-frames",
        type=int,
        default=20,
        help="Max frames to extract per video",
    )
    parser.add_argument(
        "--preset",
        choices=["fast", "balanced", "quality"],
        default="balanced",
        help="FFmpeg extraction preset",
    )
    parser.add_argument(
        "--monitor",
        action="store_true",
        help="Monitor processing progress after indexing",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=3600,
        help="Monitoring timeout in seconds",
    )
    parser.add_argument("-v", "--verbose", action="store_true")

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    video_dir = Path(args.video_dir)
    if not video_dir.exists():
        logger.error("Video directory not found: %s", video_dir)
        sys.exit(1)

    data_path = Path(
        args.data_path or f"data/benchmarks/{args.benchmark}/{args.benchmark}.json"
    )
    if not data_path.exists():
        logger.error(
            "Benchmark data not found at %s. Run download_benchmarks.py first.",
            data_path,
        )
        sys.exit(1)

    # Index videos
    if args.mode == "api":
        results = index_videos_via_api(
            video_dir=video_dir,
            benchmark_data_path=data_path,
            api_url=args.api_url,
            max_frames=args.max_frames,
            preset=args.preset,
            user_token=args.token,
        )
    else:
        results = index_videos_direct(
            video_dir=video_dir,
            benchmark_data_path=data_path,
            max_frames=args.max_frames,
            preset=args.preset,
        )

    # Save results
    output_path = Path(f"data/benchmarks/{args.benchmark}/indexing_results.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(results, indent=2))

    # Summary
    statuses = {}
    for vid, info in results.items():
        s = info.get("status", "unknown")
        statuses[s] = statuses.get(s, 0) + 1

    logger.info("Indexing summary: %s", statuses)

    # Monitor if requested
    if args.monitor:
        monitor_indexing(results, args.api_url, args.timeout)


if __name__ == "__main__":
    main()
