"""
Step 1: Submit judge requests to OpenAI Batch API.

Creates JSONL files with evaluation requests and submits them
as batch jobs. Supports both win-rate and quantitative protocols.
Following VideoRAG's pattern with position debiasing and N runs.
"""

import json
import logging
from pathlib import Path

from openai import AsyncOpenAI

from evaluation.judges.llm_judge import (
    build_quantitative_batch_request,
    build_winrate_batch_request,
)
from evaluation.models.eval_schemas import BenchmarkEntry, EvalConfig, EvalResult

logger = logging.getLogger(__name__)


async def upload_winrate_batch(
    client: AsyncOpenAI,
    config: EvalConfig,
    entries: list[BenchmarkEntry],
    method_answers: dict[str, list[EvalResult]],
    our_method: str,
    comparator_methods: list[str],
    output_dir: Path,
) -> list[str]:
    """Create and submit win-rate evaluation batch jobs.

    For each comparator method, creates batch requests comparing
    our_method against the comparator. Includes position debiasing
    (both orderings) and N runs.

    Args:
        client: OpenAI async client.
        config: Evaluation configuration.
        entries: Benchmark entries.
        method_answers: Dict mapping method name -> list of EvalResult.
        our_method: The method we're evaluating (e.g., "qprisma-full").
        comparator_methods: Methods to compare against.
        output_dir: Directory to save JSONL files.

    Returns:
        List of batch job IDs.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    entry_map = {e.question_id: e for e in entries}
    our_answers = {r.question_id: r for r in method_answers[our_method]}
    batch_ids = []

    for comparator in comparator_methods:
        comp_answers = {r.question_id: r for r in method_answers[comparator]}
        requests = []

        for run_idx in range(config.num_runs):
            for qid, our_result in our_answers.items():
                entry = entry_map.get(qid)
                comp_result = comp_answers.get(qid)
                if not entry or not comp_result:
                    continue

                # Original ordering: our=Answer1, comp=Answer2
                requests.append(
                    build_winrate_batch_request(
                        question_id=qid,
                        question=entry.question,
                        answer_1=our_result.answer,
                        answer_2=comp_result.answer,
                        method_1=our_method,
                        method_2=comparator,
                        run_index=run_idx,
                        ordering="original",
                        model=config.judge_model,
                    )
                )

                # Reversed ordering for position debiasing
                if config.use_position_debiasing:
                    requests.append(
                        build_winrate_batch_request(
                            question_id=qid,
                            question=entry.question,
                            answer_1=comp_result.answer,
                            answer_2=our_result.answer,
                            method_1=comparator,
                            method_2=our_method,
                            run_index=run_idx,
                            ordering="reversed",
                            model=config.judge_model,
                        )
                    )

        # Write JSONL and submit
        jsonl_path = output_dir / f"winrate_{our_method}_vs_{comparator}.jsonl"
        _write_jsonl(requests, jsonl_path)

        batch_id = await _submit_batch(client, jsonl_path)
        batch_ids.append(batch_id)
        logger.info(
            "Submitted win-rate batch: %s vs %s (%d requests) -> %s",
            our_method,
            comparator,
            len(requests),
            batch_id,
        )

    return batch_ids


async def upload_quantitative_batch(
    client: AsyncOpenAI,
    config: EvalConfig,
    entries: list[BenchmarkEntry],
    method_answers: dict[str, list[EvalResult]],
    methods_to_evaluate: list[str],
    output_dir: Path,
) -> list[str]:
    """Create and submit quantitative evaluation batch jobs.

    Scores each method's answers on a 1-5 scale relative to the
    baseline method's answers.

    Args:
        client: OpenAI async client.
        config: Evaluation configuration.
        entries: Benchmark entries.
        method_answers: Dict mapping method name -> list of EvalResult.
        methods_to_evaluate: Methods to score.
        output_dir: Directory to save JSONL files.

    Returns:
        List of batch job IDs.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    entry_map = {e.question_id: e for e in entries}
    baseline_answers = {r.question_id: r for r in method_answers[config.baseline_method]}
    batch_ids = []

    for method in methods_to_evaluate:
        if method == config.baseline_method:
            continue

        eval_answers = {r.question_id: r for r in method_answers[method]}
        requests = []

        for run_idx in range(config.num_runs):
            for qid, eval_result in eval_answers.items():
                entry = entry_map.get(qid)
                baseline_result = baseline_answers.get(qid)
                if not entry or not baseline_result:
                    continue

                requests.append(
                    build_quantitative_batch_request(
                        question_id=qid,
                        question=entry.question,
                        evaluated_answer=eval_result.answer,
                        baseline_answer=baseline_result.answer,
                        method=method,
                        baseline_method=config.baseline_method,
                        run_index=run_idx,
                        model=config.judge_model,
                    )
                )

        jsonl_path = output_dir / f"quantitative_{method}.jsonl"
        _write_jsonl(requests, jsonl_path)

        batch_id = await _submit_batch(client, jsonl_path)
        batch_ids.append(batch_id)
        logger.info(
            "Submitted quantitative batch: %s (%d requests) -> %s",
            method,
            len(requests),
            batch_id,
        )

    return batch_ids


# =============================================================================
# Helpers
# =============================================================================


def _write_jsonl(requests: list[dict], path: Path) -> None:
    """Write requests as JSONL file."""
    with open(path, "w", encoding="utf-8") as f:
        for req in requests:
            f.write(json.dumps(req, ensure_ascii=False) + "\n")
    logger.info("Wrote %d requests to %s", len(requests), path)


async def _submit_batch(client: AsyncOpenAI, jsonl_path: Path) -> str:
    """Upload JSONL file and create batch job."""
    with open(jsonl_path, "rb") as f:
        upload = await client.files.create(file=f, purpose="batch")

    batch = await client.batches.create(
        input_file_id=upload.id,
        endpoint="/v1/chat/completions",
        completion_window="24h",
        metadata={"source": "qprisma-evaluation", "file": jsonl_path.name},
    )
    return batch.id
