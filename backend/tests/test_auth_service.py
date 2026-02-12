"""
Tests for services/auth_service.py

Covers password hashing, JWT token lifecycle, user creation,
authentication, login, and registration flows.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from freezegun import freeze_time

from models.user import UserCreate

# =============================================================================
# Password Hashing
# =============================================================================


@pytest.mark.unit
class TestPasswordHashing:
    def test_hash_returns_bcrypt_format(self, auth_service):
        hashed = auth_service.hash_password("SecurePass1")
        assert hashed.startswith("$2b$")

    def test_same_password_different_hashes(self, auth_service):
        h1 = auth_service.hash_password("SecurePass1")
        h2 = auth_service.hash_password("SecurePass1")
        assert h1 != h2  # salt differs

    def test_verify_correct_password(self, auth_service):
        hashed = auth_service.hash_password("SecurePass1")
        assert auth_service.verify_password("SecurePass1", hashed) is True

    def test_verify_incorrect_password(self, auth_service):
        hashed = auth_service.hash_password("SecurePass1")
        assert auth_service.verify_password("WrongPass1", hashed) is False

    def test_verify_empty_password(self, auth_service):
        hashed = auth_service.hash_password("SecurePass1")
        assert auth_service.verify_password("", hashed) is False


# =============================================================================
# JWT Tokens
# =============================================================================


@pytest.mark.unit
class TestJWTTokens:
    def test_create_access_token_decodable(self, auth_service):
        token = auth_service.create_access_token({"sub": "user_123", "email": "a@b.com"})
        assert isinstance(token, str)
        assert len(token) > 20

    def test_verify_valid_access_token(self, auth_service):
        token = auth_service.create_access_token({"sub": "user_123", "email": "a@b.com"})
        data = auth_service.verify_token(token)
        assert data.user_id == "user_123"
        assert data.email == "a@b.com"

    def test_create_refresh_token(self, auth_service):
        token = auth_service.create_refresh_token({"sub": "user_123", "email": "a@b.com"})
        data = auth_service.verify_token(token, token_type="refresh")
        assert data.user_id == "user_123"

    def test_verify_expired_token_raises_401(self, auth_service):
        with freeze_time("2024-01-01"):
            token = auth_service.create_access_token(
                {"sub": "user_123"}, expires_delta=timedelta(minutes=1)
            )
        with freeze_time("2024-01-02"):
            with pytest.raises(HTTPException) as exc_info:
                auth_service.verify_token(token)
            assert exc_info.value.status_code == 401

    def test_verify_wrong_token_type_raises_401(self, auth_service):
        # Create refresh token, verify as access
        token = auth_service.create_refresh_token({"sub": "user_123"})
        with pytest.raises(HTTPException) as exc_info:
            auth_service.verify_token(token, token_type="access")
        assert exc_info.value.status_code == 401

    def test_verify_tampered_token_raises_401(self, auth_service):
        token = auth_service.create_access_token({"sub": "user_123"})
        tampered = token[:-5] + "XXXXX"
        with pytest.raises(HTTPException) as exc_info:
            auth_service.verify_token(tampered)
        assert exc_info.value.status_code == 401

    def test_verify_token_missing_sub_raises_401(self, auth_service):
        # Token without "sub" claim
        token = auth_service.create_access_token({"email": "a@b.com"})
        with pytest.raises(HTTPException) as exc_info:
            auth_service.verify_token(token)
        assert exc_info.value.status_code == 401

    def test_custom_expiry_delta(self, auth_service):
        token = auth_service.create_access_token(
            {"sub": "user_123"}, expires_delta=timedelta(hours=2)
        )
        data = auth_service.verify_token(token)
        assert data.user_id == "user_123"

    def test_get_token_expiry_seconds(self, auth_service):
        expected = auth_service.access_token_expire_minutes * 60
        assert auth_service.get_token_expiry_seconds() == expected

    def test_verify_garbage_string_raises_401(self, auth_service):
        with pytest.raises(HTTPException) as exc_info:
            auth_service.verify_token("not.a.jwt")
        assert exc_info.value.status_code == 401


# =============================================================================
# Create User
# =============================================================================


@pytest.mark.unit
class TestCreateUser:
    def test_returns_user_in_db(self, auth_service):
        user_data = UserCreate(email="new@example.com", password="SecurePass1", full_name="New")
        user = auth_service.create_user(user_data)
        assert user.email == "new@example.com"
        assert user.full_name == "New"

    def test_hashes_password(self, auth_service):
        user_data = UserCreate(email="new@example.com", password="SecurePass1")
        user = auth_service.create_user(user_data)
        assert user.hashed_password != "SecurePass1"
        assert user.hashed_password.startswith("$2b$")

    def test_generates_uuid_prefixed_id(self, auth_service):
        user_data = UserCreate(email="new@example.com", password="SecurePass1")
        user = auth_service.create_user(user_data)
        assert user.id.startswith("user_")
        assert len(user.id) > 5

    def test_sets_timestamps(self, auth_service):
        user_data = UserCreate(email="new@example.com", password="SecurePass1")
        user = auth_service.create_user(user_data)
        assert user.created_at is not None
        assert user.updated_at is not None

    def test_sets_defaults(self, auth_service):
        user_data = UserCreate(email="new@example.com", password="SecurePass1")
        user = auth_service.create_user(user_data)
        assert user.is_active is True
        assert user.is_superuser is False


# =============================================================================
# Authenticate User
# =============================================================================


@pytest.mark.unit
class TestAuthenticateUser:
    def test_valid_credentials(self, auth_service):
        mock_db_user = MagicMock()
        mock_db_user.id = "user_abc"
        mock_db_user.email = "test@example.com"
        mock_db_user.full_name = "Test"
        mock_db_user.hashed_password = auth_service.hash_password("SecurePass1")
        mock_db_user.is_active = True
        mock_db_user.is_superuser = False
        mock_db_user.created_at = datetime(2024, 1, 1, tzinfo=UTC)
        mock_db_user.updated_at = datetime(2024, 1, 1, tzinfo=UTC)

        mock_db = MagicMock()
        mock_db.get_user_by_email.return_value = mock_db_user

        with patch("services.database_service.get_database_service", return_value=mock_db):
            result = auth_service.authenticate_user("test@example.com", "SecurePass1")

        assert result is not None
        assert result.email == "test@example.com"

    def test_wrong_password_returns_none(self, auth_service):
        mock_db_user = MagicMock()
        mock_db_user.hashed_password = auth_service.hash_password("SecurePass1")

        mock_db = MagicMock()
        mock_db.get_user_by_email.return_value = mock_db_user

        with patch("services.database_service.get_database_service", return_value=mock_db):
            result = auth_service.authenticate_user("test@example.com", "WrongPass1")

        assert result is None

    def test_nonexistent_email_returns_none(self, auth_service):
        mock_db = MagicMock()
        mock_db.get_user_by_email.return_value = None

        with patch("services.database_service.get_database_service", return_value=mock_db):
            result = auth_service.authenticate_user("nobody@example.com", "SecurePass1")

        assert result is None

    def test_db_error_returns_none(self, auth_service):
        mock_db = MagicMock()
        mock_db.get_user_by_email.side_effect = ValueError("DB down")

        with patch("services.database_service.get_database_service", return_value=mock_db):
            result = auth_service.authenticate_user("test@example.com", "SecurePass1")

        assert result is None


# =============================================================================
# Login
# =============================================================================


@pytest.mark.unit
class TestLogin:
    def test_success_returns_access_token(self, auth_service):
        mock_db_user = MagicMock()
        mock_db_user.id = "user_abc"
        mock_db_user.email = "test@example.com"
        mock_db_user.full_name = "Test"
        mock_db_user.hashed_password = auth_service.hash_password("SecurePass1")
        mock_db_user.is_active = True
        mock_db_user.is_superuser = False
        mock_db_user.created_at = datetime(2024, 1, 1, tzinfo=UTC)
        mock_db_user.updated_at = datetime(2024, 1, 1, tzinfo=UTC)

        mock_db = MagicMock()
        mock_db.get_user_by_email.return_value = mock_db_user

        with patch("services.database_service.get_database_service", return_value=mock_db):
            result = auth_service.login("test@example.com", "SecurePass1")

        assert "access_token" in result
        assert "error" not in result

    def test_invalid_credentials_returns_error(self, auth_service):
        mock_db = MagicMock()
        mock_db.get_user_by_email.return_value = None

        with (
            patch("services.database_service.get_database_service", return_value=mock_db),
            patch.object(
                type(auth_service),
                "login",
                wraps=auth_service.login,
            ),
            patch("services.auth_service.settings") as mock_settings,
        ):
            # In non-dev mode, should return error
            mock_settings.app.environment = "production"
            result = auth_service.login("test@example.com", "WrongPass1")

        assert "error" in result

    def test_dev_mode_auto_login(self, auth_service):
        mock_db = MagicMock()
        mock_db.get_user_by_email.return_value = None
        mock_created = MagicMock()
        mock_created.id = "test@dev.com"
        mock_db.create_user.return_value = mock_created

        with (
            patch("services.database_service.get_database_service", return_value=mock_db),
            patch("services.auth_service.settings") as mock_settings,
        ):
            mock_settings.app.environment = "development"
            result = auth_service.login("test@dev.com", "anypassword123")

        assert "access_token" in result

    def test_production_rejects_auto_login(self, auth_service):
        mock_db = MagicMock()
        mock_db.get_user_by_email.return_value = None

        with (
            patch("services.database_service.get_database_service", return_value=mock_db),
            patch("services.auth_service.settings") as mock_settings,
        ):
            mock_settings.app.environment = "production"
            result = auth_service.login("test@dev.com", "anypassword123")

        assert "error" in result


# =============================================================================
# Register
# =============================================================================


@pytest.mark.unit
class TestRegister:
    def test_success_returns_access_token(self, auth_service):
        mock_user = MagicMock()
        mock_user.id = "user_new"
        mock_user.email = "new@example.com"

        mock_db = MagicMock()
        mock_db.get_user_by_email.return_value = None
        mock_db.create_user.return_value = mock_user

        with patch("services.database_service.get_database_service", return_value=mock_db):
            result = auth_service.register("new@example.com", "SecurePass1", "New User")

        assert "access_token" in result

    def test_duplicate_email_returns_error(self, auth_service):
        mock_db = MagicMock()
        mock_db.get_user_by_email.return_value = MagicMock()  # exists

        with patch("services.database_service.get_database_service", return_value=mock_db):
            result = auth_service.register("existing@example.com", "SecurePass1", "Existing")

        assert result == {"error": "Email already registered"}

    def test_invalid_email_returns_error(self, auth_service):
        result = auth_service.register("notanemail", "SecurePass1", "Test")
        assert result == {"error": "Invalid email format"}

    def test_short_password_returns_error(self, auth_service):
        result = auth_service.register("new@example.com", "short", "Test")
        assert result == {"error": "Password must be at least 8 characters"}

    def test_short_name_returns_error(self, auth_service):
        result = auth_service.register("new@example.com", "SecurePass1", "A")
        assert result == {"error": "Name must be at least 2 characters"}

    def test_db_error_returns_error(self, auth_service):
        mock_db = MagicMock()
        mock_db.get_user_by_email.side_effect = Exception("DB down")

        with patch("services.database_service.get_database_service", return_value=mock_db):
            result = auth_service.register("new@example.com", "SecurePass1", "Test")

        assert "error" in result
