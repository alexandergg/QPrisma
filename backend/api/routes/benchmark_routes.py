"""Benchmark automation routes."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query

from api.dependencies import require_benchmark_operator
from core.errors import bad_request, internal_error, service_unavailable
from models.benchmark_schemas import (
    BenchmarkIngestBatchRequest,
    BenchmarkIngestBatchResponse,
    BenchmarkIngestRequest,
    BenchmarkIngestResponse,
    BenchmarkManifestRequest,
    BenchmarkManifestResponse,
    BenchmarkStatusResponse,
)
from models.user import User
from services.benchmark_ingest_service import get_benchmark_ingest_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/benchmark")


@router.post(
    "/ingest",
    response_model=BenchmarkIngestResponse,
    summary="Ingest one benchmark video from Blob",
)
async def ingest_benchmark_video(
    request: BenchmarkIngestRequest,
    operator: User | None = Depends(require_benchmark_operator),
):
    """Copy a staged benchmark blob into app media storage and queue processing."""
    service = get_benchmark_ingest_service()
    try:
        return await service.ingest_video(request)
    except TimeoutError as exc:
        raise service_unavailable(str(exc)) from exc
    except FileNotFoundError as exc:
        raise bad_request(str(exc)) from exc
    except ValueError as exc:
        raise bad_request(str(exc)) from exc
    except RuntimeError as exc:
        raise service_unavailable(str(exc)) from exc
    except Exception as exc:
        logger.error("Benchmark ingest failed: %s", exc, exc_info=True)
        raise internal_error(detail="Benchmark ingest failed") from exc


@router.post(
    "/ingest/batch",
    response_model=BenchmarkIngestBatchResponse,
    summary="Ingest multiple benchmark videos from Blob",
)
async def ingest_benchmark_batch(
    request: BenchmarkIngestBatchRequest,
    operator: User | None = Depends(require_benchmark_operator),
):
    """Sequentially ingest a small benchmark batch."""
    service = get_benchmark_ingest_service()
    items: list[BenchmarkIngestResponse] = []
    for item in request.videos:
        try:
            items.append(await service.ingest_video(item))
        except TimeoutError as exc:
            raise service_unavailable(str(exc)) from exc
        except FileNotFoundError as exc:
            raise bad_request(str(exc)) from exc
        except ValueError as exc:
            raise bad_request(str(exc)) from exc
        except RuntimeError as exc:
            raise service_unavailable(str(exc)) from exc
    return BenchmarkIngestBatchResponse(total=len(items), items=items)


@router.get(
    "/status",
    response_model=BenchmarkStatusResponse,
    summary="List benchmark ingest status",
)
async def get_benchmark_status(
    benchmark_name: str,
    user_id: str | None = None,
    benchmark_video_id: list[str] | None = Query(default=None),
    media_id: list[str] | None = Query(default=None),
    operator: User | None = Depends(require_benchmark_operator),
):
    """Return processing status for benchmark media rows."""
    service = get_benchmark_ingest_service()
    try:
        items = service.list_status(
            benchmark_name=benchmark_name,
            user_id=user_id,
            benchmark_video_ids=benchmark_video_id,
            media_ids=media_id,
        )
    except RuntimeError as exc:
        raise service_unavailable(str(exc)) from exc
    completed = sum(1 for item in items if item.processing_status == "completed")
    resolved_user_id = user_id or (items[0].user_id if items else "")
    return BenchmarkStatusResponse(
        benchmark_name=benchmark_name,
        user_id=resolved_user_id,
        total=len(items),
        completed=completed,
        items=items,
    )


@router.post(
    "/manifest",
    response_model=BenchmarkManifestResponse,
    summary="Build a benchmark manifest from stored media rows",
)
async def build_benchmark_manifest(
    request: BenchmarkManifestRequest,
    operator: User | None = Depends(require_benchmark_operator),
):
    """Assemble a reproducibility manifest for a benchmark run."""
    service = get_benchmark_ingest_service()
    try:
        manifest = service.build_manifest(request)
    except ValueError as exc:
        raise bad_request(str(exc)) from exc
    except RuntimeError as exc:
        raise service_unavailable(str(exc)) from exc
    except Exception as exc:
        logger.error("Benchmark manifest generation failed: %s", exc, exc_info=True)
        raise internal_error(detail="Benchmark manifest generation failed") from exc
    return BenchmarkManifestResponse(
        benchmark_name=request.benchmark_name,
        user_id=manifest["user_id"],
        video_count=len(manifest.get("videos", [])),
        manifest=manifest,
    )
