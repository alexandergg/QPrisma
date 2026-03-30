"""
Authentication Routes

Handles user registration, login, and token management.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from api.dependencies import get_auth_service, get_current_user, get_token_from_header
from api.rate_limit import limiter
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
@limiter.limit("5/minute")
async def register(request: Request, body: RegisterRequest, response: Response):
    """
    Register a new user.

    Creates a new user account and returns an access token.
    """
    auth_service = get_auth_service()

    result = auth_service.register(
        email=body.email,
        password=body.password,
        name=body.name,
    )

    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])

    return TokenResponse(access_token=result["access_token"])


@router.post("/login", response_model=TokenResponse)
@limiter.limit("10/minute")
async def login(request: Request, body: LoginRequest, response: Response):
    """
    Authenticate user and get access token.

    Returns a JWT token for authenticated requests.
    """
    auth_service = get_auth_service()

    result = auth_service.login(
        email=body.email,
        password=body.password,
    )

    if "error" in result:
        raise HTTPException(status_code=401, detail=result["error"])

    return TokenResponse(access_token=result["access_token"])


@router.post("/logout")
@limiter.limit("10/minute")
async def logout(
    request: Request,
    response: Response,
    current_user: User = Depends(get_current_user),
    token: str = Depends(get_token_from_header),
):
    """
    Logout and revoke the current JWT token.

    Invalidates the token so it can no longer be used for authentication.
    """
    auth_service = get_auth_service()
    await auth_service.revoke_token(token)
    return {"message": "Successfully logged out"}


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
