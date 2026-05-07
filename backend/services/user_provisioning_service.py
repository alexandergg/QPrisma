"""
User provisioning service for Microsoft Entra ID.

Handles auto-provisioning of users on first Entra ID login, including
email-matching to link existing local accounts to Entra identities.
"""

import logging

from core.exceptions import AccessDeniedError
from models.database import UserModel
from models.user import EntraTokenData, User
from services.database_service import get_database_service

logger = logging.getLogger(__name__)


class UserProvisioningService:
    """Find-or-create users from Entra ID token data."""

    def ensure_user_exists(self, token_data: EntraTokenData) -> User:
        """Return an active User for the given Entra token, creating one if needed.

        Lookup order:
        1. By ``entra_oid`` (fastest — already linked)
        2. By ``email`` (first Entra login for existing local user → link OID)
        3. Create a brand-new user record

        Returns:
            User pydantic model ready for API use.

        Raises:
            AccessDeniedError: if the matched user account is deactivated.
        """
        db = get_database_service()

        # 1. Try lookup by Entra OID
        user: UserModel | None = db.get_user_by_entra_oid(token_data.oid)

        # 2. Fall back to email match (links existing user on first Entra login)
        if user is None and token_data.email:
            user = db.get_user_by_email(token_data.email)
            if user is not None:
                db.update_user_entra_oid(user.id, token_data.oid)
                logger.info(
                    "Linked existing user %s (%s) to Entra OID %s",
                    user.id,
                    user.email,
                    token_data.oid,
                )

        # 3. Auto-provision new user
        if user is None:
            user = db.create_user(
                email=token_data.email or f"{token_data.oid}@entra.local",
                full_name=token_data.name,
                entra_oid=token_data.oid,
            )
            logger.info("Auto-provisioned new Entra user %s (%s)", user.id, user.email)

        if not user.is_active:
            raise AccessDeniedError("User account is deactivated")

        return User(
            id=user.id,
            email=user.email,
            full_name=user.full_name,
            is_active=user.is_active,
            is_superuser=user.is_superuser,
            created_at=user.created_at,
            updated_at=user.updated_at,
        )


# Singleton
_provisioning_instance: UserProvisioningService | None = None


def get_user_provisioning_service() -> UserProvisioningService:
    """Get singleton instance of UserProvisioningService."""
    global _provisioning_instance
    if _provisioning_instance is None:
        _provisioning_instance = UserProvisioningService()
    return _provisioning_instance
