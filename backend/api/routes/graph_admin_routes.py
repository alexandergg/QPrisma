"""Operational/admin Knowledge Graph endpoints."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query

from api.dependencies import require_superuser
from core.exceptions import internal_error
from models.user import User

logger = logging.getLogger(__name__)

router = APIRouter()


def get_async_graph_service():
    from api.routes import graph_routes

    return graph_routes.get_async_graph_service()


@router.delete("/clear", include_in_schema=False)
async def clear_all_graph_data(
    confirm: bool = Query(False), _admin_user: User = Depends(require_superuser)
):
    """Delete all data from the Knowledge Graph after explicit confirmation."""
    if not confirm:
        raise HTTPException(
            status_code=400,
            detail="Must confirm deletion with ?confirm=true",
        )

    try:
        service = get_async_graph_service()
        await service.clear_all()
        return {"status": "success", "message": "All graph data has been deleted"}
    except Exception as e:
        logger.error("Failed to clear graph: %s", e, exc_info=True)
        raise internal_error() from e
