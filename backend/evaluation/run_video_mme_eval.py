"""
End-to-end Video-MME evaluation orchestrator for QPrisma.

Automates the full pipeline: authenticate → discover/download/upload videos
→ run evaluation → compute metrics → generate report.

Usage:
    cd backend
    python -m evaluation.run_video_mme_eval \\
        --api-url https://ca-qprisma-api-dev.lemoncoast-87c1f692.westeurope.azurecontainerapps.io \\
        --subset short --max-videos 12
"""

import argparse
import asyncio
import json
import logging
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

import httpx

from evaluation.adapters.remote_adapter import (
    RemoteDirectSearchAdapter,
    RemoteQPrismaAdapter,
    get_auth_token,
)
from evaluation.benchmarks.video_mme_loader import load_from_huggingface, load_from_json
from evaluation.metrics.accuracy import (
    compute_accuracy,
    compute_accuracy_by_group,
)
from evaluation.models.eval_schemas import BenchmarkEntry, EvalResult
from evaluation.runner import EvaluationRunner
from evaluation.services.video_preparation import VideoPreparationService

logger = logging.getLogger(__name__)

BENCHMARK_JSON_PATH = Path("data/benchmarks/video_mme/video_mme.json")
DEFAULT_OUTPUT_DIR = "evaluation/results/video_mme"
DEFAULT_VIDEO_DIR = "evaluation/data/videos"
DEFAULT_MAPPING_PATH = "evaluation/data/video_mme_id_mapping.json"


# =============================================================================
# Phase 1: Setup
# =============================================================================


async def phase_setup(args: argparse.Namespace) -> tuple[str, list[BenchmarkEntry]]:
    """Authenticate and load benchmark data.

    Returns:
        Tuple of (JWT token, list of benchmark entries).
    """
    api_url = args.api_url
    email = args.email or os.getenv("QPRISMA_EVAL_EMAIL", "")
    password = args.password or os.getenv("QPRISMA_EVAL_PASSWORD", "")

    if not email or not password:
        logger.error(
            "Credentials required: set --email/--password or QPRISMA_EVAL_EMAIL/QPRISMA_EVAL_PASSWORD"
        )
        sys.exit(1)

    # Health check
    logger.info("Checking API health at %s ...", api_url)
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(f"{api_url}/health")
            resp.raise_for_status()
            logger.info("API is healthy: %s", resp.json().get("status", "ok"))
    except httpx.HTTPError as e:
        logger.error("API health check failed: %s", e)
        sys.exit(1)

    # Authenticate
    logger.info("Authenticating as %s ...", email)
    try:
        token = await get_auth_token(api_url, email, password)
        logger.info("Authentication successful")
    except httpx.HTTPStatusError as e:
        logger.error("Authentication failed: HTTP %d", e.response.status_code)
        sys.exit(1)

    # Load benchmark data
    entries = _load_benchmark(args)
    logger.info(
        "Loaded %d benchmark entries (subset=%s, max_videos=%d)",
        len(entries),
        args.subset,
        args.max_videos,
    )

    return token, entries


def _load_benchmark(args: argparse.Namespace) -> list[BenchmarkEntry]:
    """Load and filter Video-MME benchmark entries.

    Always ensures YouTube IDs are present (needed for video discovery
    and ID mapping, not just downloading).
    """
    entries: list[BenchmarkEntry] = []

    # Try local JSON first
    if BENCHMARK_JSON_PATH.exists():
        entries = load_from_json(BENCHMARK_JSON_PATH)

    # Check if local data has YouTube IDs (needed for mapping)
    has_youtube_ids = any((e.metadata or {}).get("youtube_id") for e in entries)

    # Load from HuggingFace when YouTube IDs are missing
    if not has_youtube_ids:
        logger.info(
            "Local benchmark lacks YouTube IDs — loading from HuggingFace "
            "(required for video discovery and mapping)..."
        )
        entries = load_from_huggingface()

    if not entries:
        logger.info("No local data, loading from HuggingFace...")
        entries = load_from_huggingface()

    # Filter by duration tier
    if args.subset != "all":
        entries = [e for e in entries if e.duration_tier and e.duration_tier.value == args.subset]

    # Limit number of videos
    if args.max_videos > 0:
        video_ids = sorted({e.video_id for e in entries})
        selected_videos = set(video_ids[: args.max_videos])
        entries = [e for e in entries if e.video_id in selected_videos]

    return entries


