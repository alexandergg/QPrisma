"""
Authentication Routes

Provides user profile and Entra ID configuration endpoints.
Login/registration is handled by Microsoft Entra ID (MSAL) on the frontend.
"""

from fastapi import APIRouter, Depends

from api.dependencies import get_current_user
from core.config import settings
from models.api_schemas import (
    AuthConfigResponse,
    UserResponse,
)
from models.user import User

router = APIRouter(tags=["Authentication"])


# =============================================================================
# Routes
# =============================================================================


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_user)):
    """
    Get current user profile.

    Returns the profile of the authenticated user (token validated via Entra ID).
    """
    return UserResponse(
        id=current_user.id,
        email=current_user.email,
        name=current_user.full_name or current_user.email.split("@")[0],
    )


@router.get("/config", response_model=AuthConfigResponse)
async def get_auth_config():
    """
    Get Entra ID configuration for the frontend MSAL setup.

    Returns tenant ID, client ID, and API scope needed for MSAL initialization.
    This endpoint is public (no auth required).
    """
    return AuthConfigResponse(
        tenant_id=settings.auth.entra_tenant_id,
        client_id=settings.auth.entra_client_id,
        api_scope=settings.auth.entra_api_scope,
    )
