"""
Answer generation runner for QPrisma evaluation.

Runs each method adapter on a set of benchmark questions, collects
EvalResult objects, tracks efficiency, and persists results to disk
for reproducibility. Supports resumable runs (skips already-generated answers).
"""

import asyncio
import json
import logging
import os
from pathlib import Path

from evaluation.adapters.base import BaseMethodAdapter
from evaluation.metrics.efficiency import EfficiencyRecord, EfficiencyTracker
from evaluation.models.eval_schemas import BenchmarkEntry, EvalResult

logger = logging.getLogger(__name__)

SUMMARY_FILENAME = "_summary.json"
RUN_SUMMARY_FILENAME = "_run_summary.json"
SUPPORTED_VIDEO_EXTENSIONS = [".mp4", ".mkv", ".webm", ".avi"]


class EvaluationRunner:
    """Runs method adapters on benchmark entries and collects results.

    Handles:
    - Sequential or concurrent answer generation per method
    - Efficiency tracking (latency, tokens, cost)
    - Result persistence to disk (JSON per question)
    - Resumable runs: skips questions with existing answers
    """

    def __init__(
        self,
        output_dir: str = "evaluation/results",
        max_concurrent: int = 3,  # Conservative default to avoid API rate limits
        resume: bool = True,
    ):
        """
        Args:
            output_dir: Directory to save answer files.
            max_concurrent: Max concurrent answer generations per method.
            resume: If True, skip questions that already have saved answers.
        """
        self.output_dir = Path(output_dir)
        self.max_concurrent = max_concurrent
        self.resume = resume
        self.tracker = EfficiencyTracker()

    async def run_method(
        self,
        adapter: BaseMethodAdapter,
        entries: list[BenchmarkEntry],
        video_dir: str | None = None,
        benchmark_name: str = "unknown",
    ) -> list[EvalResult]:
        """Run a single method on all benchmark entries.

        Args:
            adapter: The method adapter to evaluate.
            entries: List of benchmark questions.
            video_dir: Base directory containing video files.
            benchmark_name: Name of the benchmark for file organization.

        Returns:
            List of EvalResult for each question.
        """
        method_dir = self.output_dir / benchmark_name / adapter.name
        method_dir.mkdir(parents=True, exist_ok=True)

        logger.info(
            "Running %s on %d questions (benchmark: %s, resume=%s)",
            adapter.display_name,
            len(entries),
            benchmark_name,
            self.resume,
        )

        # Setup adapter
        await adapter.setup()

        # Filter out already-completed questions if resuming
        pending_entries = entries
        completed_results = []

        if self.resume:
            pending_entries = []
            for entry in entries:
                result_path = method_dir / f"{entry.question_id}.json"
                if result_path.exists():
                    try:
                        saved = EvalResult.model_validate_json(result_path.read_text(encoding="utf-8"))
                        completed_results.append(saved)
                        continue
                    except (json.JSONDecodeError, ValueError) as e:
                        logger.warning(
                            "Corrupted result file %s, will re-run: %s",
                            result_path,
                            e,
                        )
                pending_entries.append(entry)

            if completed_results:
                logger.info(
                    "Resuming: %d/%d already completed for %s",
                    len(completed_results),
                    len(entries),
                    adapter.name,
                )

        # Run pending entries with bounded concurrency
        semaphore = asyncio.Semaphore(self.max_concurrent)
        new_results = await asyncio.gather(
            *[
                self._run_single(adapter, entry, video_dir, method_dir, semaphore)
                for entry in pending_entries
            ],
            return_exceptions=True,
        )

        # Collect results, handling any exceptions
        all_results = list(completed_results)
        for i, result in enumerate(new_results):
            if isinstance(result, Exception):
                entry = pending_entries[i]
                logger.error(
                    "Unhandled error for %s on %s: %s",
                    adapter.name,
                    entry.question_id,
                    result,
                )
                # Create error result
                error_result = EvalResult(
                    question_id=entry.question_id,
                    method=adapter.name,
                    answer=f"Error: {result}",
                    error=str(result),
                )
                all_results.append(error_result)
            else:
                all_results.append(result)

        # Teardown adapter
        await adapter.teardown()

        logger.info(
            "Completed %s: %d results (%d errors)",
            adapter.name,
            len(all_results),
            sum(1 for r in all_results if r.error is not None),
        )

        return all_results

    async def _run_single(
        self,
        adapter: BaseMethodAdapter,
        entry: BenchmarkEntry,
        video_dir: str | None,
        method_dir: Path,
        semaphore: asyncio.Semaphore,
    ) -> EvalResult:
        """Run a single question through the adapter with efficiency tracking."""
        async with semaphore:
            video_path = None
            if video_dir and entry.video_id:
                video_path = self._resolve_video_path(video_dir, entry.video_id)

            with self.tracker.measure(entry.question_id, adapter.name) as record:
                result = await adapter.generate_answer(entry, video_path)
                # Populate efficiency record from result
                record.tokens_input = result.tokens_used or 0
                record.cost_usd = result.cost_usd or 0.0
                record.tool_calls = result.tool_calls or 0

            # Save result to disk (UTF-8 for Unicode safety on Windows)
            result_path = method_dir / f"{entry.question_id}.json"
            result_path.write_text(result.model_dump_json(indent=2), encoding="utf-8")

            return result

    async def run_all_methods(
        self,
        adapters: list[BaseMethodAdapter],
        entries: list[BenchmarkEntry],
        video_dir: str | None = None,
        benchmark_name: str = "unknown",
    ) -> dict[str, list[EvalResult]]:
        """Run all methods on the benchmark entries.

        Methods run sequentially (each adapter may have its own rate limits).

        Returns:
            Dict mapping method name -> list of EvalResult.
        """
        results = {}
        for adapter in adapters:
            method_results = await self.run_method(
                adapter, entries, video_dir, benchmark_name
            )
            results[adapter.name] = method_results

        # Save combined results summary
        self._save_summary(results, benchmark_name)

        return results

    def load_results(
        self,
        method_name: str,
        benchmark_name: str,
    ) -> list[EvalResult]:
        """Load previously saved results from disk.

        Args:
            method_name: Method identifier.
            benchmark_name: Benchmark name.

        Returns:
            List of EvalResult loaded from saved JSON files.
        """
        method_dir = self.output_dir / benchmark_name / method_name
        results = []

        if not method_dir.exists():
            return results

        for json_file in sorted(method_dir.glob("*.json")):
            if json_file.name == SUMMARY_FILENAME:
                continue
            try:
                result = EvalResult.model_validate_json(json_file.read_text(encoding="utf-8"))
                results.append(result)
            except (json.JSONDecodeError, ValueError) as e:
                logger.warning("Failed to load %s: %s", json_file, e)

        return results

    def _resolve_video_path(self, video_dir: str, video_id: str) -> str | None:
        """Resolve video file path from video_id.

        Returns:
            Full path to video file, or None if not found (warning logged).
        """
        base = Path(video_dir)

        # Try common patterns
        for ext in SUPPORTED_VIDEO_EXTENSIONS:
            candidate = base / f"{video_id}{ext}"
            if candidate.exists():
                return str(candidate)

        # Try subdirectories (e.g., video_dir/short/video_id.mp4)
        for subdir in base.iterdir():
            if subdir.is_dir():
                for ext in SUPPORTED_VIDEO_EXTENSIONS:
                    candidate = subdir / f"{video_id}{ext}"
                    if candidate.exists():
                        return str(candidate)

        logger.warning("Video not found for %s in %s", video_id, video_dir)
        return None

    def _save_summary(
        self,
        results: dict[str, list[EvalResult]],
        benchmark_name: str,
    ) -> None:
        """Save a summary of all method results."""
        summary_dir = self.output_dir / benchmark_name
        summary_dir.mkdir(parents=True, exist_ok=True)

        summary = {}
        for method_name, method_results in results.items():
            errors = [r for r in method_results if r.error is not None]
            summary[method_name] = {
                "total": len(method_results),
                "errors": len(errors),
                "successful": len(method_results) - len(errors),
            }

            # Add efficiency stats if available
            efficiency = self.tracker.summarize(method_name)
            if efficiency:
                summary[method_name]["efficiency"] = efficiency

        summary_path = summary_dir / RUN_SUMMARY_FILENAME
        summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        logger.info("Run summary saved to %s", summary_path)
