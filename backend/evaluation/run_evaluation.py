"""
Master evaluation orchestrator for QPrisma.

Entry point that ties together:
1. Benchmark loading (Video-MME, MLVU)
2. Method adapters (QPrisma configs + baselines)
3. Answer generation runner
4. Metric computation (accuracy, retrieval, temporal, faithfulness, efficiency)
5. LLM judge evaluation (win-rate + quantitative)
6. Batch pipeline for judge calls
7. Final results aggregation and reporting

Usage:
    python -m evaluation.run_evaluation --config eval_config.json
    python -m evaluation.run_evaluation --benchmark video_mme --methods qprisma-full naive-rag
"""

import argparse
import asyncio
import json
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path

from evaluation.adapters.base import BaseMethodAdapter
from evaluation.adapters.baseline_adapters import (
    ExternalAPIAdapter,
    NaiveRAGAdapter,
    UniformBaselineAdapter,
)
from evaluation.adapters.qprisma_adapter import QPrismaAdapter
from evaluation.models.eval_schemas import (
    AggregatedResults,
    BenchmarkConfig,
    BenchmarkEntry,
    EvalConfig,
    EvalResult,
)
from evaluation.runner import EvaluationRunner

logger = logging.getLogger(__name__)

# =============================================================================
# Adapter Registry
# =============================================================================

ADAPTER_REGISTRY: dict[str, type] = {}


def _build_adapter(method_name: str) -> BaseMethodAdapter:
    """Create an adapter instance from a method name string."""
    # QPrisma ablation configs
    if method_name.startswith("qprisma-"):
        config = method_name.replace("qprisma-", "")
        return QPrismaAdapter(config_name=config)

    # Baselines
    match method_name:
        case "uniform-8":
            return UniformBaselineAdapter(num_frames=8)
        case "uniform-16":
            return UniformBaselineAdapter(num_frames=16)
        case "uniform-32":
            return UniformBaselineAdapter(num_frames=32)
        case "naive-rag":
            return NaiveRAGAdapter()
        case "openai-gpt-4o":
            return ExternalAPIAdapter(provider="openai", model="gpt-4o")
        case "gemini-1.5-pro":
            return ExternalAPIAdapter(provider="gemini", model="gemini-1.5-pro")
        case _:
            raise ValueError(
                f"Unknown method: {method_name}. "
                f"QPrisma configs: qprisma-{{full,noagent,flat,vectoronly,norerank,"
                f"visualonly,audioonly,fixedtokens}}. "
                f"Baselines: uniform-{{8,16,32}}, naive-rag, openai-gpt-4o, gemini-1.5-pro"
            )


# =============================================================================
# Benchmark Loading
# =============================================================================


def _load_benchmark(config: BenchmarkConfig) -> list[BenchmarkEntry]:
    """Load benchmark entries from a config."""
    match config.name:
        case "video_mme" | "video-mme":
            from evaluation.benchmarks import video_mme_loader

            return video_mme_loader.load_from_json(config.data_path)
        case "mlvu":
            from evaluation.benchmarks import mlvu_loader

            return mlvu_loader.load_from_directory(config.data_path)
        case _:
            # Try generic JSON loading
            path = Path(config.data_path)
            if path.suffix == ".json":
                data = json.loads(path.read_text(encoding="utf-8"))
                return [BenchmarkEntry.model_validate(e) for e in data]
            raise ValueError(f"Unknown benchmark: {config.name}")


# =============================================================================
# Metric Computation
# =============================================================================


