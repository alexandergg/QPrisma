"""
Benchmark adapters for Azure AI Foundry evaluation
==================================================

Each benchmark (Video-MME, VideoRAG/LongerVideos) ships:

1. An ``ingest`` CLI that replays the production media-upload path against a
   stable benchmark user, tagging rows with ``benchmark_name`` /
   ``benchmark_video_id`` so they can be cleaned up later.
2. An ``emit_foundry_data`` CLI that walks the resulting manifest and emits
   the JSONL file consumed by ``microsoft/ai-agent-evals`` (uses the existing
   ``[QPRISMA_CONTEXT:{...}]`` envelope plus an additive ``[QPRISMA_BENCH:{...}]``
   envelope that hosted-agent benchmark paths parse and non-benchmark paths
   never emit).
3. A ``BenchmarkManifest`` (this module) describing what was ingested — pinned
   judge model, dataset version, license, and the ``media_id`` ↔
   ``benchmark_video_id`` mapping for reproducibility.

The manifest is the single source of truth a Foundry run reads to attach
``benchmark_*`` tags to every result row.

Read ``data/datasets/_private/README.md`` for how to populate inputs and
``docs/EVALUATION_GUIDE.md`` for the full workflow.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------

EvalMode = Literal["mcq", "pairwise_winrate", "freeform_grounding"]
"""Format the evaluator should expect from the agent.

* ``mcq``                — single-letter answer (Video-MME).
* ``pairwise_winrate``  — long-form text scored against a baseline.
* ``freeform_grounding`` — long-form text scored on grounding/temporal evidence.
"""


@dataclass(frozen=True)
class BenchmarkVideo:
    """One ingested benchmark video and its mapping back to the source dataset."""

    benchmark_video_id: str
    media_id: str
    duration_bucket: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class BenchmarkManifest:
    """Reproducibility manifest emitted by every benchmark ingest run.

    Stored next to the dataset under ``data/datasets/_private/<name>/manifest.json``
    and uploaded as a workflow artifact so each Foundry run can be traced back
    to an exact dataset snapshot, judge configuration, and agent commit.
    """

    name: str
    """Stable benchmark identifier (``video_mme``, ``videorag``)."""

    version: str
    """Dataset version (e.g. HuggingFace dataset revision or upstream tag)."""

    license: str
    """Short human-readable license note (e.g. ``academic-only-no-redistribution``)."""

    user_id: str
    """User account that owns the ingested ``media_id`` rows."""

    eval_mode: EvalMode
    """How the evaluator scores rows from this benchmark."""

    format: str
    """Expected response shape (``letter_only``, ``free_text``)."""

    judge_model: str
    """Pinned judge deployment name (when applicable). ``""`` for deterministic evaluators."""

    n_judge_runs: int = 1
    """Number of judge invocations to average per row (mitigates LLM-judge variance)."""

    judge_temperature: float = 0.0
    """Judge sampling temperature; pinned for reproducibility."""

    frame_sampling_fps: float | None = None
    """Frame-sampling FPS the agent used during ingest (recorded for cross-cloud comparability)."""

    max_frames: int | None = None
    """Frame cap the agent used during ingest."""

    subtitle_mode: str | None = None
    """``with``, ``without``, or ``None`` if the benchmark does not distinguish."""

    agent_commit_sha: str | None = None
    """Git SHA of the agent under test (set by the workflow)."""

    dataset_hash: str | None = None
    """Stable hash of the ingested ``BenchmarkVideo`` set for change detection."""

    videos: list[BenchmarkVideo] = field(default_factory=list)
    """``benchmark_video_id`` ↔ ``media_id`` mapping for every ingested row."""

    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    # ------------------------------------------------------------------
    # Serialization helpers
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation."""
        return asdict(self)

    def write(self, path: Path) -> None:
        """Persist the manifest to ``path`` (parent dirs are created)."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2) + "\n", encoding="utf-8")

    @classmethod
    def read(cls, path: Path) -> BenchmarkManifest:
        """Load a previously persisted manifest."""
        raw = json.loads(path.read_text(encoding="utf-8"))
        videos = [BenchmarkVideo(**v) for v in raw.pop("videos", [])]
        return cls(videos=videos, **raw)


__all__ = [
    "BenchmarkManifest",
    "BenchmarkVideo",
    "EvalMode",
]
