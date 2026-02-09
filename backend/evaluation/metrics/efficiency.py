"""
Efficiency metrics for video understanding evaluation.

Tracks latency, cost, and token usage across evaluation runs
to enable cost-quality Pareto analysis.
"""

import statistics
import time
from contextlib import contextmanager
from dataclasses import dataclass, field


@dataclass
class EfficiencyRecord:
    """Single measurement of efficiency for one query."""

    question_id: str
    method: str
    latency_ms: float
    retrieval_latency_ms: float | None = None
    tokens_input: int = 0
    tokens_output: int = 0
    cost_usd: float = 0.0
    tool_calls: int = 0


@dataclass
class EfficiencyTracker:
    """Collects and aggregates efficiency metrics across an evaluation run."""

    records: list[EfficiencyRecord] = field(default_factory=list)

    def add(self, record: EfficiencyRecord) -> None:
        self.records.append(record)

    @contextmanager
    def measure(self, question_id: str, method: str):
        """Context manager to measure latency for a single query.

        Usage:
            with tracker.measure("q1", "qprisma-full") as record:
                answer = await run_query(question)
                record.tokens_input = 5000
                record.tokens_output = 500
                record.cost_usd = 0.01
        """
        record = EfficiencyRecord(
            question_id=question_id,
            method=method,
            latency_ms=0.0,
        )
        start = time.perf_counter()
        try:
            yield record
        finally:
            record.latency_ms = (time.perf_counter() - start) * 1000
            self.records.append(record)

    def summarize(self, method: str | None = None) -> dict[str, float]:
        """Compute aggregate efficiency statistics.

        Args:
            method: Filter to a specific method. None = all records.

        Returns:
            Dict with latency (mean, p50, p95, p99), cost, and token stats.
        """
        records = self.records
        if method:
            records = [r for r in records if r.method == method]

        if not records:
            return {}

        latencies = [r.latency_ms for r in records]
        retrieval_latencies = [
            r.retrieval_latency_ms for r in records if r.retrieval_latency_ms is not None
        ]
        costs = [r.cost_usd for r in records]
        total_tokens = [r.tokens_input + r.tokens_output for r in records]
        tool_calls = [r.tool_calls for r in records]

        result = {
            "n_queries": len(records),
            "latency_mean_ms": statistics.mean(latencies),
            "latency_p50_ms": _percentile(latencies, 50),
            "latency_p95_ms": _percentile(latencies, 95),
            "latency_p99_ms": _percentile(latencies, 99),
            "cost_mean_usd": statistics.mean(costs),
            "cost_total_usd": sum(costs),
            "tokens_mean": statistics.mean(total_tokens),
            "tokens_total": sum(total_tokens),
            "tool_calls_mean": statistics.mean(tool_calls),
        }

        if retrieval_latencies:
            result["retrieval_latency_mean_ms"] = statistics.mean(retrieval_latencies)
            result["retrieval_latency_p50_ms"] = _percentile(retrieval_latencies, 50)
            result["retrieval_latency_p95_ms"] = _percentile(retrieval_latencies, 95)

        return result

    def methods(self) -> list[str]:
        """Return list of unique methods in the tracker."""
        return sorted({r.method for r in self.records})


def _percentile(data: list[float], pct: int) -> float:
    """Compute the pct-th percentile of a sorted list."""
    if not data:
        return 0.0
    sorted_data = sorted(data)
    idx = (pct / 100) * (len(sorted_data) - 1)
    lower = int(idx)
    upper = min(lower + 1, len(sorted_data) - 1)
    fraction = idx - lower
    return sorted_data[lower] + fraction * (sorted_data[upper] - sorted_data[lower])
