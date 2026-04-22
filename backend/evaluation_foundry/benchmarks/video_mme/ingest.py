"""Video-MME ingest adapter (V1).

Replays the production media-upload path from
``backend/api/routes/media_routes.py:140-237`` programmatically against a
benchmark user (default ``user_7541242e88e3``), so the agent indexes Video-MME
videos exactly like a customer upload — frames in Blob, embeddings in Postgres,
scenes/entities in Neo4j, retrieval cache warm in Redis.

Idempotency
-----------
Skips any ``(user_id, benchmark_name="video_mme", benchmark_video_id)`` already
present in PostgreSQL, so re-running after a partial failure resumes safely.

Smoke vs full
-------------
Use ``--limit N --stratify-by duration_bucket --seed 42`` for a smoke run
before paying for ~900 ingests (V0 in the plan). The same script handles the
full ingest when ``--limit`` is omitted.

License
-------
Video-MME is academic-only. Videos are NEVER auto-downloaded by this script;
they must be staged by the operator into ``data/datasets/_private/video_mme/``
per ``data/datasets/_private/README.md``.

Example
-------
::

    python -m evaluation_foundry.benchmarks.video_mme.ingest \
           --user-id user_7541242e88e3 \
           --videos-dir data/datasets/_private/video_mme/videos \
           --metadata data/datasets/_private/video_mme/metadata.parquet \
           --preset benchmark --limit 5 --stratify-by duration_bucket --seed 42
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import random
import sys
import time
import uuid
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from evaluation_foundry.benchmarks.video_mme.file_validation import (
    build_parquet_read_error,
    validate_staged_dataset_file,
)

logger = logging.getLogger(__name__)

BENCHMARK_NAME = "video_mme"
DEFAULT_USER_ID = "user_7541242e88e3"
DEFAULT_PRESET = "benchmark"
DEFAULT_POLL_INTERVAL_S = 10
DEFAULT_TIMEOUT_S = 60 * 60  # 1h per video upper bound

VALID_VIDEO_EXTS = {"mp4", "avi", "mov", "mkv", "webm"}


# ---------------------------------------------------------------------------
# Metadata loading
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class VideoMMERecord:
    """One row of Video-MME metadata required for ingest.

    Per the upstream ``lmms-lab/Video-MME`` dataset, every video has a stable
    ``video_id`` and a duration bucket of ``short`` / ``medium`` / ``long``.
    Question rows are emitted later by the companion emitter; this adapter
    only needs the per-video metadata.
    """

    video_id: str
    duration_bucket: str
    filename: str  # e.g. "<video_id>.mp4"
    domain: str | None = None
    sub_category: str | None = None


def _load_metadata(path: Path) -> list[VideoMMERecord]:
    """Load Video-MME metadata from a parquet/jsonl/json/csv file.

    The upstream HuggingFace dataset ships parquet, but operators may pre-stage
    a smaller jsonl/json/csv file when they only have a subset locally. We
    accept all four to keep the ingest flexible.
    """
    suffix = path.suffix.lower()
    if suffix == ".parquet":
        validate_staged_dataset_file(path, label="Video-MME metadata")
        try:
            import pyarrow as pa  # type: ignore[import-not-found]
            import pyarrow.parquet as pq  # type: ignore[import-not-found]
        except ImportError as e:  # pragma: no cover - operator environment issue
            raise RuntimeError(
                "Reading parquet metadata requires `pyarrow`. "
                "Install with `uv add pyarrow` or pre-convert to JSONL."
            ) from e
        try:
            table = pq.read_table(path)
        except pa.ArrowException as e:
            raise RuntimeError(
                build_parquet_read_error(path, label="Video-MME metadata", detail=str(e))
            ) from e
        rows = table.to_pylist()
    elif suffix == ".jsonl":
        validate_staged_dataset_file(path, label="Video-MME metadata")
        rows = [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    elif suffix == ".json":
        validate_staged_dataset_file(path, label="Video-MME metadata")
        raw = json.loads(path.read_text(encoding="utf-8"))
        rows = raw if isinstance(raw, list) else raw.get("videos", [])
    elif suffix == ".csv":
        validate_staged_dataset_file(path, label="Video-MME metadata")
        import csv

        with path.open(newline="", encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
    else:
        raise ValueError(f"Unsupported metadata format: {path.suffix}")

    records: dict[str, VideoMMERecord] = {}
    for row in rows:
        # Upstream column names vary; accept the common aliases.
        video_id = str(row.get("video_id") or row.get("videoID") or row.get("id") or "").strip()
        if not video_id:
            continue
        duration_bucket = (
            str(
                row.get("duration_bucket")
                or row.get("duration")
                or row.get("duration_category")
                or "unknown"
            )
            .strip()
            .lower()
        )
        filename = str(row.get("filename") or row.get("video_file") or f"{video_id}.mp4").strip()
        # One record per video — Video-MME has multiple Q rows per video.
        if video_id in records:
            continue
        records[video_id] = VideoMMERecord(
            video_id=video_id,
            duration_bucket=duration_bucket,
            filename=filename,
            domain=row.get("domain"),
            sub_category=row.get("sub_category") or row.get("subfield"),
        )
    return list(records.values())


# ---------------------------------------------------------------------------
# Stratified sampling (smoke runs)
# ---------------------------------------------------------------------------


def stratified_sample(
    records: Sequence[VideoMMERecord],
    *,
    limit: int | None,
    stratify_by: str | None,
    seed: int,
) -> list[VideoMMERecord]:
    """Stratified-sample ``limit`` records by ``stratify_by`` (or random).

    For ``stratify_by="duration_bucket"`` and ``limit=5`` we get roughly even
    coverage across short/medium/long, which is what V0 needs.
    """
    if limit is None or limit >= len(records):
        return list(records)

    rng = random.Random(seed)  # noqa: S311 - deterministic benchmark sampling, not crypto
    if not stratify_by:
        sample = list(records)
        rng.shuffle(sample)
        return sample[:limit]

    buckets: dict[str, list[VideoMMERecord]] = defaultdict(list)
    for r in records:
        key = getattr(r, stratify_by, "unknown") or "unknown"
        buckets[str(key)].append(r)
    for v in buckets.values():
        rng.shuffle(v)

    chosen: list[VideoMMERecord] = []
    bucket_keys = sorted(buckets.keys())
    while len(chosen) < limit and any(buckets[k] for k in bucket_keys):
        for k in bucket_keys:
            if buckets[k] and len(chosen) < limit:
                chosen.append(buckets[k].pop())
    return chosen


# ---------------------------------------------------------------------------
# Ingest
# ---------------------------------------------------------------------------


def _existing_benchmark_media_ids(db: Any, user_id: str) -> dict[str, str]:
    """Return ``{benchmark_video_id: media_id}`` for already-ingested videos.

    Uses a narrow raw-SQL query via the engine to fetch only the ``id`` and
    ``benchmark_video_id`` columns needed to build this lookup map. The DB
    service now has benchmark-aware helpers, but this avoids hydrating full
    ORM rows for a read-only CLI lookup.
    """
    from sqlalchemy import text

    out: dict[str, str] = {}
    with db.engine.connect() as conn:
        result = conn.execute(
            text(
                "SELECT id, benchmark_video_id FROM media "
                "WHERE user_id = :uid AND benchmark_name = :bname"
            ),
            {"uid": user_id, "bname": BENCHMARK_NAME},
        )
        for row in result:
            out[str(row.benchmark_video_id)] = str(row.id)
    return out


def _wait_for_processing(
    db: Any,
    media_id: str,
    *,
    timeout_s: int,
    poll_interval_s: int,
) -> str:
    """Block until the Celery pipeline reports terminal status.

    Returns the final ``processing_status`` (e.g. ``completed``, ``failed``).
    """
    deadline = time.monotonic() + timeout_s
    last_status = "unknown"
    while time.monotonic() < deadline:
        media = db.get_media(media_id)
        if media is None:
            time.sleep(poll_interval_s)
            continue
        last_status = getattr(media, "processing_status", "unknown") or "unknown"
        if last_status in {"completed", "failed", "error"}:
            return last_status
        time.sleep(poll_interval_s)
    return last_status


def ingest_records(
    records: Iterable[VideoMMERecord],
    *,
    videos_dir: Path,
    user_id: str,
    preset: str | None,
    max_frames: int | None,
    poll_interval_s: int,
    timeout_s: int,
    container_name: str | None = None,
) -> list[dict[str, Any]]:
    """Run the upload+process flow for every record. Returns ingest summaries."""
    # Imported lazily so `--help` works without backend deps installed.
    from api.dependencies import get_blob_service, get_storage_container_name
    from services.database_service import get_database_service
    from tasks.video_tasks import process_video_pipeline

    db = get_database_service()
    blob_service = get_blob_service()
    if blob_service is None:
        raise RuntimeError("Azure Blob Storage is not configured (BLOB env vars missing).")
    container = container_name or get_storage_container_name()

    existing = _existing_benchmark_media_ids(db, user_id)
    summaries: list[dict[str, Any]] = []

    for rec in records:
        if rec.video_id in existing:
            media_id = existing[rec.video_id]
            logger.info("Skipping %s — already ingested as media_id=%s", rec.video_id, media_id)
            summaries.append(
                {
                    "benchmark_video_id": rec.video_id,
                    "media_id": media_id,
                    "duration_bucket": rec.duration_bucket,
                    "status": "skipped_existing",
                }
            )
            continue

        video_path = videos_dir / rec.filename
        if not video_path.is_file():
            logger.warning("Missing video file %s — skipping", video_path)
            summaries.append(
                {
                    "benchmark_video_id": rec.video_id,
                    "media_id": None,
                    "duration_bucket": rec.duration_bucket,
                    "status": "missing_file",
                    "path": str(video_path),
                }
            )
            continue

        media_id = str(uuid.uuid4())
        ext = video_path.suffix.lstrip(".").lower() or "mp4"
        if ext not in VALID_VIDEO_EXTS:
            logger.warning("Unsupported extension %s for %s — skipping", ext, video_path)
            summaries.append(
                {
                    "benchmark_video_id": rec.video_id,
                    "media_id": None,
                    "duration_bucket": rec.duration_bucket,
                    "status": "unsupported_ext",
                    "path": str(video_path),
                }
            )
            continue
        blob_name = f"{media_id}.{ext}"

        # Stream-upload to Blob (mirrors media_routes.py:170-178).
        blob_client = blob_service.get_blob_client(container=container, blob=blob_name)
        file_size = video_path.stat().st_size
        with video_path.open("rb") as fh:
            blob_client.upload_blob(fh, overwrite=True, length=file_size or None)

        # Persist Postgres row with benchmark provenance.
        media_data = {
            "id": media_id,
            "user_id": user_id,
            "blob_name": blob_name,
            "original_filename": video_path.name,
            "media_type": "video",
            "file_size": file_size,
            "content_type": f"video/{ext}",
            "processing_status": "queued",
            "benchmark_name": BENCHMARK_NAME,
            "benchmark_video_id": rec.video_id,
            "benchmark_split": rec.duration_bucket,
        }
        db.create_media(media_data)

        # Dispatch the same Celery task the API uses.
        celery_config = {
            "max_frames": max_frames,
            "custom_prompt": None,
            "index_graph": True,
            "preset": preset,
        }
        async_result = process_video_pipeline.apply_async(args=[media_id, blob_name, celery_config])
        db.update_media(media_id, {"job_id": async_result.id})

        logger.info(
            "Dispatched %s (bucket=%s) as media_id=%s job_id=%s",
            rec.video_id,
            rec.duration_bucket,
            media_id,
            async_result.id,
        )

        final_status = _wait_for_processing(
            db,
            media_id,
            timeout_s=timeout_s,
            poll_interval_s=poll_interval_s,
        )
        summaries.append(
            {
                "benchmark_video_id": rec.video_id,
                "media_id": media_id,
                "duration_bucket": rec.duration_bucket,
                "job_id": async_result.id,
                "status": final_status,
            }
        )
        # Surface failures immediately but do not abort the whole batch.
        if final_status != "completed":
            logger.error(
                "Video %s ended with status=%s — continuing with next record",
                rec.video_id,
                final_status,
            )

    # Make `asyncio` import side-effect explicit for linters.
    return summaries


# ---------------------------------------------------------------------------
# Manifest assembly
# ---------------------------------------------------------------------------


def _dataset_hash(summaries: Sequence[dict[str, Any]]) -> str:
    payload = json.dumps(
        sorted(
            (
                {
                    "benchmark_video_id": s["benchmark_video_id"],
                    "media_id": s.get("media_id"),
                    "duration_bucket": s.get("duration_bucket"),
                }
                for s in summaries
                if s.get("media_id")
            ),
            key=lambda r: r["benchmark_video_id"],
        ),
        sort_keys=True,
    )
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def write_manifest(
    summaries: Sequence[dict[str, Any]],
    *,
    out_path: Path,
    user_id: str,
    version: str,
    judge_model: str,
    judge_temperature: float,
    n_judge_runs: int,
    frame_sampling_fps: float | None,
    max_frames: int | None,
    subtitle_mode: str | None,
    agent_commit_sha: str | None,
) -> Path:
    """Write the BenchmarkManifest to ``out_path`` and return the path."""
    from evaluation_foundry.benchmarks import BenchmarkManifest, BenchmarkVideo

    videos = [
        BenchmarkVideo(
            benchmark_video_id=s["benchmark_video_id"],
            media_id=s["media_id"],
            duration_bucket=s.get("duration_bucket"),
            extra={"status": s.get("status"), "job_id": s.get("job_id")},
        )
        for s in summaries
        if s.get("media_id")
    ]
    manifest = BenchmarkManifest(
        name=BENCHMARK_NAME,
        version=version,
        license="academic-only-no-redistribution",
        user_id=user_id,
        eval_mode="mcq",
        format="letter_only",
        judge_model=judge_model,
        n_judge_runs=n_judge_runs,
        judge_temperature=judge_temperature,
        frame_sampling_fps=frame_sampling_fps,
        max_frames=max_frames,
        subtitle_mode=subtitle_mode,
        agent_commit_sha=agent_commit_sha,
        dataset_hash=_dataset_hash(summaries),
        videos=videos,
    )
    manifest.write(out_path)
    return out_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m evaluation_foundry.benchmarks.video_mme.ingest",
        description="Ingest Video-MME videos into QPrisma against a benchmark user.",
    )
    p.add_argument("--user-id", default=DEFAULT_USER_ID)
    p.add_argument("--videos-dir", type=Path, required=True)
    p.add_argument("--metadata", type=Path, required=True)
    p.add_argument("--preset", default=DEFAULT_PRESET)
    p.add_argument("--max-frames", type=int, default=None)
    p.add_argument("--limit", type=int, default=None, help="Smoke-run cap (omit for full).")
    p.add_argument("--stratify-by", default="duration_bucket")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument(
        "--manifest-out",
        type=Path,
        default=Path("data/datasets/_private/video_mme/manifest.json"),
    )
    p.add_argument("--version", default="lmms-lab/Video-MME@main")
    p.add_argument("--judge-model", default="")
    p.add_argument("--judge-temperature", type=float, default=0.0)
    p.add_argument("--n-judge-runs", type=int, default=1)
    p.add_argument("--frame-sampling-fps", type=float, default=None)
    p.add_argument("--subtitle-mode", default=None, choices=["with", "without", None])
    p.add_argument("--agent-commit-sha", default=None)
    p.add_argument("--poll-interval-s", type=int, default=DEFAULT_POLL_INTERVAL_S)
    p.add_argument("--timeout-s", type=int, default=DEFAULT_TIMEOUT_S)
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Resolve the sample and print what would be ingested; do not call Blob/Celery.",
    )
    return p


def main(argv: Sequence[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    args = _build_parser().parse_args(argv)

    if not args.metadata.is_file():
        logger.error("Metadata file not found: %s", args.metadata)
        return 2
    if not args.videos_dir.is_dir():
        logger.error("Videos dir not found: %s", args.videos_dir)
        return 2

    records = _load_metadata(args.metadata)
    sampled = stratified_sample(
        records, limit=args.limit, stratify_by=args.stratify_by, seed=args.seed
    )
    logger.info(
        "Loaded %d Video-MME records, sampled %d (limit=%s, stratify_by=%s, seed=%d)",
        len(records),
        len(sampled),
        args.limit,
        args.stratify_by,
        args.seed,
    )

    if args.dry_run:
        for rec in sampled:
            logger.info(
                "[dry-run] would ingest video_id=%s bucket=%s file=%s",
                rec.video_id,
                rec.duration_bucket,
                rec.filename,
            )
        return 0

    summaries = ingest_records(
        sampled,
        videos_dir=args.videos_dir,
        user_id=args.user_id,
        preset=args.preset,
        max_frames=args.max_frames,
        poll_interval_s=args.poll_interval_s,
        timeout_s=args.timeout_s,
    )
    manifest_path = write_manifest(
        summaries,
        out_path=args.manifest_out,
        user_id=args.user_id,
        version=args.version,
        judge_model=args.judge_model,
        judge_temperature=args.judge_temperature,
        n_judge_runs=args.n_judge_runs,
        frame_sampling_fps=args.frame_sampling_fps,
        max_frames=args.max_frames,
        subtitle_mode=args.subtitle_mode,
        agent_commit_sha=args.agent_commit_sha,
    )
    completed = sum(1 for s in summaries if s.get("status") == "completed")
    logger.info(
        "Ingest finished: %d completed / %d sampled. Manifest: %s",
        completed,
        len(summaries),
        manifest_path,
    )
    return 0 if completed == len(summaries) else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
