"""
User models for authentication and authorization.

Authentication is handled via Microsoft Entra ID (OIDC).
"""

from datetime import UTC, datetime

from pydantic import BaseModel, EmailStr, Field


class UserBase(BaseModel):
    """Base user model with common fields."""

    email: EmailStr
    full_name: str | None = None
    is_active: bool = True
    is_superuser: bool = False


class UserInDB(UserBase):
    """User model as stored in database."""

    id: str = Field(..., description="Unique user identifier")
    entra_oid: str | None = Field(default=None, description="Microsoft Entra ID Object ID")
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    model_config = {
        "json_schema_extra": {
            "example": {
                "id": "user_123abc",
                "email": "user@example.com",
                "full_name": "John Doe",
                "is_active": True,
                "is_superuser": False,
                "entra_oid": "00000000-0000-0000-0000-000000000000",
                "created_at": "2024-01-01T00:00:00Z",
                "updated_at": "2024-01-01T00:00:00Z",
            }
        }
    }


class User(UserBase):
    """User model for API responses (without sensitive data)."""

    id: str
    created_at: datetime
    updated_at: datetime

    model_config = {
        "json_schema_extra": {
            "example": {
                "id": "user_123abc",
                "email": "user@example.com",
                "full_name": "John Doe",
                "is_active": True,
                "is_superuser": False,
                "created_at": "2024-01-01T00:00:00Z",
                "updated_at": "2024-01-01T00:00:00Z",
            }
        }
    }


class EntraTokenData(BaseModel):
    """Data decoded from a Microsoft Entra ID token."""

    oid: str = Field(..., description="Entra Object ID (unique per user)")
    email: str | None = None
    name: str | None = None
