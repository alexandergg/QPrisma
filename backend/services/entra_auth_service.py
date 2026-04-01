"""
Microsoft Entra ID authentication service.

Validates Entra ID JWT tokens using OIDC JWKS discovery.
Replaces the legacy local JWT/password authentication.
"""

import logging

import jwt
from fastapi import HTTPException, status
from jwt import PyJWKClient

from core.config import settings
from models.user import EntraTokenData

logger = logging.getLogger(__name__)


class EntraAuthService:
    """Validates Microsoft Entra ID JWT tokens via JWKS endpoint."""

    def __init__(self, tenant_id: str, client_id: str) -> None:
        self._tenant_id = tenant_id
        self._client_id = client_id
        # Accept both v1 and v2 issuer formats — the actual format depends on
        # the accessTokenAcceptedVersion in the API app registration in Azure.
        self._issuers = [
            f"https://login.microsoftonline.com/{tenant_id}/v2.0",
            f"https://sts.windows.net/{tenant_id}/",
        ]
        jwks_url = f"https://login.microsoftonline.com/{tenant_id}/discovery/v2.0/keys"
        self._jwks_client = PyJWKClient(jwks_url, cache_keys=True)

    async def verify_token(self, token: str) -> EntraTokenData:
        """Validate an Entra ID Bearer token and return decoded claims.

        Raises:
            HTTPException 401: if the token is invalid, expired, or untrusted.
        """
        credentials_exception = HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate Entra ID credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

        try:
            signing_key = self._jwks_client.get_signing_key_from_jwt(token)
            payload = jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],
                audience=self._client_id,
                issuer=self._issuers,
                options={"require": ["exp", "iss", "aud", "oid"]},
            )

            oid: str = payload["oid"]
            email = payload.get("preferred_username") or payload.get("email")
            name = payload.get("name")

            return EntraTokenData(oid=oid, email=email, name=name)

        except jwt.ExpiredSignatureError:
            logger.warning("Entra ID token expired")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token has expired",
                headers={"WWW-Authenticate": "Bearer"},
            ) from None
        except (jwt.InvalidTokenError, Exception) as exc:
            logger.warning("Entra ID token validation failed: %s", exc)
            raise credentials_exception from None


# Singleton
_entra_auth_instance: EntraAuthService | None = None


def get_entra_auth_service() -> EntraAuthService:
    """Get singleton instance of EntraAuthService."""
    global _entra_auth_instance
    if _entra_auth_instance is None:
        _entra_auth_instance = EntraAuthService(
            tenant_id=settings.auth.entra_tenant_id,
            client_id=settings.auth.entra_client_id,
        )
    return _entra_auth_instance
