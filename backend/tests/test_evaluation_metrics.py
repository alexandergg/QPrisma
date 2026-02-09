"""
Tests for QPrisma evaluation metrics.

Covers: accuracy, retrieval, temporal, faithfulness, efficiency.
"""

import math

import pytest

from evaluation.metrics.accuracy import (
    compute_accuracy,
    compute_accuracy_by_duration_tier,
    compute_accuracy_by_group,
)
from evaluation.metrics.efficiency import EfficiencyRecord, EfficiencyTracker
from evaluation.metrics.faithfulness import (
    aggregate_faithfulness,
    compute_faithfulness_score,
    compute_hallucination_rate,
    compute_source_attribution_rate,
)
from evaluation.metrics.retrieval import (
    compute_retrieval_metrics,
    context_precision,
    context_recall,
    mean_average_precision,
    mean_reciprocal_rank,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
)
from evaluation.metrics.temporal import (
    compute_temporal_metrics,
    mean_iou,
    recall_at_iou_threshold,
    temporal_iou,
    timestamp_mae,
)
from evaluation.models.eval_schemas import BenchmarkEntry, DurationTier, EvalResult


# =============================================================================
# Accuracy Tests
# =============================================================================


class TestAccuracy:
    def _make_entry(self, qid, answer, category=None, tier=None, duration=None):
        return BenchmarkEntry(
            question_id=qid,
            video_id="v1",
            question="test?",
            correct_answer=answer,
            category=category,
            duration_tier=tier,
            video_duration_seconds=duration,
            benchmark="test",
        )

    def _make_result(self, qid, choice):
        return EvalResult(
            question_id=qid, method="test", answer="", predicted_choice=choice
        )

    def test_perfect_accuracy(self):
        entries = [self._make_entry("q1", "A"), self._make_entry("q2", "B")]
        results = [self._make_result("q1", "A"), self._make_result("q2", "B")]
        assert compute_accuracy(results, entries) == 1.0

    def test_zero_accuracy(self):
        entries = [self._make_entry("q1", "A"), self._make_entry("q2", "B")]
        results = [self._make_result("q1", "C"), self._make_result("q2", "D")]
        assert compute_accuracy(results, entries) == 0.0

    def test_partial_accuracy(self):
        entries = [
            self._make_entry("q1", "A"),
            self._make_entry("q2", "B"),
            self._make_entry("q3", "C"),
            self._make_entry("q4", "D"),
        ]
        results = [
            self._make_result("q1", "A"),
            self._make_result("q2", "B"),
            self._make_result("q3", "X"),
            self._make_result("q4", "Y"),
        ]
        assert compute_accuracy(results, entries) == 0.5

    def test_case_insensitive(self):
        entries = [self._make_entry("q1", "A")]
        results = [self._make_result("q1", "a")]
        assert compute_accuracy(results, entries) == 1.0

    def test_empty_inputs(self):
        assert compute_accuracy([], []) == 0.0

    def test_accuracy_by_group(self):
        entries = [
            self._make_entry("q1", "A", category="perception"),
            self._make_entry("q2", "B", category="perception"),
            self._make_entry("q3", "C", category="reasoning"),
            self._make_entry("q4", "D", category="reasoning"),
        ]
        results = [
            self._make_result("q1", "A"),  # correct
            self._make_result("q2", "X"),  # wrong
            self._make_result("q3", "C"),  # correct
            self._make_result("q4", "D"),  # correct
        ]
        by_group = compute_accuracy_by_group(results, entries, "category")
        assert by_group["perception"] == 0.5
        assert by_group["reasoning"] == 1.0

    def test_accuracy_by_duration_tier(self):
        entries = [
            self._make_entry("q1", "A", duration=60),  # short
            self._make_entry("q2", "B", duration=300),  # medium
            self._make_entry("q3", "C", duration=1800),  # long
        ]
        results = [
            self._make_result("q1", "A"),
            self._make_result("q2", "B"),
            self._make_result("q3", "X"),
        ]
        by_tier = compute_accuracy_by_duration_tier(results, entries)
        assert by_tier["short"] == 1.0
        assert by_tier["medium"] == 1.0
        assert by_tier["long"] == 0.0


# =============================================================================
# Retrieval Tests
# =============================================================================


