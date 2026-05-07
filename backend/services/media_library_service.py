"""Service-layer read/delete/search operations for media routes."""

import asyncio
import inspect
import json
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from core.degraded import DegradationImpact, record_degraded_operation
from core.exceptions import (
    AccessDeniedError,
    NotFoundError,
    QPrismaException,
    ServiceUnavailableError,
)

logger = logging.getLogger(__name__)

SasUrlFactory = Callable[[str, int], Awaitable[str | None]]
HydrateDataFactory = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]
GraphServiceFactory = Callable[[], Any]
GraphSearchServiceFactory = Callable[[], Any]


MediaLibraryError = QPrismaException
MediaNotFoundError = NotFoundError
MediaForbiddenError = AccessDeniedError
MediaStorageUnavailableError = ServiceUnavailableError


class MediaLibraryService:
    """Coordinates media library reads, deletion, hydration, and search formatting."""

    def __init__(
        self,
        *,
        db: Any,
        blob_service: Any | None,
        container_name: str,
        sas_url_factory: SasUrlFactory,
        hydrate_data_factory: HydrateDataFactory | None = None,
        graph_service_factory: GraphServiceFactory | None = None,
        graph_search_service_factory: GraphSearchServiceFactory | None = None,
    ) -> None:
        self.db = db
        self.blob_service = blob_service
        self.container_name = container_name
        self.sas_url_factory = sas_url_factory
        self.hydrate_data_factory = hydrate_data_factory
        self.graph_service_factory = graph_service_factory
        self.graph_search_service_factory = graph_search_service_factory

    def list_media(self, *, user_id: str, limit: int, offset: int) -> dict[str, Any]:
        """List media for a user with route-compatible response shaping."""
        media_list = self.db.get_media_by_user(user_id, limit=limit, offset=offset)

        items = []
        for media in media_list:
            item = media.to_dict()
            if item.get("video_metadata", {}) and item["video_metadata"].get("duration"):
                item["duration"] = item["video_metadata"]["duration"]
            if item.get("processing_result", {}) and item["processing_result"].get(
                "frames_analyzed"
            ):
                item["frames_analyzed"] = item["processing_result"]["frames_analyzed"]
            items.append(item)

        return {"total": len(items), "media": items, "limit": limit, "offset": offset}

    async def delete_media(self, *, media_id: str, user_id: str) -> dict[str, str]:
        """Delete media data from Blob Storage, graph storage, and PostgreSQL."""
        if not self.blob_service:
            raise ServiceUnavailableError("Azure Blob Storage")

        media = self._get_media_for_user(media_id=media_id, user_id=user_id)
        blob_name = media.blob_name

        if blob_name:
            try:
                blob_client = self.blob_service.get_blob_client(
                    container=self.container_name,
                    blob=blob_name,
                )
                await asyncio.get_running_loop().run_in_executor(None, blob_client.delete_blob)
            except Exception as exc:
                record_degraded_operation(
                    logger,
                    component="media",
                    operation="delete_blob",
                    impact=DegradationImpact.BLOB_DELETE,
                    exc=exc,
                )

        try:
            if self.graph_service_factory:
                kg_service = self.graph_service_factory()
                if kg_service:
                    delete_video_graph = kg_service.delete_video_graph
                    if inspect.iscoroutinefunction(delete_video_graph):
                        await delete_video_graph(media_id)
                    else:
                        await asyncio.get_running_loop().run_in_executor(
                            None,
                            delete_video_graph,
                            media_id,
                        )
        except Exception as exc:
            record_degraded_operation(
                logger,
                component="media",
                operation="delete_graph",
                impact=DegradationImpact.GRAPH_DELETE,
                exc=exc,
            )

        self.db.delete_media(media_id)
        return {"message": f"Media {media_id} deleted successfully"}

    async def get_media_metadata(self, *, media_id: str, user_id: str) -> dict[str, Any]:
        """Return media metadata with hydrated heavy fields and signed Blob URL."""
        media = self._get_media_for_user(media_id=media_id, user_id=user_id)
        self.db.update_media(media_id, {"last_accessed_at": datetime.now(UTC)})

        item = media.to_dict()
        if item.get("video_metadata", {}) and item["video_metadata"].get("duration"):
            item["duration"] = item["video_metadata"]["duration"]

        hydrate = self.hydrate_data_factory or self.hydrate_data_from_blob
        item = await hydrate(item)

        if item.get("blob_name"):
            blob_url = await self.sas_url_factory(item["blob_name"], 1)
            if blob_url:
                item["blob_url"] = blob_url

        return item

    def get_media_processing_status(self, *, media_id: str) -> dict[str, Any] | None:
        """Return persisted media processing status."""
        return self.db.get_media_status(media_id)

    async def get_video_audio_data(self, *, media_id: str, media: Any) -> dict[str, Any] | None:
        """Return transcription/audio data for an already-authorized media item."""
        item = media.to_dict()
        audio_data = item.get("audio_data")

        if item.get("audio_data_blob") and (not audio_data or "transcription" not in audio_data):
            try:
                audio_data = await self._download_json_blob(item["audio_data_blob"])
            except Exception as exc:
                record_degraded_operation(
                    logger,
                    component="media",
                    operation="hydrate_audio_endpoint_data",
                    impact=DegradationImpact.BLOB_HYDRATION,
                    exc=exc,
                )

        if not audio_data:
            return None

        return {
            "media_id": media_id,
            "audio_data": audio_data,
            "has_transcription": bool(audio_data.get("transcription", {}).get("text")),
            "language": audio_data.get("transcription", {}).get("language"),
            "duration": audio_data.get("transcription", {}).get("duration"),
            "word_count": audio_data.get("stats", {}).get("total_words", 0),
        }

    async def search_in_video(self, *, media_id: str, query: str, top: int) -> dict[str, Any]:
        """Search within a video and format graph results for the existing endpoint contract."""
        from models.graph_models import NodeType
        from services.graph_search_service import get_graph_search_service

        graph_search = (
            self.graph_search_service_factory()
            if self.graph_search_service_factory
            else get_graph_search_service()
        )
        graph_resp = await graph_search.hybrid_search(
            query_text=query,
            node_types=[NodeType.FRAME],
            video_id=media_id,
            limit=top,
            use_reranking=False,
        )

        formatted_results = []
        for result in graph_resp.results:
            content = result.content or {}
            formatted_results.append(
                {
                    "id": result.node_id,
                    "frame_number": int(content.get("frame_number", 0) or 0),
                    "timestamp": float(content.get("timestamp", 0.0) or 0.0),
                    "content": content.get("description") or "",
                    "score": float(result.combined_score or result.vector_score or 0.0),
                    "blob_name": "",
                    "transcript_text": content.get("transcript_text"),
                    "visual_description": content.get("visual_description"),
                    "detected_objects": content.get("detected_objects"),
                }
            )

        return {
            "query": query,
            "media_id": media_id,
            "total_results": len(formatted_results),
            "results": formatted_results,
            "source": "knowledge_graph",
        }

    async def hydrate_data_from_blob(self, item: dict[str, Any]) -> dict[str, Any]:
        """Hydrate heavy media fields from Blob Storage when present."""
        if not self.blob_service:
            return item

        if item.get("audio_data_blob") and (
            not item.get("audio_data") or "transcription" not in item.get("audio_data", {})
        ):
            try:
                item["audio_data"] = await self._download_json_blob(item["audio_data_blob"])
            except Exception as exc:
                record_degraded_operation(
                    logger,
                    component="media",
                    operation="hydrate_audio_data",
                    impact=DegradationImpact.BLOB_HYDRATION,
                    exc=exc,
                )

        if item.get("objects_data_blob") and (
            not item.get("objects_data") or "frames" not in item.get("objects_data", {})
        ):
            try:
                item["objects_data"] = await self._download_json_blob(item["objects_data_blob"])
            except Exception as exc:
                record_degraded_operation(
                    logger,
                    component="media",
                    operation="hydrate_objects_data",
                    impact=DegradationImpact.BLOB_HYDRATION,
                    exc=exc,
                )

        if item.get("frames_data_blob"):
            try:
                frames_data = await self._download_json_blob(item["frames_data_blob"])
                item["frames_data"] = frames_data

                if not item.get("objects_data"):
                    item["objects_data"] = {
                        "frames": [
                            {
                                "frame_number": frame.get("frame_number"),
                                "timestamp": frame.get("timestamp"),
                                "caption": frame.get("analysis"),
                                "detections": [],
                                "points": [],
                                "segmentation": [],
                            }
                            for frame in frames_data
                        ],
                        "objects": [],
                    }
            except Exception as exc:
                record_degraded_operation(
                    logger,
                    component="media",
                    operation="hydrate_frames_data",
                    impact=DegradationImpact.BLOB_HYDRATION,
                    exc=exc,
                )

        return item

    async def _download_json_blob(self, blob_name: str) -> Any:
        if not self.blob_service:
            raise ServiceUnavailableError("Azure Blob Storage")

        blob_client = self.blob_service.get_blob_client(
            container=self.container_name,
            blob=blob_name,
        )
        payload = await asyncio.get_running_loop().run_in_executor(
            None, lambda: blob_client.download_blob().readall()
        )
        return json.loads(payload)

    def _get_media_for_user(self, *, media_id: str, user_id: str) -> Any:
        media = self.db.get_media(media_id)
        if not media:
            raise NotFoundError("Media", media_id)
        if media.user_id != user_id:
            raise AccessDeniedError(
                "media",
                media_id,
                user_id=user_id,
                message="You don't have permission to access this media",
            )
        return media