def compute_all_metrics(
    results: list[EvalResult],
    entries: list[BenchmarkEntry],
    method_name: str,
    benchmark_name: str,
    efficiency_summary: dict | None = None,
) -> AggregatedResults:
    """Compute all applicable metrics for a set of results.

    Automatically detects which metrics are applicable based on
    the data (e.g., MC accuracy only for MC questions, temporal
    metrics only when ground truth segments exist).
    """
    from evaluation.metrics import (
        compute_accuracy,
        compute_accuracy_by_duration_tier,
        compute_accuracy_by_group,
        mean_iou,
        timestamp_mae,
    )

    # Build lookup: question_id -> entry
    entry_map = {e.question_id: e for e in entries}

    agg = AggregatedResults(
        method=method_name,
        benchmark=benchmark_name,
        total_questions=len(results),
    )

    # --- MC Accuracy ---
    mc_results = [
        r for r in results
        if r.predicted_choice and entry_map.get(r.question_id, None)
        and entry_map[r.question_id].correct_answer
    ]
    mc_entries = [entry_map[r.question_id] for r in mc_results]

    if mc_results:
        agg.accuracy = compute_accuracy(mc_results, mc_entries)

        # By duration tier
        has_tiers = any(e.duration_tier for e in mc_entries)
        if has_tiers:
            agg.accuracy_by_tier = compute_accuracy_by_group(
                mc_results, mc_entries, "duration_tier"
            )

        # By category
        has_categories = any(e.category for e in mc_entries)
        if has_categories:
            agg.accuracy_by_category = compute_accuracy_by_group(
                mc_results, mc_entries, "category"
            )

    # --- Temporal Metrics ---
    temporal_results = [
        r for r in results
        if r.predicted_timestamps
        and entry_map.get(r.question_id)
        and entry_map[r.question_id].ground_truth_segments
    ]

    if temporal_results:
        pred_segments = []
        gt_segments = []
        for r in temporal_results:
            entry = entry_map[r.question_id]
            # Convert timestamps to segments (point -> small window)
            pred_segs = [(t, t + 1.0) for t in (r.predicted_timestamps or [])]
            pred_segments.append(pred_segs)
            gt_segments.append(entry.ground_truth_segments or [])

        if pred_segments and gt_segments:
            agg.mean_iou = mean_iou(
                [s for segs in pred_segments for s in segs],
                [s for segs in gt_segments for s in segs],
            )

        # Timestamp MAE
        pred_ts = [t for r in temporal_results for t in (r.predicted_timestamps or [])]
        gt_ts = [
            s[0]
            for r in temporal_results
            for s in (entry_map[r.question_id].ground_truth_segments or [])
        ]
        if pred_ts and gt_ts:
            min_len = min(len(pred_ts), len(gt_ts))
            agg.timestamp_mae = timestamp_mae(pred_ts[:min_len], gt_ts[:min_len])

    # --- Efficiency ---
    if efficiency_summary:
        agg.avg_latency_ms = efficiency_summary.get("latency_mean_ms")
        agg.p95_latency_ms = efficiency_summary.get("latency_p95_ms")
        agg.avg_cost_usd = efficiency_summary.get("cost_mean_usd")
        agg.avg_tokens = efficiency_summary.get("tokens_mean")

    return agg


# =============================================================================
# Judge Pipeline
# =============================================================================


async def run_judge_pipeline(
    results_by_method: dict[str, list[EvalResult]],
    entries: list[BenchmarkEntry],
    config: EvalConfig,
    output_dir: Path,
) -> dict[str, dict]:
    """Run the LLM judge pipeline (win-rate + quantitative).

    Uses the batch API for cost efficiency (50% savings).
    """
    baseline_method = config.baseline_method
    baseline_results = results_by_method.get(baseline_method, [])

    if not baseline_results:
        logger.warning("No baseline results for %s, skipping judge pipeline", baseline_method)
        return {}

    judge_results = {}

    for method_name, method_results in results_by_method.items():
        if method_name == baseline_method:
            continue

        logger.info("Judging %s vs %s", method_name, baseline_method)

        # Build answer pairs
        baseline_map = {r.question_id: r for r in baseline_results}
        pairs = []
        for r in method_results:
            base_r = baseline_map.get(r.question_id)
            if base_r:
                entry = next(
                    (e for e in entries if e.question_id == r.question_id), None
                )
                if entry:
                    pairs.append((entry, r, base_r))

        if not pairs:
            logger.warning("No matching pairs for %s vs %s", method_name, baseline_method)
            continue

        try:
            if config.use_batch_api:
                judge_results[method_name] = await _run_batch_judge(
                    pairs, method_name, baseline_method, config, output_dir
                )
            else:
                judge_results[method_name] = await _run_online_judge(
                    pairs, method_name, baseline_method, config
                )
        except Exception as e:
            logger.error("Judge pipeline failed for %s: %s", method_name, e)
            judge_results[method_name] = {"error": str(e)}

    return judge_results


