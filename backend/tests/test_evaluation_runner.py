"""
Tests for QPrisma evaluation runner, adapters, and orchestrator.

Covers:
- BaseMethodAdapter (extract_mc_choice, extract_timestamps)
- EvaluationRunner (run_method, resume, result persistence)
- run_evaluation orchestrator (config building, metric computation)
"""

import asyncio
import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from evaluation.adapters.base import BaseMethodAdapter
from evaluation.models.eval_schemas import (
    AggregatedResults,
    BenchmarkConfig,
    BenchmarkEntry,
    DurationTier,
    EvalConfig,
    EvalResult,
    MethodConfig,
)
from evaluation.runner import EvaluationRunner


# =============================================================================
# Helpers
# =============================================================================


def _entry(qid="q1", answer="A", category=None, tier=None, duration=None):
    return BenchmarkEntry(
        question_id=qid,
        video_id="v1",
        question="What happens in the video?",
        choices=["Option A", "Option B", "Option C", "Option D"],
        correct_answer=answer,
        category=category,
        duration_tier=tier,
        video_duration_seconds=duration,
        benchmark="test",
    )


def _result(qid="q1", method="test", answer="A", choice="A"):
    return EvalResult(
        question_id=qid,
        method=method,
        answer=answer,
        predicted_choice=choice,
        latency_ms=100.0,
        tokens_used=500,
    )


class MockAdapter(BaseMethodAdapter):
    """Fake adapter for testing the runner."""

    def __init__(self, name_str="mock-method", answers=None):
        self._name = name_str
        self._answers = answers or {}
        self.setup_called = False
        self.teardown_called = False

    @property
    def name(self) -> str:
        return self._name

    @property
    def display_name(self) -> str:
        return f"Mock ({self._name})"

    async def setup(self) -> None:
        self.setup_called = True

    async def teardown(self) -> None:
        self.teardown_called = True

    async def generate_answer(self, entry, video_path=None):
        answer = self._answers.get(entry.question_id, "A")
        return EvalResult(
            question_id=entry.question_id,
            method=self.name,
            answer=f"The answer is {answer}",
            predicted_choice=answer,
            latency_ms=50.0,
            tokens_used=300,
        )


# =============================================================================
# BaseMethodAdapter Tests (extract_mc_choice, extract_timestamps)
# =============================================================================


class TestExtractMCChoice:
    """Test the MC choice extraction logic in BaseMethodAdapter."""

    def _extract(self, answer, choices=None):
        adapter = MockAdapter()
        return adapter.extract_mc_choice(answer, choices)

    def test_direct_letter(self):
        assert self._extract("A", ["a", "b", "c", "d"]) == "A"

    def test_direct_letter_lowercase(self):
        assert self._extract("b", ["a", "b", "c", "d"]) == "B"

    def test_parenthesized_letter(self):
        assert self._extract("(C)", ["a", "b", "c", "d"]) == "C"

    def test_answer_is_pattern(self):
        assert self._extract("The answer is B", ["a", "b", "c", "d"]) == "B"

    def test_answer_colon_pattern(self):
        assert self._extract("Answer: D", ["a", "b", "c", "d"]) == "D"

    def test_letter_dot_prefix(self):
        assert self._extract("A. This is the first option", ["a", "b", "c", "d"]) == "A"

    def test_full_text_match(self):
        choices = ["apples", "bananas", "cherries", "dates"]
        assert self._extract("bananas", choices) == "B"

    def test_full_text_match_with_prefix(self):
        choices = ["A. apples", "B. bananas", "C. cherries", "D. dates"]
        assert self._extract("cherries", choices) == "C"

    def test_no_match_returns_none(self):
        assert self._extract("some random text", ["a", "b", "c", "d"]) is None

    def test_no_choices_returns_none(self):
        assert self._extract("A", None) is None

    def test_empty_choices_returns_none(self):
        assert self._extract("A", []) is None

    def test_complex_answer_with_explanation(self):
        answer = "Based on the video, the answer is C because the speaker mentions..."
        assert self._extract(answer, ["a", "b", "c", "d"]) == "C"

    def test_bold_markdown_letter(self):
        answer = "**A** \u2013 Yes, a large seated audience is visible."
        assert self._extract(answer, ["opt1", "opt2", "opt3", "opt4"]) == "A"

    def test_bold_markdown_letter_with_period(self):
        answer = "**C.** About 2.5 hours"
        assert self._extract(answer, ["2 mins", "30 mins", "2.5 hours", "8 hours"]) == "C"

    def test_bold_answer_colon(self):
        answer = "**Answer: B**\n\nThe video shows..."
        assert self._extract(answer, ["opt1", "opt2", "opt3", "opt4"]) == "B"


