"""Emit a Foundry-compatible eval data file from a Video-MME manifest (V2).

Reads:

* the :class:`evaluation_foundry.benchmarks.BenchmarkManifest` written by
  :mod:`evaluation_foundry.benchmarks.video_mme.ingest`, and
* the Video-MME questions parquet (``lmms-lab/Video-MME``) staged under
  ``data/datasets/_private/video_mme/``.

Builds one row per (question x subtitle_mode) using the **verbatim
Video-MME prompt template** the upstream leaderboard expects::

    Question: <question>
    A. <opt_a>
    B. <opt_b>
    C. <opt_c>
    D. <opt_d>
    Respond with only the letter (A, B, C, or D) of the correct option.
    The best answer is:

The query is wrapped with the existing ``[QPRISMA_CONTEXT:{user_id, media_ids}]``
envelope (already parsed by the agent) and an additive
``[QPRISMA_BENCH:{eval_mode, format, with_subtitles, duration_bucket}]``
envelope (additive; non-benchmark code paths ignore it).

Per-row schema::

    {"query": "...", "ground_truth": "C", "metadata": {...}}

Output format is selected by the ``--out`` suffix:

* ``.json`` writes a single wrapped object
  ``{"name": ..., "evaluators": [...], "data": [<rows>]}`` matching what
  ``microsoft/ai-agent-evals`` reads via ``json.loads(data_path.read_text())``.
  This is the format used by the Video-MME GitHub Actions workflows.
* ``.jsonl`` writes one row per line (legacy / local tooling).

Any other suffix is rejected so callers fail fast instead of silently
producing a file the upstream action cannot parse.
"""

from __future__ import annotations

import argparse
import json
import logging
import random
import sys
from collections import defaultdict
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

from evaluation_foundry.benchmarks.video_mme.file_validation import (
    build_parquet_read_error,
    validate_staged_dataset_file,
)

logger = logging.getLogger(__name__)

# Verbatim from Video-MME paper Appendix / lmms-eval implementation. Do NOT edit
# without bumping the benchmark version — leaderboard comparability depends on
# this exact wording.
PROMPT_TEMPLATE = (
    "Question: {question}\n"
    "A. {opt_a}\n"
    "B. {opt_b}\n"
    "C. {opt_c}\n"
    "D. {opt_d}\n"
    "Respond with only the letter (A, B, C, or D) of the correct option.\n"
    "The best answer is:"
)


def _load_questions(path: Path) -> list[dict[str, Any]]:
    suffix = path.suffix.lower()
    if suffix == ".parquet":
        validate_staged_dataset_file(path, label="Video-MME questions file")
        try:
            import pyarrow as pa  # type: ignore[import-not-found]
            import pyarrow.parquet as pq  # type: ignore[import-not-found]
        except ImportError as e:  # pragma: no cover
            raise RuntimeError(
                "Reading parquet requires `pyarrow`; install or pre-convert to JSONL."
            ) from e
        try:
            return pq.read_table(path).to_pylist()
        except pa.ArrowException as e:
            raise RuntimeError(
                build_parquet_read_error(path, label="Video-MME questions file", detail=str(e))
            ) from e
    if suffix == ".jsonl":
        validate_staged_dataset_file(path, label="Video-MME questions file")
        return [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    if suffix == ".json":
        validate_staged_dataset_file(path, label="Video-MME questions file")
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, list):
            return raw
        questions = raw.get("questions")
        if questions is not None:
            return questions
        rows = raw.get("rows")
        if rows is not None:
            return rows
        videos = raw.get("videos")
        if videos is not None:
            return videos
        return []
    raise ValueError(f"Unsupported questions format: {path.suffix}")


def _qprisma_envelopes(
    *, user_id: str, media_id: str, with_subtitles: bool, duration_bucket: str
) -> str:
    ctx = json.dumps({"user_id": user_id, "media_ids": [media_id]}, separators=(",", ":"))
    bench = json.dumps(
        {
            "eval_mode": "mcq",
            "format": "letter_only",
            "with_subtitles": with_subtitles,
            "duration_bucket": duration_bucket,
        },
        separators=(",", ":"),
    )
    return f"[QPRISMA_CONTEXT:{ctx}][QPRISMA_BENCH:{bench}]"


def _build_query(
    *,
    question_row: dict[str, Any],
    user_id: str,
    media_id: str,
    duration_bucket: str,
    with_subtitles: bool,
) -> str:
    options = question_row.get("options") or [
        question_row.get("option_a") or question_row.get("A"),
        question_row.get("option_b") or question_row.get("B"),
        question_row.get("option_c") or question_row.get("C"),
        question_row.get("option_d") or question_row.get("D"),
    ]
    if len(options) < 4 or any(o is None for o in options[:4]):
        raise ValueError(f"Malformed question row (need 4 options): {question_row}")

    body = PROMPT_TEMPLATE.format(
        question=str(question_row.get("question", "")).strip(),
        opt_a=str(options[0]).strip(),
        opt_b=str(options[1]).strip(),
        opt_c=str(options[2]).strip(),
        opt_d=str(options[3]).strip(),
    )
    envelope = _qprisma_envelopes(
        user_id=user_id,
        media_id=media_id,
        with_subtitles=with_subtitles,
        duration_bucket=duration_bucket,
    )
    return f"{envelope}\n{body}"


