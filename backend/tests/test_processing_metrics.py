"""Tests for services.processing_metrics."""

import logging

import pytest

from services.processing_metrics import PipelineMetrics, ProcessingTimer, StageMetrics

# ---------------------------------------------------------------------------
# StageMetrics
# ---------------------------------------------------------------------------


class TestStageMetrics:
    def test_duration_seconds_with_times(self):
        stage = StageMetrics(name="test", start_time=100.0, end_time=103.5)
        assert stage.duration_seconds == pytest.approx(3.5)

    def test_duration_seconds_zero_when_not_set(self):
        stage = StageMetrics(name="test")
        assert stage.duration_seconds == 0.0

    def test_duration_seconds_zero_when_no_end(self):
        stage = StageMetrics(name="test", start_time=100.0)
        assert stage.duration_seconds == 0.0

    def test_success_rate_all_success(self):
        stage = StageMetrics(name="test", items_processed=10, items_failed=0)
        assert stage.success_rate == pytest.approx(1.0)

    def test_success_rate_partial(self):
        stage = StageMetrics(name="test", items_processed=7, items_failed=3)
        assert stage.success_rate == pytest.approx(0.7)

    def test_success_rate_all_failed(self):
        stage = StageMetrics(name="test", items_processed=0, items_failed=5)
        assert stage.success_rate == pytest.approx(0.0)

    def test_success_rate_zero_items(self):
        """Edge case: no items processed or failed."""
        stage = StageMetrics(name="test")
        assert stage.success_rate == 0.0


# ---------------------------------------------------------------------------
# PipelineMetrics
# ---------------------------------------------------------------------------


class TestPipelineMetrics:
    def test_start_and_end_stage(self):
        pm = PipelineMetrics(media_id="vid-1")
        pm.start_stage("extract")
        # Simulate work
        pm.end_stage("extract", items_processed=5, resolution="1920x1080")

        assert "extract" in pm.stages
        stage = pm.stages["extract"]
        assert stage.items_processed == 5
        assert stage.metadata == {"resolution": "1920x1080"}
        assert stage.duration_seconds > 0.0 or stage.end_time >= stage.start_time

    def test_end_stage_nonexistent_is_noop(self):
        pm = PipelineMetrics(media_id="vid-1")
        pm.end_stage("missing")  # should not raise
        assert "missing" not in pm.stages

    def test_total_duration(self):
        pm = PipelineMetrics(media_id="vid-1", pipeline_start=10.0, pipeline_end=15.5)
        assert pm.total_duration == pytest.approx(5.5)

    def test_total_duration_zero_when_not_finished(self):
        pm = PipelineMetrics(media_id="vid-1", pipeline_start=10.0)
        assert pm.total_duration == 0.0

    def test_to_dict_no_stages(self):
        pm = PipelineMetrics(media_id="vid-1")
        d = pm.to_dict()
        assert d["media_id"] == "vid-1"
        assert d["total_duration_seconds"] == 0.0
        assert d["stages"] == {}

    def test_to_dict_with_stages(self):
        pm = PipelineMetrics(media_id="vid-2", pipeline_start=1.0, pipeline_end=4.0)
        pm.stages["a"] = StageMetrics(
            name="a",
            start_time=1.0,
            end_time=2.5,
            items_processed=3,
            items_failed=1,
            metadata={"extra": "value"},
        )
        d = pm.to_dict()
        assert d["total_duration_seconds"] == 3.0
        stage_a = d["stages"]["a"]
        assert stage_a["duration_seconds"] == 1.5
        assert stage_a["items_processed"] == 3
        assert stage_a["items_failed"] == 1
        assert stage_a["success_rate"] == 0.75
        assert stage_a["extra"] == "value"

    def test_log_summary(self, caplog):
        pm = PipelineMetrics(media_id="vid-3", pipeline_start=0.0, pipeline_end=2.0)
        pm.stages["s1"] = StageMetrics(
            name="s1",
            start_time=0.0,
            end_time=1.0,
            items_processed=10,
            items_failed=0,
        )
        with caplog.at_level(logging.INFO):
            pm.log_summary()

        assert "vid-3" in caplog.text
        assert "s1" in caplog.text
        assert "100.0% success" in caplog.text

    def test_start_stage_returns_stage(self):
        pm = PipelineMetrics(media_id="vid-4")
        stage = pm.start_stage("x")
        assert isinstance(stage, StageMetrics)
        assert stage.name == "x"
        assert stage.start_time > 0


# ---------------------------------------------------------------------------
# ProcessingTimer
# ---------------------------------------------------------------------------


class TestProcessingTimer:
    def test_success_path(self):
        pm = PipelineMetrics(media_id="vid-5")
        with ProcessingTimer(pm, "step"):
            pass  # simulate work

        assert "step" in pm.stages
        stage = pm.stages["step"]
        # On success __exit__ does NOT call end_stage (caller is responsible)
        # start_time is set, end_time stays 0 unless caller explicitly ends
        assert stage.start_time > 0

    def test_error_path_records_failure(self):
        pm = PipelineMetrics(media_id="vid-6")
        with pytest.raises(ValueError, match="boom"), ProcessingTimer(pm, "bad_step"):
            raise ValueError("boom")

        stage = pm.stages["bad_step"]
        assert stage.items_failed == 1
        assert stage.metadata.get("error") == "boom"
        assert stage.end_time > 0

    def test_does_not_suppress_exceptions(self):
        pm = PipelineMetrics(media_id="vid-7")
        with pytest.raises(RuntimeError), ProcessingTimer(pm, "fail"):
            raise RuntimeError("oops")

    def test_nested_timers(self):
        pm = PipelineMetrics(media_id="vid-8")
        with ProcessingTimer(pm, "outer"), ProcessingTimer(pm, "inner"):
            pass
        assert "outer" in pm.stages
        assert "inner" in pm.stages


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_multiple_stages_ordering(self):
        pm = PipelineMetrics(media_id="vid-9")
        pm.start_stage("a")
        pm.start_stage("b")
        pm.end_stage("a", items_processed=1)
        pm.end_stage("b", items_processed=2)

        d = pm.to_dict()
        assert list(d["stages"].keys()) == ["a", "b"]

    def test_overwrite_stage(self):
        """Starting a stage again overwrites the previous one."""
        pm = PipelineMetrics(media_id="vid-10")
        pm.start_stage("dup")
        pm.end_stage("dup", items_processed=1)
        assert pm.stages["dup"].end_time > 0

        pm.start_stage("dup")  # overwrite
        assert pm.stages["dup"].end_time == 0.0
        assert pm.stages["dup"].items_processed == 0

    def test_to_dict_rounds_correctly(self):
        pm = PipelineMetrics(media_id="vid-11", pipeline_start=0.0, pipeline_end=1.1119)
        assert pm.to_dict()["total_duration_seconds"] == 1.112
