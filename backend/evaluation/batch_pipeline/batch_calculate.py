"""
Step 4: Aggregate evaluation scores from parsed judge responses.

Computes win-rates (with position debiasing) and quantitative scores
(mean ± std across N runs), stratified by domain and category.
"""

import logging
import statistics
from collections import defaultdict

from evaluation.models.eval_schemas import (
    AggregatedResults,
    BenchmarkEntry,
    DimensionAggregation,
    EvalDimension,
    JudgeResponse,
)

logger = logging.getLogger(__name__)

# Dimension keys in the Pydantic models
WINRATE_DIMENSIONS = [
    ("comprehensiveness", "Comprehensiveness"),
    ("empowerment", "Empowerment"),
    ("trustworthiness", "Trustworthiness"),
    ("depth", "Depth"),
    ("density", "Density"),
    ("temporal_specificity", "Temporal Specificity"),
    ("source_grounding", "Source Grounding"),
    ("overall_winner", "Overall Winner"),
]

QUANTITATIVE_DIMENSIONS = [
    ("comprehensiveness", "Comprehensiveness"),
    ("empowerment", "Empowerment"),
    ("trustworthiness", "Trustworthiness"),
    ("depth", "Depth"),
    ("density", "Density"),
    ("temporal_specificity", "Temporal Specificity"),
    ("source_grounding", "Source Grounding"),
    ("overall_score", "Overall Score"),
]


def calculate_winrates(
    responses: list[JudgeResponse],
    our_method: str,
    entries: list[BenchmarkEntry] | None = None,
    group_key: str | None = None,
) -> dict[str, dict[str, float]]:
    """Calculate win-rates with position debiasing.

    For original ordering: "Answer 1" win -> our_method wins
    For reversed ordering: "Answer 2" win -> our_method wins

    Args:
        responses: Parsed judge responses (winrate only).
        our_method: The method we're evaluating.
        entries: Benchmark entries for stratification.
        group_key: Optional grouping (e.g., 'domain', 'category').

    Returns:
        Nested dict: comparator -> dimension -> win_rate (0-100%).
    """
    # Group by comparator
    by_comparator: dict[str, list[JudgeResponse]] = defaultdict(list)
    for r in responses:
        if r.winrate_response is None:
            continue
        comparator = r.method_b if r.method_a == our_method else r.method_a
        by_comparator[comparator].append(r)

    results = {}
    for comparator, comp_responses in by_comparator.items():
        dim_wins: dict[str, int] = defaultdict(int)
        dim_total: dict[str, int] = defaultdict(int)

        for r in comp_responses:
            wr = r.winrate_response
            for attr_name, dim_label in WINRATE_DIMENSIONS:
                dim_result = getattr(wr, attr_name, None)
                if dim_result is None:
                    continue

                dim_total[dim_label] += 1

                # Position debiasing logic
                if r.ordering == "original":
                    # our_method is Answer 1
                    if dim_result.winner == "Answer 1":
                        dim_wins[dim_label] += 1
                elif r.ordering == "reversed":
                    # our_method is Answer 2
                    if dim_result.winner == "Answer 2":
                        dim_wins[dim_label] += 1

        results[comparator] = {
            dim: (dim_wins[dim] / dim_total[dim] * 100) if dim_total[dim] > 0 else 0.0
            for dim in dim_total
        }

    return results


