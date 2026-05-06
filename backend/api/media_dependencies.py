"""Media ownership and storage-tiering dependency helpers."""

from fastapi import HTTPException

from models.user import User


def get_storage_tiering_service():
    """Get or create Storage Tiering Service singleton."""
    import api.dependencies as deps

    if deps._storage_tiering_service is None:
        from services.storage_tiering_service import StorageTieringService

        deps._storage_tiering_service = StorageTieringService()
    return deps._storage_tiering_service


def get_media_or_404(
    media_id: str,
    current_user: User,
    *,
    allow_superuser: bool = True,
):
    """Fetch media and enforce ownership."""
    import api.dependencies as deps

    db = deps.get_database_service()
    media = db.get_media(media_id)
    if not media:
        raise HTTPException(status_code=404, detail="Media not found")
    if media.user_id != current_user.id and (not allow_superuser or not current_user.is_superuser):
        raise HTTPException(status_code=403, detail="Not authorized")
    return media


def get_user_media_ids(
    current_user: User,
    *,
    processed_only: bool = False,
) -> list[str]:
    """Return the current user's media IDs, optionally restricted to processed items."""
    import api.dependencies as deps

    db = deps.get_database_service()
    return db.get_user_media_ids(current_user.id, processed_only=processed_only)


def get_graph_node_media_or_404(
    node_id: str,
    current_user: User,
    *,
    allow_superuser: bool = True,
):
    """Resolve a graph node to its video and enforce media ownership."""
    import api.dependencies as deps

    graph_service = deps.get_knowledge_graph_service()
    video_id = graph_service.get_node_video_id(node_id)
    if not video_id:
        raise HTTPException(status_code=404, detail="Graph node not found")
    return deps.get_media_or_404(video_id, current_user, allow_superuser=allow_superuser)