class TestExtractTimestamps:
    """Test the timestamp extraction logic in BaseMethodAdapter."""

    def _extract(self, answer):
        adapter = MockAdapter()
        return adapter.extract_timestamps(answer)

    def test_mm_ss_format(self):
        result = self._extract("The event occurs at [2:34]")
        assert 154.0 in result  # 2*60 + 34

    def test_h_mm_ss_format(self):
        result = self._extract("At [1:02:30] the speaker begins")
        assert 3750.0 in result  # 1*3600 + 2*60 + 30

    def test_at_xs_format(self):
        result = self._extract("This happens at 45s into the video")
        assert 45.0 in result

    def test_timestamp_xs_format(self):
        result = self._extract("See timestamp 120s for details")
        assert 120.0 in result

    def test_multiple_timestamps(self):
        result = self._extract("Events at [1:00], [2:30], and [5:00]")
        assert 60.0 in result
        assert 150.0 in result
        assert 300.0 in result

    def test_no_timestamps(self):
        result = self._extract("The answer is A")
        assert result == []

    def test_deduplication(self):
        # [1:02:30] captures both H:MM:SS and MM:SS pattern for 02:30
        result = self._extract("[1:02:30]")
        # Should not have duplicates
        assert len(result) == len(set(result))

    def test_float_seconds(self):
        result = self._extract("at 12.5s the scene changes")
        assert 12.5 in result


# =============================================================================
# EvaluationRunner Tests
# =============================================================================