async def _run_batch_judge(
    pairs: list[tuple],
    method_name: str,
    baseline_method: str,
    config: EvalConfig,
    output_dir: Path,
) -> dict:
    """Run judge via OpenAI Batch API."""
    from evaluation.batch_pipeline.batch_calculate import (
        calculate_quantitative_scores,
        calculate_winrates,
    )
    from evaluation.batch_pipeline.batch_download import download_batch_results
    from evaluation.batch_pipeline.batch_parse import parse_batch_results
    from evaluation.batch_pipeline.batch_upload import (
        upload_quantitative_batch,
        upload_winrate_batch,
    )

    entries = [p[0] for p in pairs]
    method_answers = [p[1].answer for p in pairs]
    baseline_answers = [p[2].answer for p in pairs]

    # Upload win-rate batch
    winrate_batch_id = await upload_winrate_batch(
        questions=[e.question for e in entries],
        answers_a=method_answers,
        answers_b=baseline_answers,
        method_a=method_name,
        method_b=baseline_method,
        num_runs=config.num_runs,
        model=config.judge_model,
    )

    # Upload quantitative batch
    quant_batch_id = await upload_quantitative_batch(
        questions=[e.question for e in entries],
        test_answers=method_answers,
        baseline_answers=baseline_answers,
        method_name=method_name,
        baseline_name=baseline_method,
        num_runs=config.num_runs,
        model=config.judge_model,
    )

    # Wait for both batches
    logger.info("Waiting for batch jobs: winrate=%s, quant=%s", winrate_batch_id, quant_batch_id)
    winrate_raw = await download_batch_results(winrate_batch_id)
    quant_raw = await download_batch_results(quant_batch_id)

    # Parse responses
    winrate_parsed = parse_batch_results(winrate_raw, "winrate")
    quant_parsed = parse_batch_results(quant_raw, "quantitative")

    # Calculate final scores
    winrates = calculate_winrates(winrate_parsed, method_name, baseline_method)
    quant_scores = calculate_quantitative_scores(quant_parsed)

    # Save raw judge outputs
    judge_dir = output_dir / "judges" / method_name
    judge_dir.mkdir(parents=True, exist_ok=True)
    (judge_dir / "winrate_raw.json").write_text(json.dumps(winrate_raw, indent=2, default=str), encoding="utf-8")
    (judge_dir / "quant_raw.json").write_text(json.dumps(quant_raw, indent=2, default=str), encoding="utf-8")
    (judge_dir / "winrate_results.json").write_text(json.dumps(winrates, indent=2), encoding="utf-8")
    (judge_dir / "quant_results.json").write_text(json.dumps(quant_scores, indent=2), encoding="utf-8")

    return {"winrates": winrates, "quantitative": quant_scores}


async def _run_online_judge(
    pairs: list[tuple],
    method_name: str,
    baseline_method: str,
    config: EvalConfig,
) -> dict:
    """Run judge via direct API calls (non-batch, higher cost)."""
    from evaluation.judges.llm_judge import LLMJudge

    judge = LLMJudge(model=config.judge_model)

    winrate_results = []
    quant_results = []

    for entry, method_result, baseline_result in pairs:
        try:
            wr = await judge.judge_winrate(
                question=entry.question,
                answer_a=method_result.answer,
                answer_b=baseline_result.answer,
            )
            winrate_results.append(wr)
        except (RuntimeError, ValueError) as e:
            logger.warning("Winrate judge failed for %s: %s", entry.question_id, e)

        try:
            qt = await judge.judge_quantitative(
                question=entry.question,
                test_answer=method_result.answer,
                baseline_answer=baseline_result.answer,
            )
            quant_results.append(qt)
        except (RuntimeError, ValueError) as e:
            logger.warning("Quantitative judge failed for %s: %s", entry.question_id, e)

    return {
        "winrate_results": [r.model_dump() if hasattr(r, "model_dump") else r for r in winrate_results],
        "quant_results": [r.model_dump() if hasattr(r, "model_dump") else r for r in quant_results],
    }


# =============================================================================
# Report Generation
# =============================================================================


