"""
Tests for models/user.py

Covers Pydantic validation for UserCreate (password strength),
UserInDB, User, Token, and TokenData models.
"""

from datetime import datetime

import pytest
from pydantic import ValidationError

from models.user import Token, TokenData, User, UserCreate, UserInDB


# =============================================================================
# UserCreate Password Validation
# =============================================================================


@pytest.mark.unit
class TestUserCreate:
    def test_valid_password(self):
        user = UserCreate(email="a@b.com", password="SecurePass1")
        assert user.password == "SecurePass1"

    def test_valid_password_with_full_name(self):
        user = UserCreate(email="a@b.com", password="SecurePass1", full_name="Test User")
        assert user.full_name == "Test User"

    def test_full_name_optional(self):
        user = UserCreate(email="a@b.com", password="SecurePass1")
        assert user.full_name is None

    @pytest.mark.parametrize(
        "password,reason",
        [
            ("Short1A", "too short (< 8 chars)"),
            ("Ab1", "way too short"),
            ("alllowercase1", "no uppercase"),
            ("ALLUPPERCASE1", "no lowercase"),
            ("NoDigitsHere", "no digit"),
        ],
    )
    def test_invalid_passwords(self, password, reason):
        with pytest.raises(ValidationError):
            UserCreate(email="a@b.com", password=password)

    @pytest.mark.parametrize(
        "password",
        [
            "Admin123",     # lowered = "admin123" in weak set
            "Qwerty123",    # lowered = "qwerty123" in weak set
        ],
    )
    def test_common_weak_passwords_rejected(self, password):
        with pytest.raises(ValidationError, match="too common"):
            UserCreate(email="a@b.com", password=password)

    def test_invalid_email(self):
        with pytest.raises(ValidationError):
            UserCreate(email="notanemail", password="SecurePass1")

    @pytest.mark.parametrize(
        "password",
        [
            "SecurePass1",
            "MyP@ssw0rd",
            "Abcdefg1",
            "TestUser123",
            "C0mplexPwd",
        ],
    )
    def test_valid_passwords_parametrized(self, password):
        user = UserCreate(email="a@b.com", password=password)
        assert user.password == password


# =============================================================================
# UserInDB
# =============================================================================


@pytest.mark.unit
class TestUserInDB:
    def test_all_fields(self):
        user = UserInDB(
            id="user_abc",
            email="a@b.com",
            hashed_password="$2b$12$hash",
            full_name="Test",
            is_active=True,
            is_superuser=False,
            created_at=datetime(2024, 1, 1),
            updated_at=datetime(2024, 1, 1),
        )
        assert user.id == "user_abc"
        assert user.hashed_password == "$2b$12$hash"

    def test_defaults(self):
        user = UserInDB(
            id="user_abc",
            email="a@b.com",
            hashed_password="$2b$12$hash",
        )
        assert user.is_active is True
        assert user.is_superuser is False
        assert user.full_name is None

    def test_created_at_has_default(self):
        user = UserInDB(
            id="user_abc",
            email="a@b.com",
            hashed_password="$2b$12$hash",
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

    def test_no_hashed_password_field(self):
        user = User(
            id="user_abc",
            email="a@b.com",
            created_at=datetime(2024, 1, 1),
            updated_at=datetime(2024, 1, 1),
        )
        assert not hasattr(user, "hashed_password")


# =============================================================================
# Token
# =============================================================================


@pytest.mark.unit
class TestToken:
    def test_creates_with_required_fields(self):
        token = Token(access_token="abc.def.ghi", expires_in=3600)
        assert token.access_token == "abc.def.ghi"
        assert token.expires_in == 3600

    def test_token_type_defaults_to_bearer(self):
        token = Token(access_token="abc.def.ghi", expires_in=3600)
        assert token.token_type == "bearer"


# =============================================================================
# TokenData
# =============================================================================


@pytest.mark.unit
class TestTokenData:
    def test_defaults_to_none(self):
        data = TokenData()
        assert data.user_id is None
        assert data.email is None

    def test_sets_values(self):
        data = TokenData(user_id="user_123", email="a@b.com")
        assert data.user_id == "user_123"
        assert data.email == "a@b.com"
