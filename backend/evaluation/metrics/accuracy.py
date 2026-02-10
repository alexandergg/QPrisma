"""
Accuracy metrics for video understanding evaluation.

Supports multiple-choice accuracy with stratification by
video duration tier, task category, and custom groupings.
"""

from collections import defaultdict

from evaluation.models.eval_schemas import BenchmarkEntry, DurationTier, EvalResult


def compute_accuracy(
    results: list[EvalResult],
    entries: list[BenchmarkEntry],
) -> float:
    """Compute overall MC accuracy.

    Args:
        results: Predicted results with predicted_choice populated.
        entries: Benchmark entries with correct_answer populated.

    Returns:
        Accuracy as a float in [0, 1].
    """
    if not results:
        return 0.0

    gt_map = {e.question_id: e.correct_answer for e in entries if e.correct_answer}
    correct = 0
    total = 0

    for r in results:
        if r.question_id not in gt_map or r.predicted_choice is None:
            continue
        total += 1
        if _normalize_choice(r.predicted_choice) == _normalize_choice(gt_map[r.question_id]):
            correct += 1

    return correct / total if total > 0 else 0.0


def compute_accuracy_by_group(
    results: list[EvalResult],
    entries: list[BenchmarkEntry],
    group_key: str = "category",
) -> dict[str, float]:
    """Compute accuracy stratified by a grouping key.

    Args:
        results: Predicted results.
        entries: Benchmark entries.
        group_key: Attribute of BenchmarkEntry to group by
                   ('category', 'domain', 'duration_tier', 'benchmark').

    Returns:
        Dict mapping group values to accuracy scores.
    """
    entry_map = {e.question_id: e for e in entries}
    groups: dict[str, list[tuple[EvalResult, BenchmarkEntry]]] = defaultdict(list)

    for r in results:
        entry = entry_map.get(r.question_id)
        if entry is None or entry.correct_answer is None or r.predicted_choice is None:
            continue
        group_val = getattr(entry, group_key, None)
        if group_val is None:
            group_val = "unknown"
        elif isinstance(group_val, DurationTier):
            group_val = group_val.value
        groups[str(group_val)].append((r, entry))

    return {group: _accuracy_from_pairs(pairs) for group, pairs in sorted(groups.items())}


def compute_accuracy_by_duration_tier(
    results: list[EvalResult],
    entries: list[BenchmarkEntry],
    tier_boundaries: dict[DurationTier, tuple[float, float]] | None = None,
) -> dict[str, float]:
    """Compute accuracy by video duration tier.

    If entries have duration_tier set, uses those directly.
    Otherwise, computes tiers from video_duration_seconds using tier_boundaries.

    Args:
        results: Predicted results.
        entries: Benchmark entries.
        tier_boundaries: Optional custom tier boundaries in seconds.
            Defaults to: short < 120s, medium 120-900s, long 900-3600s, very_long > 3600s.

    Returns:
        Dict mapping tier names to accuracy scores.
    """
    if tier_boundaries is None:
        tier_boundaries = {
            DurationTier.SHORT: (0, 120),
            DurationTier.MEDIUM: (120, 900),
            DurationTier.LONG: (900, 3600),
            DurationTier.VERY_LONG: (3600, float("inf")),
        }

    {e.question_id: e for e in entries}
    enriched_entries = []

    for entry in entries:
        if entry.duration_tier is not None:
            enriched_entries.append(entry)
        elif entry.video_duration_seconds is not None:
            tier = _duration_to_tier(entry.video_duration_seconds, tier_boundaries)
            enriched_entries.append(entry.model_copy(update={"duration_tier": tier}))
        else:
            enriched_entries.append(entry)

    return compute_accuracy_by_group(results, enriched_entries, group_key="duration_tier")


# =============================================================================
# Helpers
# =============================================================================


def _normalize_choice(choice: str) -> str:
    """Normalize an answer choice for comparison."""
    return choice.strip().upper()


def _accuracy_from_pairs(
    pairs: list[tuple[EvalResult, BenchmarkEntry]],
) -> float:
    """Compute accuracy from a list of (result, entry) pairs."""
    if not pairs:
        return 0.0
    correct = sum(
        1
        for r, e in pairs
        if _normalize_choice(r.predicted_choice) == _normalize_choice(e.correct_answer)
    )
    return correct / len(pairs)


def _duration_to_tier(
    duration_seconds: float,
    boundaries: dict[DurationTier, tuple[float, float]],
) -> DurationTier:
    """Map a duration in seconds to a tier."""
    for tier, (low, high) in boundaries.items():
        if low <= duration_seconds < high:
            return tier
    return DurationTier.VERY_LONG