# =============================================================================
# Phase 2: Video Preparation
# =============================================================================


async def phase_prepare_videos(
    args: argparse.Namespace,
    token: str,
    entries: list[BenchmarkEntry],
) -> dict[str, str]:
    """Discover, download, upload, and index required videos.

    Returns:
        Dict mapping YouTube ID → QPrisma media UUID.
    """
    # Extract unique YouTube IDs from benchmark entries
    youtube_ids = _extract_youtube_ids(entries)
    logger.info("Need %d unique videos for evaluation", len(youtube_ids))

    async with VideoPreparationService(
        api_url=args.api_url,
        token=token,
        video_dir=args.video_dir,
        mapping_path=args.mapping_path,
    ) as prep:
        mapping = await prep.prepare_videos(
            required_youtube_ids=list(youtube_ids.keys()),
            skip_upload=args.skip_upload,
        )

    return mapping


def _extract_youtube_ids(entries: list[BenchmarkEntry]) -> dict[str, str]:
    """Extract YouTube ID → Video-MME video_id mapping from entries.

    Returns:
        Dict mapping YouTube ID → Video-MME video_id (e.g., "001").
    """
    yt_map: dict[str, str] = {}
    for entry in entries:
        yt_id = (entry.metadata or {}).get("youtube_id")
        if yt_id:
            yt_map[str(yt_id)] = entry.video_id
        else:
            # Fallback: use video_id as YouTube ID
            yt_map[entry.video_id] = entry.video_id
    return yt_map


# =============================================================================
# Phase 3: Evaluation
# =============================================================================


async def phase_evaluate(
    args: argparse.Namespace,
    token: str,
    entries: list[BenchmarkEntry],
    id_mapping: dict[str, str],
) -> dict[str, list[EvalResult]]:
    """Run evaluation methods on the benchmark entries.

    Returns:
        Dict mapping method name → list of EvalResult.
    """
    # Remap video IDs from Video-MME to QPrisma UUIDs
    yt_to_vmme = _extract_youtube_ids(entries)
    vmme_to_uuid: dict[str, str] = {}
    for yt_id, uuid_val in id_mapping.items():
        vmme_id = yt_to_vmme.get(yt_id, yt_id)
        vmme_to_uuid[vmme_id] = uuid_val

    remapped_entries = _remap_entries(entries, vmme_to_uuid)
    if not remapped_entries:
        logger.error("No entries could be remapped to QPrisma UUIDs")
        sys.exit(1)

    logger.info(
        "Remapped %d/%d entries to QPrisma UUIDs",
        len(remapped_entries),
        len(entries),
    )

    # Build adapters
    adapters = [
        RemoteQPrismaAdapter(api_url=args.api_url, token=token),
    ]
    if not args.skip_baseline:
        adapters.append(RemoteDirectSearchAdapter(api_url=args.api_url, token=token))

    # Run evaluation
    runner = EvaluationRunner(
        output_dir=args.output_dir,
        max_concurrent=args.concurrency,
        resume=not args.fresh,
    )

    results = await runner.run_all_methods(
        adapters=adapters,
        entries=remapped_entries,
        benchmark_name="video-mme",
    )

    return results


def _remap_entries(
    entries: list[BenchmarkEntry],
    vmme_to_uuid: dict[str, str],
) -> list[BenchmarkEntry]:
    """Replace Video-MME video_ids with QPrisma UUIDs."""
    remapped = []
    for entry in entries:
        uuid_val = vmme_to_uuid.get(entry.video_id)
        if uuid_val:
            remapped.append(entry.model_copy(update={"video_id": uuid_val}))
        else:
            logger.debug(
                "Skipping %s: no UUID for video %s",
                entry.question_id,
                entry.video_id,
            )
    return remapped


# =============================================================================
# Phase 4: Metrics & Reporting
# =============================================================================


