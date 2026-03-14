"""
Authentication service for JWT token management and user authentication.
Uses PostgreSQL for user storage (replaces Cosmos DB).
"""

import logging
import uuid
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi import HTTPException, status
from jose import JWTError, jwt
from passlib.context import CryptContext

from core.config import settings
from models.user import TokenData, UserCreate, UserInDB

# Redis async client for token revocation
try:
    import redis.asyncio as aioredis

    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    aioredis = None

logger = logging.getLogger(__name__)


class AuthService:
    """Service for handling authentication operations."""

    def __init__(self):
        """Initialize authentication service with configuration from centralized settings."""
        self.secret_key = settings.auth.jwt_secret_key
        self.algorithm = settings.auth.jwt_algorithm
        self.access_token_expire_minutes = settings.auth.jwt_access_token_expire_minutes
        self.refresh_token_expire_days = settings.auth.jwt_refresh_token_expire_days

        # Password hashing context
        self.pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

        # Redis client for token revocation (lazy init)
        self._redis: aioredis.Redis | None = None

        if settings.app.allow_dev_autologin:
            logger.warning(
                "Dev auto-login is ENABLED (ALLOW_DEV_AUTOLOGIN=True). "
                "Do NOT use this setting in production!"
            )

    def hash_password(self, password: str) -> str:
        """
        Hash a plain password using bcrypt.

        Args:
            password: Plain text password

        Returns:
            Hashed password string
        """
        return self.pwd_context.hash(password)

    def verify_password(self, plain_password: str, hashed_password: str) -> bool:
        """
        Verify a plain password against its hash.

        Args:
            plain_password: Plain text password to verify
            hashed_password: Hashed password to compare against

        Returns:
            True if password matches, False otherwise
        """
        return self.pwd_context.verify(plain_password, hashed_password)

    def create_access_token(self, data: dict, expires_delta: timedelta | None = None) -> str:
        """
        Create a JWT access token.

        Args:
            data: Dictionary of data to encode in the token
            expires_delta: Optional custom expiration time

        Returns:
            Encoded JWT token string
        """
        to_encode = data.copy()

        if expires_delta:
            expire = datetime.now(UTC) + expires_delta
        else:
            expire = datetime.now(UTC) + timedelta(minutes=self.access_token_expire_minutes)

        to_encode.update(
            {"exp": expire, "iat": datetime.now(UTC), "type": "access", "jti": str(uuid4())}
        )

        encoded_jwt = jwt.encode(to_encode, self.secret_key, algorithm=self.algorithm)
        return encoded_jwt

    def create_refresh_token(self, data: dict) -> str:
        """
        Create a JWT refresh token with longer expiration.

        Args:
            data: Dictionary of data to encode in the token

        Returns:
            Encoded JWT refresh token string
        """
        to_encode = data.copy()
        expire = datetime.now(UTC) + timedelta(days=self.refresh_token_expire_days)

        to_encode.update(
            {"exp": expire, "iat": datetime.now(UTC), "type": "refresh", "jti": str(uuid4())}
        )

        encoded_jwt = jwt.encode(to_encode, self.secret_key, algorithm=self.algorithm)
        return encoded_jwt

    async def _get_redis(self):
        """Get or create Redis client for token revocation (lazy init)."""
        if not REDIS_AVAILABLE:
            return None
        if self._redis is None:
            try:
                self._redis = aioredis.from_url(
                    settings.redis.url,
                    encoding="utf-8",
                    decode_responses=True,
                )
            except Exception as e:
                logger.warning(f"Failed to create Redis client for token revocation: {e}")
                return None
        return self._redis

    async def revoke_token(self, token: str) -> bool:
        """
        Revoke a JWT by storing its JTI in Redis with TTL matching token expiry.

        Args:
            token: JWT token string to revoke

        Returns:
            True if token was successfully revoked, False otherwise
        """
        try:
            # Decode without verifying expiry — user might logout with near-expired token
            payload = jwt.decode(
                token,
                self.secret_key,
                algorithms=[self.algorithm],
                options={"verify_exp": False},
            )

            jti = payload.get("jti")
            if not jti:
                logger.warning("Token has no JTI claim, cannot revoke")
                return False

            exp = payload.get("exp")
            if not exp:
                logger.warning("Token has no EXP claim, cannot determine TTL")
                return False

            # Calculate TTL: time until token expires
            now = datetime.now(UTC).timestamp()
            ttl = int(exp - now)

            if ttl <= 0:
                # Token already expired, no need to revoke
                logger.debug("Token already expired, skipping revocation")
                return True

            redis_client = await self._get_redis()
            if redis_client is None:
                logger.warning("Redis unavailable, token revocation skipped")
                return False

            await redis_client.set(f"revoked:{jti}", "1", ex=ttl)
            logger.info(f"Token revoked: jti={jti}, ttl={ttl}s")
            return True

        except JWTError as e:
            logger.error(f"Failed to decode token for revocation: {e}")
            return False
        except Exception as e:
            logger.warning(f"Token revocation failed: {e}")
            return False

    async def is_token_revoked(self, jti: str) -> bool:
        """
        Check if a token has been revoked.

        Args:
            jti: JWT ID to check

        Returns:
            True if token is revoked, False otherwise (fails open if Redis unavailable)
        """
        try:
            redis_client = await self._get_redis()
            if redis_client is None:
                return False  # Fail open if Redis unavailable

            result = await redis_client.exists(f"revoked:{jti}")
            return bool(result)
        except Exception as e:
            logger.warning(f"Token revocation check failed: {e}")
            return False  # Fail open

    async def verify_token(self, token: str, token_type: str = "access") -> TokenData:
        """
        Verify and decode a JWT token.

        Args:
            token: JWT token string to verify
            token_type: Expected token type ("access" or "refresh")

        Returns:
            TokenData containing decoded user information

        Raises:
            HTTPException: If token is invalid, expired, or wrong type
        """
        credentials_exception = HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

        try:
            payload = jwt.decode(token, self.secret_key, algorithms=[self.algorithm])

            # Verify token type
            if payload.get("type") != token_type:
                raise credentials_exception

            user_id: str = payload.get("sub")
            email: str = payload.get("email")

            if user_id is None:
                raise credentials_exception

            # Check if token has been revoked (backward compatible — tokens without JTI still work)
            jti = payload.get("jti")
            if jti and await self.is_token_revoked(jti):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Token has been revoked",
                    headers={"WWW-Authenticate": "Bearer"},
                )

            return TokenData(user_id=user_id, email=email)

        except HTTPException:
            raise
        except JWTError:
            raise credentials_exception from None

    def create_user(self, user_data: UserCreate) -> UserInDB:
        """
        Create a new user with hashed password.

        Args:
            user_data: User creation data

        Returns:
            UserInDB model with hashed password
        """
        import uuid

        hashed_password = self.hash_password(user_data.password)

        user = UserInDB(
            id=f"user_{uuid.uuid4().hex[:12]}",
            email=user_data.email,
            full_name=user_data.full_name,
            hashed_password=hashed_password,
            is_active=True,
            is_superuser=False,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

        return user

    def authenticate_user(self, email: str, password: str) -> UserInDB | None:
        """
        Authenticate a user by email and password using PostgreSQL.

        Args:
            email: User's email address
            password: Plain text password

        Returns:
            UserInDB if authentication successful, None otherwise
        """
        from services.database_service import get_database_service

        try:
            db = get_database_service()
            user = db.get_user_by_email(email)

            if not user:
                return None

            # Verify password
            if not self.verify_password(password, user.hashed_password):
                return None

            return UserInDB(
                id=user.id,
                email=user.email,
                full_name=user.full_name,
                hashed_password=user.hashed_password,
                is_active=user.is_active,
                is_superuser=user.is_superuser,
                created_at=user.created_at,
                updated_at=user.updated_at,
            )

        except (ValueError, AttributeError) as e:
            logger.error(f"Error authenticating user {email}: {e}")
            return None

    def get_token_expiry_seconds(self) -> int:
        """
        Get access token expiry time in seconds.

        Returns:
            Token expiry time in seconds
        """
        return self.access_token_expire_minutes * 60

    def login(self, email: str, password: str) -> dict:
        """
        Login and create a token.

        In production, validates against PostgreSQL.
        In development mode without DB, accepts demo logins.

        Args:
            email: User email
            password: User password

        Returns:
            Dict with access_token or error
        """
        # Try to authenticate against database
        user = self.authenticate_user(email, password)
        if user:
            token = self.create_access_token({"sub": user.id, "email": user.email})
            return {"access_token": token}

        # Dev auto-login: only when explicitly enabled via config flag
        if not settings.app.allow_dev_autologin:
            return {"error": "Invalid email or password"}

        if "@" not in email or len(password) < 6:
            return {"error": "Invalid email or password"}

        logger.warning(f"Dev-mode auto-login for {email}")

        # Auto-create demo user in database to satisfy FK constraints
        from services.database_service import get_database_service

        try:
            db = get_database_service()
            demo_user_id = str(uuid.uuid4())

            # Check if demo user already exists
            existing = db.get_user_by_email(email)
            if not existing:
                # Create demo user in database
                hashed_password = self.hash_password(password)
                user = db.create_user(
                    email=email,
                    hashed_password=hashed_password,
                    full_name=f"Demo User ({email.split('@')[0]})",
                    user_id=demo_user_id,
                )
                logger.info(f"Created demo user: {email}")
                demo_user_id = user.id
            else:
                demo_user_id = existing.id

            token = self.create_access_token({"sub": demo_user_id, "email": email})
            return {"access_token": token}
        except Exception as e:
            logger.error(f"Login failed: {e}")
            return {"error": "Login failed. Please try again."}

    def register(self, email: str, password: str, name: str) -> dict:
        """
        Register a new user in PostgreSQL.

        Args:
            email: User email
            password: User password
            name: User's display name

        Returns:
            Dict with access_token or error
        """
        from services.database_service import get_database_service

        # Validate input
        if "@" not in email:
            return {"error": "Invalid email format"}
        if len(password) < 8:
            return {"error": "Password must be at least 8 characters"}
        if len(name) < 2:
            return {"error": "Name must be at least 2 characters"}

        try:
            db = get_database_service()

            # Check if user exists
            existing = db.get_user_by_email(email)
            if existing:
                return {"error": "Email already registered"}

            # Create user
            hashed_password = self.hash_password(password)
            user = db.create_user(
                email=email,
                hashed_password=hashed_password,
                full_name=name,
            )

            token = self.create_access_token({"sub": user.id, "email": user.email})
            return {"access_token": token}

        except Exception as e:
            logger.error(f"Registration failed: {e}")
            return {"error": "Registration failed. Please try again."}


# Singleton instance
_auth_instance: AuthService | None = None


def get_auth_service() -> AuthService:
    """Get singleton instance of AuthService."""
    global _auth_instance
    if _auth_instance is None:
        _auth_instance = AuthService()
    return _auth_instance
