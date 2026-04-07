"""
Structure Routes

Handles video structure (scenes, chapters) endpoints.
Uses PostgreSQL for metadata storage (replaces Cosmos DB).
"""

import logging

from fastapi import APIRouter, Depends, HTTPException

from api.dependencies import get_blob_service, get_current_user, get_storage_container_name
from models.user import User
from services.database_service import get_database_service

router = APIRouter(tags=["Structure"])
logger = logging.getLogger(__name__)


# =============================================================================
# Routes
# =============================================================================


@router.get("/media/{media_id}/structure")
async def get_video_structure(media_id: str, current_user: User = Depends(get_current_user)):
    """
    Get the scene/chapter structure for a video.

    Returns hierarchical video structure with:
    - Scenes with summaries and timestamps
    - Chapters grouping related scenes
    - Video-level summary and key topics
    """
    db = get_database_service()
    media = db.get_media(media_id)
    if media and media.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")
    if media is None:
        # No Postgres record — only allow graph fallback if we can verify ownership later.
        # The graph result will be checked below; if the graph video node also lacks a
        # user_id we cannot prove ownership, so we treat it as not found.
        pass

    try:
        media_dict = media.to_dict() if media else None

        from services.knowledge_graph import get_knowledge_graph_service
        from services.structure_service import StructureService

        graph = get_knowledge_graph_service()
        structure_service = StructureService(
            graph_service=graph,
            blob_service=get_blob_service(),
            storage_container=get_storage_container_name(),
        )
        result = structure_service.get_structure(media_id, media_dict)
    except Exception as e:
        logger.error(f"Failed to get video structure for media_id={media_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="An internal error occurred") from e

    if result:
        # Verify ownership via graph video node
        video_user_id = result.get("video_user_id")
        if video_user_id and video_user_id != current_user.id:
            raise HTTPException(status_code=403, detail="Access denied")
        # If media is missing in Postgres and graph node lacks user_id,
        # we cannot verify ownership — deny access to prevent tenant leakage.
        if media is None and not video_user_id:
            raise HTTPException(status_code=404, detail="Media not found")

        return {"media_id": media_id, **result}

    if media is None:
        raise HTTPException(status_code=404, detail="Media not found")

    raise HTTPException(status_code=404, detail="Video structure not available yet.")