def generate_report(
    aggregated: dict[str, AggregatedResults],
    judge_results: dict,
    output_dir: Path,
    benchmark_name: str,
) -> str:
    """Generate a markdown evaluation report."""
    lines = [
        f"# QPrisma Evaluation Report: {benchmark_name}",
        "",
        f"**Methods evaluated:** {len(aggregated)}",
        "",
    ]

    # Accuracy table
    has_accuracy = any(a.accuracy is not None for a in aggregated.values())
    if has_accuracy:
        lines.extend([
            "## MC Accuracy",
            "",
            "| Method | Overall | Short | Medium | Long |",
            "|--------|---------|-------|--------|------|",
        ])
        for method, agg in sorted(aggregated.items()):
            if agg.accuracy is not None:
                tiers = agg.accuracy_by_tier or {}
                lines.append(
                    f"| {method} | {agg.accuracy:.1%} "
                    f"| {tiers.get('short', 0):.1%} "
                    f"| {tiers.get('medium', 0):.1%} "
                    f"| {tiers.get('long', 0):.1%} |"
                )
        lines.append("")

    # Efficiency table
    has_efficiency = any(a.avg_latency_ms is not None for a in aggregated.values())
    if has_efficiency:
        lines.extend([
            "## Efficiency",
            "",
            "| Method | Avg Latency (ms) | P95 Latency (ms) | Avg Cost ($) | Avg Tokens |",
            "|--------|-------------------|-------------------|--------------|------------|",
        ])
        for method, agg in sorted(aggregated.items()):
            if agg.avg_latency_ms is not None:
                lines.append(
                    f"| {method} "
                    f"| {agg.avg_latency_ms:,.0f} "
                    f"| {agg.p95_latency_ms:,.0f} "
                    f"| ${agg.avg_cost_usd or 0:.4f} "
                    f"| {agg.avg_tokens or 0:,.0f} |"
                )
        lines.append("")

    # Judge results
    if judge_results:
        lines.extend([
            "## LLM Judge Results",
            "",
        ])
        for method, jr in judge_results.items():
            if isinstance(jr, dict) and "winrates" in jr:
                lines.append(f"### {method}")
                lines.append("")
                winrates = jr["winrates"]
                if isinstance(winrates, dict):
                    lines.append("**Win Rates (vs baseline):**")
                    lines.append("")
                    for dim, rate in winrates.items():
                        if isinstance(rate, (int, float)):
                            lines.append(f"- {dim}: {rate:.1%}")
                    lines.append("")

            if isinstance(jr, dict) and "quantitative" in jr:
                quant = jr["quantitative"]
                if isinstance(quant, dict):
                    lines.append("**Quantitative Scores (1-5, 3=baseline):**")
                    lines.append("")
                    for dim, score in quant.items():
                        if isinstance(score, (int, float)):
                            lines.append(f"- {dim}: {score:.2f}")
                    lines.append("")

    report = "\n".join(lines)

    # Save report
    report_path = output_dir / benchmark_name / "REPORT.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding="utf-8")
    logger.info("Report saved to %s", report_path)

    return report


# =============================================================================
# Main Orchestrator
# =============================================================================


async def run_evaluation(config: EvalConfig, fresh: bool = False) -> dict:
    """Main evaluation orchestration function.

    Runs the full pipeline:
    1. Load benchmarks
    2. Create adapters
    3. Generate answers
    4. Compute metrics
    5. Run LLM judges
    6. Aggregate and report

    Args:
        config: Evaluation configuration.
        fresh: If True, create a timestamped subdirectory for this run.
    """
    base_dir = Path(config.output_dir)
    if fresh:
        run_id = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        output_dir = base_dir / f"run_{run_id}"
        logger.info("Fresh run: %s", output_dir)
    else:
        output_dir = base_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    # Save config for reproducibility
    (output_dir / "eval_config.json").write_text(config.model_dump_json(indent=2), encoding="utf-8")

    all_aggregated = {}
    all_judge_results = {}

    for bench_config in config.benchmarks:
        logger.info("=== Benchmark: %s ===", bench_config.name)

        # 1. Load benchmark entries
        entries = _load_benchmark(bench_config)
        logger.info("Loaded %d entries from %s", len(entries), bench_config.name)

        # 2. Create adapters
        adapters = [_build_adapter(m.name) for m in config.methods]
        logger.info("Methods: %s", [a.name for a in adapters])

        # 3. Generate answers
        runner = EvaluationRunner(
            output_dir=str(output_dir / "answers"),
            max_concurrent=3,
            resume=not fresh,
        )
        results_by_method = await runner.run_all_methods(
            adapters=adapters,
            entries=entries,
            video_dir=bench_config.video_dir,
            benchmark_name=bench_config.name,
        )

        # 4. Compute metrics per method
        for method_name, results in results_by_method.items():
            efficiency = runner.tracker.summarize(method_name)
            agg = compute_all_metrics(
                results=results,
                entries=entries,
                method_name=method_name,
                benchmark_name=bench_config.name,
                efficiency_summary=efficiency,
            )
            all_aggregated[f"{bench_config.name}/{method_name}"] = agg

            # Save per-method aggregated results
            agg_path = output_dir / bench_config.name / f"{method_name}_metrics.json"
            agg_path.parent.mkdir(parents=True, exist_ok=True)
            agg_path.write_text(agg.model_dump_json(indent=2), encoding="utf-8")

        # 5. Run LLM judge pipeline
        judge_results = await run_judge_pipeline(
            results_by_method=results_by_method,
            entries=entries,
            config=config,
            output_dir=output_dir,
        )
        all_judge_results[bench_config.name] = judge_results

        # 6. Generate report
        bench_aggregated = {
            k.split("/")[1]: v
            for k, v in all_aggregated.items()
            if k.startswith(f"{bench_config.name}/")
        }
        generate_report(bench_aggregated, judge_results, output_dir, bench_config.name)

    # Save final combined results
    final = {
        "aggregated": {k: v.model_dump() for k, v in all_aggregated.items()},
        "judge_results": all_judge_results,
    }
    (output_dir / "final_results.json").write_text(json.dumps(final, indent=2, default=str), encoding="utf-8")

    return final


