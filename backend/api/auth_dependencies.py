"""Authentication and authorization dependencies for API routes."""

import secrets

from fastapi import Depends, Header, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from core.config import settings
from models.user import User

security = HTTPBearer()
security_optional = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> User:
    """
    Validate Entra ID Bearer token and return current user.

    Auto-provisions user in PostgreSQL on first login (email-matched to existing records).
    """
    from services.entra_auth_service import get_entra_auth_service
    from services.user_provisioning_service import get_user_provisioning_service

    try:
        token_data = await get_entra_auth_service().verify_token(credentials.credentials)
        return get_user_provisioning_service().ensure_user_exists(token_data)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token") from None


async def get_current_user_optional(
    credentials: HTTPAuthorizationCredentials | None = Depends(security_optional),
) -> User | None:
    """
    Optionally validate Entra ID token and return current user.

    Returns None if no token is provided or if token is invalid.
    """
    if credentials is None:
        return None

    from services.entra_auth_service import get_entra_auth_service
    from services.user_provisioning_service import get_user_provisioning_service

    try:
        token_data = await get_entra_auth_service().verify_token(credentials.credentials)
        return get_user_provisioning_service().ensure_user_exists(token_data)
    except Exception:
        return None


async def require_superuser(current_user: User = Depends(get_current_user)) -> User:
    """Require an authenticated superuser for operational/admin endpoints."""
    if not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user


async def require_benchmark_operator(
    current_user: User | None = Depends(get_current_user_optional),
    benchmark_token: str | None = Header(default=None, alias="X-Benchmark-Token"),
) -> User | None:
    """Authorize benchmark automation via superuser bearer token or shared secret."""
    if current_user and current_user.is_superuser:
        return current_user

    configured_token = settings.benchmark.api_token
    if (
        configured_token
        and benchmark_token
        and secrets.compare_digest(benchmark_token, configured_token)
    ):
        return None

    if current_user is not None:
        raise HTTPException(status_code=403, detail="Benchmark automation requires admin access")
    raise HTTPException(status_code=401, detail="Benchmark automation credentials required")