class TestRetrieval:
    def test_recall_at_k_perfect(self):
        retrieved = ["a", "b", "c", "d", "e"]
        relevant = {"a", "b", "c"}
        assert recall_at_k(retrieved, relevant, k=3) == 1.0

    def test_recall_at_k_partial(self):
        retrieved = ["a", "x", "b", "y", "c"]
        relevant = {"a", "b", "c"}
        assert recall_at_k(retrieved, relevant, k=3) == pytest.approx(2 / 3)

    def test_recall_at_k_none_found(self):
        retrieved = ["x", "y", "z"]
        relevant = {"a", "b"}
        assert recall_at_k(retrieved, relevant, k=3) == 0.0

    def test_recall_empty_relevant(self):
        assert recall_at_k(["a", "b"], set(), k=2) == 0.0

    def test_precision_at_k(self):
        retrieved = ["a", "x", "b", "y", "c"]
        relevant = {"a", "b", "c"}
        assert precision_at_k(retrieved, relevant, k=5) == pytest.approx(3 / 5)

    def test_precision_at_k_all_relevant(self):
        retrieved = ["a", "b", "c"]
        relevant = {"a", "b", "c"}
        assert precision_at_k(retrieved, relevant, k=3) == 1.0

    def test_ndcg_at_k_perfect(self):
        retrieved = ["a", "b", "c"]
        scores = {"a": 1.0, "b": 0.8, "c": 0.5}
        # Perfect ordering -> NDCG = 1.0
        assert ndcg_at_k(retrieved, scores, k=3) == pytest.approx(1.0)

    def test_ndcg_at_k_reversed(self):
        retrieved = ["c", "b", "a"]
        scores = {"a": 1.0, "b": 0.5, "c": 0.0}
        # Worst possible ordering -> NDCG < 1.0
        result = ndcg_at_k(retrieved, scores, k=3)
        assert 0.0 < result < 1.0

    def test_ndcg_empty(self):
        assert ndcg_at_k([], {}, k=5) == 0.0

    def test_mrr_first_position(self):
        retrieved = [["a", "b", "c"]]
        relevant = [{"a"}]
        assert mean_reciprocal_rank(retrieved, relevant) == 1.0

    def test_mrr_second_position(self):
        retrieved = [["x", "a", "b"]]
        relevant = [{"a"}]
        assert mean_reciprocal_rank(retrieved, relevant) == 0.5

    def test_mrr_multi_query(self):
        retrieved = [["a", "b"], ["x", "y", "a"]]
        relevant = [{"a"}, {"a"}]
        # Query 1: RR = 1/1 = 1.0, Query 2: RR = 1/3
        assert mean_reciprocal_rank(retrieved, relevant) == pytest.approx(
            (1.0 + 1 / 3) / 2
        )

    def test_map_single_query(self):
        retrieved = [["a", "x", "b"]]
        relevant = [{"a", "b"}]
        # P@1=1, P@2=0.5, P@3=2/3. AP = (1 + 2/3) / 2 = 5/6
        assert mean_average_precision(retrieved, relevant) == pytest.approx(5 / 6)

    def test_context_precision_all_relevant(self):
        assert context_precision([True, True, True]) == pytest.approx(1.0)

    def test_context_precision_none_relevant(self):
        assert context_precision([False, False, False]) == 0.0

    def test_context_precision_mixed(self):
        # [True, False, True] -> hits at 1,3. P@1=1/1=1, P@3=2/3
        # CP = (1 + 2/3) / 2 = 5/6
        assert context_precision([True, False, True]) == pytest.approx(5 / 6)

    def test_context_recall(self):
        claims = ["claim1", "claim2", "claim3"]
        supported = [True, True, False]
        assert context_recall(claims, supported) == pytest.approx(2 / 3)

    def test_compute_retrieval_metrics(self):
        retrieved = ["a", "x", "b", "y", "c"]
        relevant = {"a", "b", "c"}
        metrics = compute_retrieval_metrics(retrieved, relevant, k_values=[3, 5])
        assert "recall@3" in metrics
        assert "precision@5" in metrics
        assert "ndcg@3" in metrics
        assert "mrr" in metrics
        assert "ap" in metrics


# =============================================================================
# Temporal Tests
# =============================================================================


class TestTemporal:
    def test_iou_perfect_overlap(self):
        assert temporal_iou((10.0, 20.0), (10.0, 20.0)) == 1.0

    def test_iou_no_overlap(self):
        assert temporal_iou((0.0, 5.0), (10.0, 15.0)) == 0.0

    def test_iou_partial_overlap(self):
        # P=[0,10], G=[5,15] -> intersection=[5,10]=5, union=[0,15]=15
        assert temporal_iou((0.0, 10.0), (5.0, 15.0)) == pytest.approx(5 / 15)

    def test_iou_contained(self):
        # P=[5,10], G=[0,20] -> intersection=[5,10]=5, union=[0,20]=20
        assert temporal_iou((5.0, 10.0), (0.0, 20.0)) == pytest.approx(5 / 20)

    def test_iou_zero_duration(self):
        assert temporal_iou((5.0, 5.0), (5.0, 5.0)) == 0.0

    def test_recall_at_iou_threshold(self):
        preds = [(0, 10), (5, 15), (20, 30)]
        gts = [(0, 10), (5, 15), (25, 35)]
        # IoUs: 1.0, 1.0, 5/15=0.33
        assert recall_at_iou_threshold(preds, gts, 0.5) == pytest.approx(2 / 3)
        assert recall_at_iou_threshold(preds, gts, 0.3) == 1.0

    def test_mean_iou(self):
        preds = [(0, 10), (0, 10)]
        gts = [(0, 10), (5, 15)]
        # IoUs: 1.0, 5/15
        assert mean_iou(preds, gts) == pytest.approx((1.0 + 5 / 15) / 2)

    def test_timestamp_mae(self):
        preds = [10.0, 20.0, 30.0]
        gts = [12.0, 18.0, 35.0]
        # Errors: 2, 2, 5 -> MAE = 9/3 = 3.0
        assert timestamp_mae(preds, gts) == pytest.approx(3.0)

    def test_timestamp_mae_perfect(self):
        assert timestamp_mae([10.0, 20.0], [10.0, 20.0]) == 0.0

    def test_compute_temporal_metrics(self):
        preds = [(0, 10), (5, 15)]
        gts = [(0, 10), (5, 15)]
        metrics = compute_temporal_metrics(preds, gts)
        assert metrics["mean_iou"] == 1.0
        assert metrics["r1@iou=0.5"] == 1.0
        assert metrics["timestamp_mae"] == 0.0


