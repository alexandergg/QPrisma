"""
Tests for models/user.py

Covers Pydantic validation for UserInDB, User, and EntraTokenData models.
"""

from datetime import datetime

import pytest
from pydantic import ValidationError

from models.user import EntraTokenData, User, UserInDB

# =============================================================================
# UserInDB
# =============================================================================


@pytest.mark.unit
class TestUserInDB:
    def test_all_fields(self):
        user = UserInDB(
            id="user_abc",
            email="a@b.com",
            full_name="Test",
            entra_oid="entra-oid-123",
            is_active=True,
            is_superuser=False,
            created_at=datetime(2024, 1, 1),
            updated_at=datetime(2024, 1, 1),
        )
        assert user.id == "user_abc"
        assert user.entra_oid == "entra-oid-123"

    def test_defaults(self):
        user = UserInDB(
            id="user_abc",
            email="a@b.com",
        )
        assert user.is_active is True
        assert user.is_superuser is False
        assert user.full_name is None
        assert user.entra_oid is None

    def test_created_at_has_default(self):
        user = UserInDB(
            id="user_abc",
            email="a@b.com",
        )
        assert user.created_at is not None
        assert isinstance(user.created_at, datetime)


# =============================================================================
# User (API response model)
# =============================================================================


@pytest.mark.unit
class TestUser:
    def test_creates_with_required_fields(self):
        user = User(
            id="user_abc",
            email="a@b.com",
            created_at=datetime(2024, 1, 1),
            updated_at=datetime(2024, 1, 1),
        )
        assert user.id == "user_abc"
        assert user.email == "a@b.com"

    def test_no_sensitive_fields(self):
        user = User(
            id="user_abc",
            email="a@b.com",
            created_at=datetime(2024, 1, 1),
            updated_at=datetime(2024, 1, 1),
        )
        assert not hasattr(user, "hashed_password")
        assert not hasattr(user, "entra_oid")


# =============================================================================
# EntraTokenData
# =============================================================================


@pytest.mark.unit
class TestEntraTokenData:
    def test_required_oid(self):
        data = EntraTokenData(oid="entra-oid-123")
        assert data.oid == "entra-oid-123"
        assert data.email is None
        assert data.name is None

    def test_all_fields(self):
        data = EntraTokenData(oid="entra-oid-123", email="a@b.com", name="Test User")
        assert data.oid == "entra-oid-123"
        assert data.email == "a@b.com"
        assert data.name == "Test User"

    def test_oid_required(self):
        with pytest.raises(ValidationError):
            EntraTokenData(email="a@b.com")
