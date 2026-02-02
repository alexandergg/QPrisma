"""
Authentication Routes

Handles user registration, login, and token management.
"""

from fastapi import APIRouter, Depends, HTTPException

from api.dependencies import get_auth_service, get_current_user
from models.api_schemas import (
    LoginRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)
from models.user import User

router = APIRouter(tags=["Authentication"])


# =============================================================================
# Routes
# =============================================================================


@router.post("/register", response_model=TokenResponse)
async def register(request: RegisterRequest):
    """
    Register a new user.

    Creates a new user account and returns an access token.
    """
    auth_service = get_auth_service()

    result = auth_service.register(
        email=request.email,
        password=request.password,
        name=request.name,
    )

    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])

    return TokenResponse(access_token=result["access_token"])


@router.post("/login", response_model=TokenResponse)
async def login(request: LoginRequest):
    """
    Authenticate user and get access token.

    Returns a JWT token for authenticated requests.
    """
    auth_service = get_auth_service()

    result = auth_service.login(
        email=request.email,
        password=request.password,
    )

    if "error" in result:
        raise HTTPException(status_code=401, detail=result["error"])

    return TokenResponse(access_token=result["access_token"])


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_user)):
    """
    Get current user profile.

    Returns the profile of the authenticated user.
    """
    return UserResponse(
        id=current_user.id,
        email=current_user.email,
        name=current_user.full_name or current_user.email.split("@")[0],
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(current_user: User = Depends(get_current_user)):
    """
    Refresh access token.

    Returns a new access token for the authenticated user.
    """
    auth_service = get_auth_service()

    new_token = auth_service.create_access_token(
        data={"sub": current_user.id, "email": current_user.email}
    )

    return TokenResponse(access_token=new_token)