# =============================================================================
# Faithfulness Tests
# =============================================================================


class TestFaithfulness:
    def test_perfect_faithfulness(self):
        assert compute_faithfulness_score(total_claims=5, supported_claims=5) == 1.0

    def test_zero_faithfulness(self):
        assert compute_faithfulness_score(total_claims=5, supported_claims=0) == 0.0

    def test_partial_faithfulness(self):
        assert compute_faithfulness_score(total_claims=4, supported_claims=3) == 0.75

    def test_no_claims_is_faithful(self):
        assert compute_faithfulness_score(total_claims=0, supported_claims=0) == 1.0

    def test_hallucination_rate(self):
        assert compute_hallucination_rate(total_claims=10, unsupported_claims=3) == 0.3

    def test_source_attribution(self):
        assert compute_source_attribution_rate(
            total_claims=10, claims_with_timestamps=7
        ) == 0.7

    def test_aggregate_faithfulness(self):
        results = [
            {
                "total_claims": 4,
                "supported_claims": 3,
                "unsupported_claims": 1,
                "claims_with_timestamps": 2,
            },
            {
                "total_claims": 6,
                "supported_claims": 6,
                "unsupported_claims": 0,
                "claims_with_timestamps": 4,
            },
        ]
        agg = aggregate_faithfulness(results)
        assert agg["faithfulness_score"] == pytest.approx((3 / 4 + 1.0) / 2)
        assert agg["hallucination_rate"] == pytest.approx((1 / 4 + 0.0) / 2)
        assert agg["source_attribution_rate"] == pytest.approx((2 / 4 + 4 / 6) / 2)


# =============================================================================
# Efficiency Tests
# =============================================================================


class TestEfficiency:
    def test_tracker_add_and_summarize(self):
        tracker = EfficiencyTracker()
        tracker.add(
            EfficiencyRecord(
                question_id="q1",
                method="test",
                latency_ms=100.0,
                tokens_input=1000,
                tokens_output=200,
                cost_usd=0.01,
            )
        )
        tracker.add(
            EfficiencyRecord(
                question_id="q2",
                method="test",
                latency_ms=200.0,
                tokens_input=2000,
                tokens_output=300,
                cost_usd=0.02,
            )
        )

        summary = tracker.summarize("test")
        assert summary["n_queries"] == 2
        assert summary["latency_mean_ms"] == 150.0
        assert summary["cost_total_usd"] == pytest.approx(0.03)
        assert summary["tokens_total"] == 3500

    def test_tracker_empty(self):
        tracker = EfficiencyTracker()
        assert tracker.summarize("nonexistent") == {}

    def test_tracker_methods(self):
        tracker = EfficiencyTracker()
        tracker.add(EfficiencyRecord("q1", "method_a", 100.0))
        tracker.add(EfficiencyRecord("q2", "method_b", 200.0))
        assert set(tracker.methods()) == {"method_a", "method_b"}

    def test_tracker_percentiles(self):
        tracker = EfficiencyTracker()
        for i in range(100):
            tracker.add(
                EfficiencyRecord(f"q{i}", "test", latency_ms=float(i + 1))
            )

        summary = tracker.summarize("test")
        assert summary["latency_p50_ms"] == pytest.approx(50.5, abs=1.0)
        assert summary["latency_p95_ms"] == pytest.approx(95.5, abs=1.0)


# =============================================================================
# Schema Tests
# =============================================================================


class TestSchemas:
    def test_benchmark_entry_creation(self):
        entry = BenchmarkEntry(
            question_id="q1",
            video_id="v1",
            question="What happens?",
            choices=["A", "B", "C", "D"],
            correct_answer="A",
            benchmark="video-mme",
        )
        assert entry.question_id == "q1"
        assert entry.benchmark == "video-mme"

    def test_eval_result_creation(self):
        result = EvalResult(
            question_id="q1",
            method="qprisma-full",
            answer="The CEO speaks at [2:34]",
            predicted_choice="A",
            latency_ms=150.0,
        )
        assert result.method == "qprisma-full"
        assert result.latency_ms == 150.0

    def test_duration_tier_values(self):
        assert DurationTier.SHORT.value == "short"
        assert DurationTier.VERY_LONG.value == "very_long"