def calculate_quantitative_scores(
    responses: list[JudgeResponse],
    entries: list[BenchmarkEntry] | None = None,
    group_key: str | None = None,
) -> dict[str, dict[str, DimensionAggregation]]:
    """Calculate mean ± std quantitative scores across N runs.

    Args:
        responses: Parsed judge responses (quantitative only).
        entries: Benchmark entries for stratification.
        group_key: Optional grouping.

    Returns:
        Dict: method -> dimension -> DimensionAggregation(mean, std, min, max, n).
    """
    # Group by method
    by_method: dict[str, list[JudgeResponse]] = defaultdict(list)
    for r in responses:
        if r.quantitative_response is None:
            continue
        by_method[r.method_a].append(r)

    results = {}
    for method, method_responses in by_method.items():
        dim_scores: dict[str, list[int]] = defaultdict(list)

        for r in method_responses:
            qr = r.quantitative_response
            for attr_name, dim_label in QUANTITATIVE_DIMENSIONS:
                dim_result = getattr(qr, attr_name, None)
                if dim_result is None:
                    continue
                dim_scores[dim_label].append(dim_result.score)

        results[method] = {
            dim: DimensionAggregation(
                mean=statistics.mean(scores),
                std=statistics.stdev(scores) if len(scores) > 1 else 0.0,
                min=min(scores),
                max=max(scores),
                n=len(scores),
            )
            for dim, scores in dim_scores.items()
            if scores
        }

    return results


def calculate_by_group(
    responses: list[JudgeResponse],
    entries: list[BenchmarkEntry],
    group_key: str,
    our_method: str | None = None,
) -> dict[str, dict]:
    """Calculate scores stratified by a grouping key.

    Args:
        responses: All judge responses.
        entries: Benchmark entries (for group metadata).
        group_key: 'domain', 'category', 'duration_tier'.
        our_method: For win-rate, the method being evaluated.

    Returns:
        Dict: group_value -> scores dict.
    """
    entry_map = {e.question_id: e for e in entries}

    # Partition responses by group
    grouped: dict[str, list[JudgeResponse]] = defaultdict(list)
    for r in responses:
        entry = entry_map.get(r.question_id)
        group_val = "unknown"
        if entry:
            val = getattr(entry, group_key, None)
            if val is not None:
                group_val = str(val.value) if hasattr(val, "value") else str(val)
        grouped[group_val].append(r)

    results = {}
    for group_val, group_responses in sorted(grouped.items()):
        winrate_responses = [r for r in group_responses if r.winrate_response]
        quant_responses = [r for r in group_responses if r.quantitative_response]

        group_result = {}
        if winrate_responses and our_method:
            group_result["winrates"] = calculate_winrates(
                winrate_responses, our_method
            )
        if quant_responses:
            group_result["quantitative"] = calculate_quantitative_scores(
                quant_responses
            )
        results[group_val] = group_result

    return results


def format_results_table(
    winrates: dict[str, dict[str, float]] | None = None,
    quant_scores: dict[str, dict[str, DimensionAggregation]] | None = None,
) -> str:
    """Format results as a readable text table.

    Args:
        winrates: Win-rate results from calculate_winrates.
        quant_scores: Quantitative results from calculate_quantitative_scores.

    Returns:
        Formatted string table.
    """
    lines = []

    if winrates:
        lines.append("=== Win-Rate Results (%) ===")
        lines.append("")
        header_dims = [d[1] for d in WINRATE_DIMENSIONS]
        header = f"{'vs.':<20}" + "".join(f"{d:<18}" for d in header_dims)
        lines.append(header)
        lines.append("-" * len(header))

        for comparator, dims in winrates.items():
            row = f"{comparator:<20}"
            for _, dim_label in WINRATE_DIMENSIONS:
                val = dims.get(dim_label, 0.0)
                row += f"{val:>6.1f}%{'':>11}"
            lines.append(row)
        lines.append("")

    if quant_scores:
        lines.append("=== Quantitative Scores (1-5 scale) ===")
        lines.append("")
        header_dims = [d[1] for d in QUANTITATIVE_DIMENSIONS]
        header = f"{'Method':<20}" + "".join(f"{d:<18}" for d in header_dims)
        lines.append(header)
        lines.append("-" * len(header))

        for method, dims in quant_scores.items():
            row = f"{method:<20}"
            for _, dim_label in QUANTITATIVE_DIMENSIONS:
                agg = dims.get(dim_label)
                if agg:
                    row += f"{agg.mean:>4.2f}±{agg.std:<4.2f}{'':>8}"
                else:
                    row += f"{'N/A':>18}"
            lines.append(row)
        lines.append("")

    return "\n".join(lines)
