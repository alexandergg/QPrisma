"""
User models for authentication and authorization.
"""

import re
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, field_validator


# Password validation regex
# At least 8 chars, 1 uppercase, 1 lowercase, 1 digit
PASSWORD_REGEX = re.compile(r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d).{8,}$")


class UserBase(BaseModel):
    """Base user model with common fields."""

    email: EmailStr
    full_name: str | None = None
    is_active: bool = True
    is_superuser: bool = False


class UserCreate(BaseModel):
    """Model for user registration."""

    email: EmailStr
    password: str = Field(
        ..., 
        min_length=8,
        description="Password must be at least 8 characters with uppercase, lowercase, and digit"
    )
    full_name: str | None = None

    @field_validator("password")
    @classmethod
    def validate_password_strength(cls, v: str) -> str:
        """
        Validate password meets minimum security requirements.
        
        Requirements:
        - At least 8 characters
        - At least one uppercase letter
        - At least one lowercase letter  
        - At least one digit
        """
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        
        if not PASSWORD_REGEX.match(v):
            raise ValueError(
                "Password must contain at least one uppercase letter, "
                "one lowercase letter, and one digit"
            )
        
        # Check for common weak passwords
        weak_passwords = {"password", "12345678", "qwerty123", "admin123"}
        if v.lower() in weak_passwords:
            raise ValueError("Password is too common. Please choose a stronger password.")
        
        return v


class UserLogin(BaseModel):
    """Model for user login."""

    email: EmailStr
    password: str


class UserInDB(UserBase):
    """User model as stored in database."""

    id: str = Field(..., description="Unique user identifier")
    hashed_password: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    model_config = {
        "json_schema_extra": {
            "example": {
                "id": "user_123abc",
                "email": "user@example.com",
                "full_name": "John Doe",
                "is_active": True,
                "is_superuser": False,
                "hashed_password": "$2b$12$...",
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


class Token(BaseModel):
    """JWT token response."""

    access_token: str
    token_type: str = "bearer"
    expires_in: int = Field(..., description="Token expiration time in seconds")


class TokenData(BaseModel):
    """Data encoded in JWT token."""

    user_id: str | None = None
    email: str | None = None