def emit_rows(
    *,
    manifest_path: Path,
    questions_path: Path,
    subtitle_modes: Sequence[str],
) -> Iterable[dict[str, Any]]:
    """Yield Foundry input rows. ``subtitle_modes`` is ``("with",)``, ``("without",)``, or both."""
    from evaluation_foundry.benchmarks import BenchmarkManifest

    manifest = BenchmarkManifest.read(manifest_path)
    media_by_video: dict[str, str] = {v.benchmark_video_id: v.media_id for v in manifest.videos}
    bucket_by_video: dict[str, str] = {
        v.benchmark_video_id: (v.duration_bucket or "unknown") for v in manifest.videos
    }
    user_id = manifest.user_id

    for q in _load_questions(questions_path):
        video_id = str(q.get("video_id") or q.get("videoID") or q.get("id") or "").strip()
        if not video_id or video_id not in media_by_video:
            continue
        media_id = media_by_video[video_id]
        bucket = bucket_by_video.get(video_id, "unknown")
        gt = str(q.get("answer") or q.get("ground_truth") or "").strip().upper()
        if gt not in {"A", "B", "C", "D"}:
            logger.warning("Skipping question with bad ground_truth=%r", gt)
            continue
        for mode in subtitle_modes:
            with_subs = mode == "with"
            try:
                query = _build_query(
                    question_row=q,
                    user_id=user_id,
                    media_id=media_id,
                    duration_bucket=bucket,
                    with_subtitles=with_subs,
                )
            except ValueError as e:
                logger.warning("Skipping malformed question: %s", e)
                continue
            yield {
                "query": query,
                "ground_truth": gt,
                "metadata": {
                    "benchmark": manifest.name,
                    "benchmark_name": manifest.name,
                    "benchmark_video_id": video_id,
                    "media_id": media_id,
                    "duration_bucket": bucket,
                    "with_subtitles": with_subs,
                    "domain": q.get("domain"),
                    "sub_category": q.get("sub_category") or q.get("subfield"),
                    "question_id": q.get("question_id") or q.get("qid"),
                },
            }


DEFAULT_EVAL_NAME = "video-mme"
DEFAULT_EVALUATORS: tuple[str, ...] = ("qprisma.video_mme_mcq",)


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m evaluation_foundry.benchmarks.video_mme.emit_foundry_data",
        description=(
            "Emit a Foundry evaluation data file from a Video-MME manifest + "
            "questions file. Writes a single Foundry-compatible JSON object "
            "(name/evaluators/data) when --out ends in .json, or one row per "
            "line when --out ends in .jsonl."
        ),
    )
    p.add_argument("--manifest", type=Path, required=True)
    p.add_argument("--questions", type=Path, required=True)
    p.add_argument(
        "--subtitle-modes",
        nargs="+",
        default=["with", "without"],
        choices=["with", "without"],
    )
    p.add_argument("--out", type=Path, required=True)
    p.add_argument(
        "--limit",
        type=int,
        default=0,
        help="If >0, randomly subsample at most N rows stratified by duration_bucket.",
    )
    p.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed used by --limit stratified sampling.",
    )
    p.add_argument(
        "--name",
        default=DEFAULT_EVAL_NAME,
        help=(
            "Dataset name written into the Foundry JSON wrapper "
            f"(default: {DEFAULT_EVAL_NAME}). Ignored for .jsonl output."
        ),
    )
    p.add_argument(
        "--evaluators",
        nargs="+",
        default=list(DEFAULT_EVALUATORS),
        help=(
            "Foundry evaluator names referenced by the dataset wrapper "
            f"(default: {' '.join(DEFAULT_EVALUATORS)}). Ignored for .jsonl "
            "output."
        ),
    )
    return p


def _stratified_sample(rows: list[dict[str, Any]], limit: int, seed: int) -> list[dict[str, Any]]:
    """Stratify by metadata.duration_bucket, sample up to ``limit`` rows total."""
    if limit <= 0 or len(rows) <= limit:
        return rows
    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        bucket = (r.get("metadata") or {}).get("duration_bucket") or "unknown"
        buckets[bucket].append(r)
    rng = random.Random(seed)  # noqa: S311 - deterministic stratified sampling, not crypto
    per_bucket = max(1, limit // max(1, len(buckets)))
    selected: list[dict[str, Any]] = []
    for bucket_rows in buckets.values():
        rng.shuffle(bucket_rows)
        selected.extend(bucket_rows[:per_bucket])
    if len(selected) > limit:
        rng.shuffle(selected)
        selected = selected[:limit]
    return selected


def main(argv: Sequence[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    args = _build_parser().parse_args(argv)
    args.out.parent.mkdir(parents=True, exist_ok=True)

    rows = list(
        emit_rows(
            manifest_path=args.manifest,
            questions_path=args.questions,
            subtitle_modes=args.subtitle_modes,
        )
    )
    if args.limit > 0:
        before = len(rows)
        rows = _stratified_sample(rows, args.limit, args.seed)
        logger.info("Stratified --limit %d: %d -> %d rows", args.limit, before, len(rows))

    suffix = args.out.suffix.lower()
    if suffix == ".json":
        payload = {
            "name": args.name,
            "evaluators": list(args.evaluators),
            "data": rows,
        }
        args.out.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        logger.info(
            "Wrote Foundry JSON (%d rows, evaluators=%s) to %s",
            len(rows),
            payload["evaluators"],
            args.out,
        )
    elif suffix == ".jsonl":
        with args.out.open("w", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        logger.info("Wrote %d JSONL rows to %s", len(rows), args.out)
    else:
        raise SystemExit(f"--out must end in .json or .jsonl, got: {args.out.name!r}")
    return 0 if rows else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