def phase_report(
    args: argparse.Namespace,
    entries: list[BenchmarkEntry],
    results: dict[str, list[EvalResult]],
) -> None:
    """Compute metrics and generate evaluation report."""
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    report_lines = [
        "# QPrisma Video-MME Evaluation Report",
        f"\n**Date:** {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}",
        f"**API:** `{args.api_url}`",
        f"**Subset:** {args.subset} | **Max videos:** {args.max_videos}",
        f"**Total questions evaluated:** {len(entries)}",
        "",
    ]

    all_metrics: dict[str, dict] = {}

    for method_name, method_results in results.items():
        logger.info("Computing metrics for %s...", method_name)

        # Filter to successful results
        valid = [r for r in method_results if r.error is None]
        errors = [r for r in method_results if r.error is not None]

        # MC accuracy
        accuracy = compute_accuracy(valid, entries)
        acc_by_category = compute_accuracy_by_group(valid, entries, "category")
        acc_by_tier = compute_accuracy_by_group(valid, entries, "duration_tier")
        acc_by_domain = compute_accuracy_by_group(valid, entries, "domain")

        # Efficiency
        latencies = [r.latency_ms for r in valid if r.latency_ms]
        avg_latency = sum(latencies) / len(latencies) if latencies else 0
        tool_calls_list = [r.tool_calls for r in valid if r.tool_calls is not None]
        avg_tools = sum(tool_calls_list) / len(tool_calls_list) if tool_calls_list else 0

        metrics = {
            "method": method_name,
            "total_questions": len(method_results),
            "successful": len(valid),
            "errors": len(errors),
            "accuracy": round(accuracy, 4),
            "accuracy_by_category": acc_by_category,
            "accuracy_by_duration_tier": acc_by_tier,
            "accuracy_by_domain": acc_by_domain,
            "avg_latency_ms": round(avg_latency, 1),
            "avg_tool_calls": round(avg_tools, 2),
        }
        all_metrics[method_name] = metrics

        # Add to report
        report_lines.extend(
            [
                f"## {method_name}",
                "",
                "| Metric | Value |",
                "|--------|-------|",
                f"| Overall Accuracy | **{accuracy:.1%}** |",
                f"| Questions | {len(valid)}/{len(method_results)} successful |",
                f"| Avg Latency | {avg_latency:.0f}ms |",
                f"| Avg Tool Calls | {avg_tools:.1f} |",
                "",
            ]
        )

        if acc_by_category:
            report_lines.append("### Accuracy by Category\n")
            report_lines.append("| Category | Accuracy |")
            report_lines.append("|----------|----------|")
            for cat, acc in sorted(acc_by_category.items()):
                report_lines.append(f"| {cat} | {acc:.1%} |")
            report_lines.append("")

        if acc_by_tier:
            report_lines.append("### Accuracy by Duration Tier\n")
            report_lines.append("| Tier | Accuracy |")
            report_lines.append("|------|----------|")
            for tier, acc in sorted(acc_by_tier.items()):
                report_lines.append(f"| {tier} | {acc:.1%} |")
            report_lines.append("")

        if acc_by_domain:
            report_lines.append("### Accuracy by Domain\n")
            report_lines.append("| Domain | Accuracy |")
            report_lines.append("|--------|----------|")
            for domain, acc in sorted(acc_by_domain.items()):
                report_lines.append(f"| {domain} | {acc:.1%} |")
            report_lines.append("")

    # Comparison table (if multiple methods)
    if len(all_metrics) > 1:
        report_lines.extend(
            [
                "## Method Comparison",
                "",
                "| Method | Accuracy | Avg Latency | Avg Tools |",
                "|--------|----------|-------------|-----------|",
            ]
        )
        for name, m in all_metrics.items():
            report_lines.append(
                f"| {name} | {m['accuracy']:.1%} | {m['avg_latency_ms']:.0f}ms | {m['avg_tool_calls']:.1f} |"
            )
        report_lines.append("")

    # Save report
    report_path = output_dir / "EVALUATION_REPORT.md"
    report_path.write_text("\n".join(report_lines), encoding="utf-8")
    logger.info("Report saved to %s", report_path)

    # Save metrics JSON
    metrics_path = output_dir / "metrics.json"
    metrics_path.write_text(json.dumps(all_metrics, indent=2), encoding="utf-8")
    logger.info("Metrics saved to %s", metrics_path)