# =============================================================================
# CLI
# =============================================================================


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="QPrisma Evaluation Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run with a config file
  python -m evaluation.run_evaluation --config eval_config.json

  # Quick run: Video-MME with QPrisma vs NaiveRAG
  python -m evaluation.run_evaluation \\
    --benchmark video_mme \\
    --data-path data/video_mme.json \\
    --video-dir data/videos/video_mme \\
    --methods qprisma-full naive-rag \\
    --output-dir evaluation/results

  # Ablation study
  python -m evaluation.run_evaluation \\
    --benchmark video_mme \\
    --data-path data/video_mme.json \\
    --video-dir data/videos/video_mme \\
    --methods qprisma-full qprisma-noagent qprisma-flat qprisma-norerank \\
    --output-dir evaluation/results/ablation
""",
    )

    parser.add_argument("--config", type=str, help="Path to eval config JSON file")
    parser.add_argument("--benchmark", type=str, help="Benchmark name (video_mme, mlvu)")
    parser.add_argument("--data-path", type=str, help="Path to benchmark data file/directory")
    parser.add_argument("--video-dir", type=str, help="Path to video files directory")
    parser.add_argument("--methods", nargs="+", help="Method names to evaluate")
    parser.add_argument(
        "--output-dir", type=str, default="evaluation/results", help="Output directory"
    )
    parser.add_argument("--judge-model", type=str, default="gpt-4o", help="LLM judge model")
    parser.add_argument("--num-runs", type=int, default=5, help="Number of judge runs")
    parser.add_argument(
        "--no-batch", action="store_true", help="Disable batch API for judge calls"
    )
    parser.add_argument(
        "--skip-judge", action="store_true", help="Skip LLM judge evaluation"
    )
    parser.add_argument(
        "--fresh",
        action="store_true",
        help="Force a fresh run with timestamped output (ignore cached results)",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose logging")

    return parser.parse_args()


def build_config_from_args(args: argparse.Namespace) -> EvalConfig:
    """Build an EvalConfig from CLI arguments."""
    from evaluation.models.eval_schemas import BenchmarkConfig, MethodConfig

    if args.config:
        config_path = Path(args.config)
        return EvalConfig.model_validate_json(config_path.read_text(encoding="utf-8"))

    if not args.benchmark or not args.data_path or not args.methods:
        print(
            "Error: --benchmark, --data-path, and --methods required when not using --config",
            file=sys.stderr,
        )
        sys.exit(1)

    benchmarks = [
        BenchmarkConfig(
            name=args.benchmark,
            data_path=args.data_path,
            video_dir=args.video_dir or "",
        )
    ]

    methods = [
        MethodConfig(
            name=m,
            display_name=m,
            is_baseline=m in ("naive-rag", "uniform-16"),
        )
        for m in args.methods
    ]

    # Determine baseline (first baseline method or naive-rag)
    baseline = "naive-rag"
    for m in methods:
        if m.is_baseline:
            baseline = m.name
            break

    return EvalConfig(
        benchmarks=benchmarks,
        methods=methods,
        baseline_method=baseline,
        judge_model=args.judge_model,
        num_runs=args.num_runs,
        use_batch_api=not args.no_batch,
        output_dir=args.output_dir,
    )


def main():
    args = parse_args()

    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    config = build_config_from_args(args)

    logger.info("Starting QPrisma evaluation pipeline")
    logger.info("Benchmarks: %s", [b.name for b in config.benchmarks])
    logger.info("Methods: %s", [m.name for m in config.methods])
    logger.info("Output: %s", config.output_dir)

    results = asyncio.run(run_evaluation(config, fresh=args.fresh))

    # Print summary
    print("\n" + "=" * 60)
    print("EVALUATION COMPLETE")
    print("=" * 60)

    aggregated = results.get("aggregated", {})
    for key, agg in aggregated.items():
        print(f"\n{key}:")
        if agg.get("accuracy") is not None:
            print(f"  Accuracy: {agg['accuracy']:.1%}")
        if agg.get("avg_latency_ms") is not None:
            print(f"  Avg Latency: {agg['avg_latency_ms']:,.0f}ms")

    print(f"\nFull results: {config.output_dir}/")


if __name__ == "__main__":
    main()