class TestEvaluationRunner:
    async def test_run_method_basic(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = EvaluationRunner(output_dir=tmpdir, resume=False)
            adapter = MockAdapter(answers={"q1": "A", "q2": "B"})
            entries = [_entry("q1", "A"), _entry("q2", "B")]

            results = await runner.run_method(adapter, entries, benchmark_name="test")

            assert len(results) == 2
            assert adapter.setup_called
            assert adapter.teardown_called
            assert all(r.method == "mock-method" for r in results)

    async def test_run_method_saves_to_disk(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = EvaluationRunner(output_dir=tmpdir, resume=False)
            adapter = MockAdapter(answers={"q1": "A"})
            entries = [_entry("q1", "A")]

            await runner.run_method(adapter, entries, benchmark_name="test")

            result_path = Path(tmpdir) / "test" / "mock-method" / "q1.json"
            assert result_path.exists()

            saved = EvalResult.model_validate_json(result_path.read_text())
            assert saved.question_id == "q1"
            assert saved.predicted_choice == "A"

    async def test_run_method_resume_skips_completed(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Pre-save a result for q1
            method_dir = Path(tmpdir) / "test" / "mock-method"
            method_dir.mkdir(parents=True)
            existing = _result("q1", "mock-method", "A", "A")
            (method_dir / "q1.json").write_text(existing.model_dump_json(indent=2))

            runner = EvaluationRunner(output_dir=tmpdir, resume=True)
            adapter = MockAdapter(answers={"q1": "A", "q2": "B"})
            entries = [_entry("q1", "A"), _entry("q2", "B")]

            results = await runner.run_method(adapter, entries, benchmark_name="test")

            # Should have 2 results total (1 loaded + 1 generated)
            assert len(results) == 2

    async def test_run_method_handles_adapter_error(self):
        """Test that exceptions from adapter are caught gracefully."""

        class FailingAdapter(MockAdapter):
            async def generate_answer(self, entry, video_path=None):
                raise RuntimeError("Simulated failure")

        with tempfile.TemporaryDirectory() as tmpdir:
            runner = EvaluationRunner(output_dir=tmpdir, resume=False)
            adapter = FailingAdapter()
            entries = [_entry("q1")]

            results = await runner.run_method(adapter, entries, benchmark_name="test")

            assert len(results) == 1
            assert results[0].answer.startswith("Error:")

    async def test_run_all_methods(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = EvaluationRunner(output_dir=tmpdir, resume=False)
            adapter_a = MockAdapter("method-a", {"q1": "A"})
            adapter_b = MockAdapter("method-b", {"q1": "B"})
            entries = [_entry("q1")]

            results = await runner.run_all_methods(
                [adapter_a, adapter_b], entries, benchmark_name="test"
            )

            assert "method-a" in results
            assert "method-b" in results
            assert len(results["method-a"]) == 1
            assert len(results["method-b"]) == 1

    async def test_run_all_methods_saves_summary(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = EvaluationRunner(output_dir=tmpdir, resume=False)
            adapter = MockAdapter(answers={"q1": "A"})
            entries = [_entry("q1")]

            await runner.run_all_methods([adapter], entries, benchmark_name="test")

            summary_path = Path(tmpdir) / "test" / "_run_summary.json"
            assert summary_path.exists()

            summary = json.loads(summary_path.read_text())
            assert "mock-method" in summary
            assert summary["mock-method"]["total"] == 1
            assert summary["mock-method"]["errors"] == 0

    def test_load_results(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Save some results
            method_dir = Path(tmpdir) / "test" / "mock-method"
            method_dir.mkdir(parents=True)
            for i in range(3):
                result = _result(f"q{i}", "mock-method")
                (method_dir / f"q{i}.json").write_text(result.model_dump_json(indent=2))

            runner = EvaluationRunner(output_dir=tmpdir)
            loaded = runner.load_results("mock-method", "test")
            assert len(loaded) == 3

    def test_load_results_empty_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = EvaluationRunner(output_dir=tmpdir)
            loaded = runner.load_results("nonexistent", "test")
            assert loaded == []

    async def test_efficiency_tracking(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = EvaluationRunner(output_dir=tmpdir, resume=False)
            adapter = MockAdapter(answers={"q1": "A", "q2": "B"})
            entries = [_entry("q1"), _entry("q2")]

            await runner.run_method(adapter, entries, benchmark_name="test")

            summary = runner.tracker.summarize("mock-method")
            assert summary["n_queries"] == 2
            assert summary["latency_mean_ms"] > 0

    def test_resolve_video_path_not_found(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = EvaluationRunner(output_dir=tmpdir)
            result = runner._resolve_video_path(tmpdir, "nonexistent_video")
            assert result is None

    def test_resolve_video_path_found(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a fake video file
            video_path = Path(tmpdir) / "v1.mp4"
            video_path.write_bytes(b"fake")

            runner = EvaluationRunner(output_dir=tmpdir)
            result = runner._resolve_video_path(tmpdir, "v1")
            assert result == str(video_path)


# =============================================================================
# Orchestrator (compute_all_metrics) Tests
# =============================================================================


class TestComputeAllMetrics:
    def test_accuracy_metrics(self):
        from evaluation.run_evaluation import compute_all_metrics

        entries = [_entry("q1", "A"), _entry("q2", "B"), _entry("q3", "C")]
        results = [
            _result("q1", "test", "A", "A"),
            _result("q2", "test", "B", "B"),
            _result("q3", "test", "X", "X"),
        ]

        agg = compute_all_metrics(results, entries, "test", "bench")

        assert agg.method == "test"
        assert agg.benchmark == "bench"
        assert agg.total_questions == 3
        assert agg.accuracy == pytest.approx(2 / 3)

    def test_accuracy_by_tier(self):
        from evaluation.run_evaluation import compute_all_metrics

        entries = [
            _entry("q1", "A", tier=DurationTier.SHORT),
            _entry("q2", "B", tier=DurationTier.LONG),
        ]
        results = [
            _result("q1", "test", "A", "A"),
            _result("q2", "test", "X", "X"),
        ]

        agg = compute_all_metrics(results, entries, "test", "bench")
        assert agg.accuracy_by_tier["short"] == 1.0
        assert agg.accuracy_by_tier["long"] == 0.0

    def test_accuracy_by_category(self):
        from evaluation.run_evaluation import compute_all_metrics

        entries = [
            _entry("q1", "A", category="perception"),
            _entry("q2", "B", category="reasoning"),
        ]
        results = [
            _result("q1", "test", "A", "A"),
            _result("q2", "test", "X", "X"),
        ]

        agg = compute_all_metrics(results, entries, "test", "bench")
        assert agg.accuracy_by_category["perception"] == 1.0
        assert agg.accuracy_by_category["reasoning"] == 0.0

    def test_efficiency_from_summary(self):
        from evaluation.run_evaluation import compute_all_metrics

        entries = [_entry("q1", "A")]
        results = [_result("q1", "test", "A", "A")]
        efficiency = {
            "latency_mean_ms": 150.0,
            "latency_p95_ms": 250.0,
            "cost_mean_usd": 0.05,
            "tokens_mean": 1200.0,
        }

        agg = compute_all_metrics(results, entries, "test", "bench", efficiency)
        assert agg.avg_latency_ms == 150.0
        assert agg.p95_latency_ms == 250.0
        assert agg.avg_cost_usd == 0.05
        assert agg.avg_tokens == 1200.0

    def test_no_mc_questions(self):
        from evaluation.run_evaluation import compute_all_metrics

        entries = [
            BenchmarkEntry(
                question_id="q1",
                video_id="v1",
                question="Describe the video",
                benchmark="test",
            )
        ]
        results = [
            EvalResult(question_id="q1", method="test", answer="A long description...")
        ]

        agg = compute_all_metrics(results, entries, "test", "bench")
        assert agg.accuracy is None


# =============================================================================
# Adapter Builder Tests
# =============================================================================


class TestAdapterBuilder:
    def test_qprisma_full(self):
        from evaluation.run_evaluation import _build_adapter

        adapter = _build_adapter("qprisma-full")
        assert adapter.name == "qprisma-full"

    def test_qprisma_noagent(self):
        from evaluation.run_evaluation import _build_adapter

        adapter = _build_adapter("qprisma-noagent")
        assert adapter.name == "qprisma-noagent"

    def test_uniform_baselines(self):
        from evaluation.run_evaluation import _build_adapter

        for n in [8, 16, 32]:
            adapter = _build_adapter(f"uniform-{n}")
            assert adapter.name == f"uniform-{n}"

    def test_naive_rag(self):
        from evaluation.run_evaluation import _build_adapter

        adapter = _build_adapter("naive-rag")
        assert adapter.name == "naive-rag"

    def test_external_api(self):
        from evaluation.run_evaluation import _build_adapter

        adapter = _build_adapter("openai-gpt-4o")
        assert adapter.name == "openai-gpt-4o"

    def test_unknown_raises(self):
        from evaluation.run_evaluation import _build_adapter

        with pytest.raises(ValueError, match="Unknown method"):
            _build_adapter("nonexistent-method")


# =============================================================================
# Config Builder Tests
# =============================================================================


class TestConfigBuilder:
    def test_build_from_args(self):
        from evaluation.run_evaluation import build_config_from_args

        args = MagicMock()
        args.config = None
        args.benchmark = "video_mme"
        args.data_path = "/data/video_mme.json"
        args.video_dir = "/data/videos"
        args.methods = ["qprisma-full", "naive-rag"]
        args.judge_model = "gpt-4o"
        args.num_runs = 3
        args.no_batch = False
        args.output_dir = "/tmp/results"

        config = build_config_from_args(args)

        assert len(config.benchmarks) == 1
        assert config.benchmarks[0].name == "video_mme"
        assert len(config.methods) == 2
        assert config.num_runs == 3
        assert config.baseline_method == "naive-rag"

    def test_build_from_config_file(self):
        from evaluation.run_evaluation import build_config_from_args

        config_data = EvalConfig(
            benchmarks=[
                BenchmarkConfig(
                    name="video_mme",
                    data_path="/data/test.json",
                    video_dir="/data/videos",
                )
            ],
            methods=[
                MethodConfig(name="qprisma-full", display_name="QPrisma Full"),
            ],
        )

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as f:
            f.write(config_data.model_dump_json(indent=2))
            config_path = f.name

        args = MagicMock()
        args.config = config_path

        config = build_config_from_args(args)
        assert len(config.benchmarks) == 1
        assert config.methods[0].name == "qprisma-full"

        Path(config_path).unlink()


# =============================================================================
# Report Generation Tests
# =============================================================================


class TestReportGeneration:
    def test_generate_report_with_accuracy(self):
        from evaluation.run_evaluation import generate_report

        with tempfile.TemporaryDirectory() as tmpdir:
            agg = {
                "qprisma-full": AggregatedResults(
                    method="qprisma-full",
                    benchmark="test",
                    total_questions=100,
                    accuracy=0.85,
                    accuracy_by_tier={"short": 0.90, "medium": 0.85, "long": 0.75},
                ),
                "naive-rag": AggregatedResults(
                    method="naive-rag",
                    benchmark="test",
                    total_questions=100,
                    accuracy=0.60,
                    accuracy_by_tier={"short": 0.70, "medium": 0.55, "long": 0.45},
                ),
            }

            report = generate_report(agg, {}, Path(tmpdir), "test")

            assert "# QPrisma Evaluation Report: test" in report
            assert "MC Accuracy" in report
            assert "qprisma-full" in report
            assert "naive-rag" in report

            report_path = Path(tmpdir) / "test" / "REPORT.md"
            assert report_path.exists()

    def test_generate_report_with_efficiency(self):
        from evaluation.run_evaluation import generate_report

        with tempfile.TemporaryDirectory() as tmpdir:
            agg = {
                "qprisma-full": AggregatedResults(
                    method="qprisma-full",
                    benchmark="test",
                    total_questions=50,
                    avg_latency_ms=1500.0,
                    p95_latency_ms=3000.0,
                    avg_cost_usd=0.05,
                    avg_tokens=2000.0,
                ),
            }

            report = generate_report(agg, {}, Path(tmpdir), "test")
            assert "Efficiency" in report
            assert "1,500" in report

    def test_generate_report_empty(self):
        from evaluation.run_evaluation import generate_report

        with tempfile.TemporaryDirectory() as tmpdir:
            report = generate_report({}, {}, Path(tmpdir), "test")
            assert "# QPrisma Evaluation Report: test" in report