# =============================================================================
# CLI & Main
# =============================================================================


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="End-to-end Video-MME evaluation for QPrisma",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Quick test (12 short videos)
  python -m evaluation.run_video_mme_eval --subset short --max-videos 12

  # Re-run with already indexed videos
  python -m evaluation.run_video_mme_eval --skip-upload --subset short

  # Full Video-MME benchmark
  python -m evaluation.run_video_mme_eval --subset all --max-videos 900
        """,
    )
    parser.add_argument(
        "--api-url",
        default=os.getenv("QPRISMA_API_URL", ""),
        help="QPrisma API URL (default: $QPRISMA_API_URL)",
    )
    parser.add_argument(
        "--email",
        default=os.getenv("QPRISMA_EVAL_EMAIL"),
        help="Auth email (default: $QPRISMA_EVAL_EMAIL)",
    )
    parser.add_argument(
        "--password",
        default=os.getenv("QPRISMA_EVAL_PASSWORD"),
        help="Auth password (default: $QPRISMA_EVAL_PASSWORD)",
    )
    parser.add_argument(
        "--subset",
        choices=["short", "medium", "long", "all"],
        default="short",
        help="Video-MME duration tier to evaluate (default: short)",
    )
    parser.add_argument(
        "--max-videos",
        type=int,
        default=12,
        help="Maximum number of videos to evaluate (default: 12)",
    )
    parser.add_argument(
        "--skip-upload",
        action="store_true",
        help="Skip video download/upload (use existing indexed videos only)",
    )
    parser.add_argument(
        "--skip-baseline",
        action="store_true",
        help="Skip the direct-search baseline comparison",
    )
    parser.add_argument(
        "--skip-judge",
        action="store_true",
        help="Skip LLM judge evaluation (not yet implemented)",
    )
    parser.add_argument(
        "--fresh",
        action="store_true",
        help="Ignore cached results and re-run everything",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=3,
        help="Max concurrent API calls per method (default: 3)",
    )
    parser.add_argument(
        "--output-dir",
        default=DEFAULT_OUTPUT_DIR,
        help=f"Output directory for results (default: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--video-dir",
        default=DEFAULT_VIDEO_DIR,
        help=f"Directory for downloaded videos (default: {DEFAULT_VIDEO_DIR})",
    )
    parser.add_argument(
        "--mapping-path",
        default=DEFAULT_MAPPING_PATH,
        help=f"Path to ID mapping file (default: {DEFAULT_MAPPING_PATH})",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable debug logging",
    )

    args = parser.parse_args(argv)

    if not args.api_url:
        parser.error("--api-url is required (or set QPRISMA_API_URL)")

    return args


async def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)

    # Configure logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    logger.info("=" * 60)
    logger.info("QPrisma Video-MME Evaluation Pipeline")
    logger.info("=" * 60)
    logger.info("API: %s", args.api_url)
    logger.info("Subset: %s | Max videos: %d", args.subset, args.max_videos)
    logger.info("")

    # Phase 1: Setup
    logger.info("Phase 1/4: Setup")
    token, entries = await phase_setup(args)

    if not entries:
        logger.error("No benchmark entries match the filters")
        sys.exit(1)

    # Phase 2: Video Preparation
    logger.info("Phase 2/4: Video Preparation")
    id_mapping = await phase_prepare_videos(args, token, entries)

    if not id_mapping:
        logger.error("No videos available for evaluation")
        sys.exit(1)

    # Phase 3: Evaluation
    logger.info("Phase 3/4: Evaluation")
    results = await phase_evaluate(args, token, entries, id_mapping)

    # Phase 4: Metrics & Reporting
    logger.info("Phase 4/4: Metrics & Reporting")
    phase_report(args, entries, results)

    logger.info("")
    logger.info("=" * 60)
    logger.info("Evaluation complete! Results in: %s", args.output_dir)
    logger.info("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
