"""Schemas for benchmark automation endpoints."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class BenchmarkIngestRequest(BaseModel):
    """Request to ingest one benchmark video from a staged source blob."""

    benchmark_name: str = Field(..., min_length=1, max_length=64)
    benchmark_video_id: str = Field(..., min_length=1, max_length=128)
    source_container: str = Field(..., min_length=1, max_length=128)
    source_blob_name: str = Field(..., min_length=1, max_length=1024)
    benchmark_split: str | None = Field(default=None, max_length=32)
    user_id: str | None = Field(default=None, max_length=64)
    original_filename: str | None = Field(default=None, max_length=512)
    preset: str | None = Field(default="benchmark", max_length=64)
    max_frames: int | None = Field(default=None, ge=1)
    content_type: str | None = Field(default=None, max_length=128)


class BenchmarkIngestBatchRequest(BaseModel):
    """Batch ingest request."""

    videos: list[BenchmarkIngestRequest] = Field(..., min_length=1, max_length=100)


class BenchmarkIngestResponse(BaseModel):
    """Result of one benchmark ingest request."""

    benchmark_name: str
    benchmark_video_id: str
    benchmark_split: str | None = None
    user_id: str
    media_id: str
    blob_name: str
    source_blob_name: str
    job_id: str | None = None
    processing_status: str
    ingest_status: str


class BenchmarkIngestBatchResponse(BaseModel):
    """Result of a batch ingest request."""

    total: int
    items: list[BenchmarkIngestResponse]


class BenchmarkStatusItem(BaseModel):
    """Status for one benchmark media row."""

    benchmark_name: str
    benchmark_video_id: str
    benchmark_split: str | None = None
    user_id: str
    media_id: str
    blob_name: str
    job_id: str | None = None
    processing_status: str
    processed: bool
    last_updated: str | None = None


class BenchmarkStatusResponse(BaseModel):
    """Status view over one benchmark ingest set."""

    benchmark_name: str
    user_id: str
    total: int
    completed: int
    items: list[BenchmarkStatusItem]


class BenchmarkManifestRequest(BaseModel):
    """Request to assemble a reproducibility manifest for benchmark media."""

    benchmark_name: str = Field(..., min_length=1, max_length=64)
    user_id: str | None = Field(default=None, max_length=64)
    benchmark_video_ids: list[str] | None = Field(default=None, max_length=1000)
    media_ids: list[str] | None = Field(default=None, max_length=1000)
    version: str = Field(default="lmms-lab/Video-MME@main", max_length=256)
    license: str = Field(default="academic-only-no-redistribution", max_length=256)
    eval_mode: Literal["mcq", "pairwise_winrate", "freeform_grounding"] = "mcq"
    response_format: str = Field(default="letter_only", max_length=64)
    judge_model: str = Field(default="", max_length=128)
    n_judge_runs: int = Field(default=1, ge=1, le=10)
    judge_temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    frame_sampling_fps: float | None = Field(default=None, gt=0.0)
    max_frames: int | None = Field(default=None, ge=1)
    subtitle_mode: Literal["with", "without"] | None = None
    agent_commit_sha: str | None = Field(default=None, max_length=64)


class BenchmarkManifestResponse(BaseModel):
    """Serialized benchmark manifest payload."""

    benchmark_name: str
    user_id: str
    video_count: int
    manifest: dict[str, Any]
