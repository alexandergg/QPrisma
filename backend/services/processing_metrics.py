"""Processing pipeline metrics and timing for QPrisma."""

import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class StageMetrics:
    """Metrics for a single processing stage."""

    name: str
    start_time: float = 0.0
    end_time: float = 0.0
    items_processed: int = 0
    items_failed: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def duration_seconds(self) -> float:
        if self.end_time and self.start_time:
            return self.end_time - self.start_time
        return 0.0

    @property
    def success_rate(self) -> float:
        total = self.items_processed + self.items_failed
        return self.items_processed / total if total > 0 else 0.0


@dataclass
class PipelineMetrics:
    """Aggregated metrics for a complete processing pipeline run."""

    media_id: str
    stages: dict[str, StageMetrics] = field(default_factory=dict)
    pipeline_start: float = 0.0
    pipeline_end: float = 0.0

    def start_stage(self, name: str) -> StageMetrics:
        stage = StageMetrics(name=name, start_time=time.monotonic())
        self.stages[name] = stage
        return stage

    def end_stage(
        self,
        name: str,
        items_processed: int = 0,
        items_failed: int = 0,
        **metadata: Any,
    ) -> None:
        if name in self.stages:
            stage = self.stages[name]
            stage.end_time = time.monotonic()
            stage.items_processed = items_processed
            stage.items_failed = items_failed
            stage.metadata.update(metadata)

    @property
    def total_duration(self) -> float:
        if self.pipeline_end > 0:
            return self.pipeline_end - self.pipeline_start
        return 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "media_id": self.media_id,
            "total_duration_seconds": round(self.total_duration, 3),
            "stages": {
                name: {
                    "duration_seconds": round(s.duration_seconds, 3),
                    "items_processed": s.items_processed,
                    "items_failed": s.items_failed,
                    "success_rate": round(s.success_rate, 3),
                    **s.metadata,
                }
                for name, s in self.stages.items()
            },
        }

    def log_summary(self) -> None:
        """Log a structured summary of the pipeline run."""
        summary = self.to_dict()
        logger.info(
            "Pipeline completed for %s in %ss",
            self.media_id,
            summary["total_duration_seconds"],
            extra={"pipeline_metrics": summary},
        )
        for name, stage_data in summary["stages"].items():
            logger.info(
                "  Stage '%s': %ss, %d items, %.1f%% success",
                name,
                stage_data["duration_seconds"],
                stage_data["items_processed"],
                stage_data["success_rate"] * 100,
            )


class ProcessingTimer:
    """Context manager for timing processing stages."""

    def __init__(self, metrics: PipelineMetrics, stage_name: str):
        self._metrics = metrics
        self._stage_name = stage_name

    def __enter__(self):
        self._metrics.start_stage(self._stage_name)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type:
            self._metrics.end_stage(self._stage_name, items_failed=1, error=str(exc_val))
        return False  # Don't suppress exceptions
