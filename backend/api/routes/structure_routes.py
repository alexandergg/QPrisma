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

    # First, try Neo4j graph (primary source for structure)
    try:
        from services.knowledge_graph import get_knowledge_graph_service
        from services.structure_service import StructureService

        graph = get_knowledge_graph_service()
        structure_service = StructureService(graph_service=graph)
        result = structure_service.get_structure_from_graph(media_id)

        if result:
            # Verify ownership
            video_user_id = result.get("video_user_id")
            if video_user_id and video_user_id != current_user.id:
                raise HTTPException(status_code=403, detail="Access denied")

            return {
                "media_id": media_id,
                "structure": result["structure"],
                "processing_method": result["processing_method"],
                "processed_at": result["processed_at"],
            }

    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"Graph structure not available, falling back to PostgreSQL: {e}")

    # Fallback to PostgreSQL for legacy data
    try:
        media = db.get_media(media_id)
        if not media:
            raise HTTPException(status_code=404, detail="Media not found")

        if media.user_id != current_user.id:
            raise HTTPException(status_code=403, detail="Access denied")

        item = media.to_dict()

        from services.structure_service import StructureService

        blob_service = get_blob_service()
        structure_service = StructureService(
            graph_service=None,
            blob_service=blob_service,
            storage_container=get_storage_container_name(),
        )
        result = structure_service.get_structure_from_legacy(item)

        if result:
            return {
                "media_id": media_id,
                **result,
            }

        raise HTTPException(status_code=404, detail="Video structure not available yet.")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get video structure for media_id={media_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="An internal error occurred") from e
