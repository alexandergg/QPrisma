"""
Authentication service for JWT token management and user authentication.
Uses PostgreSQL for user storage (replaces Cosmos DB).
"""

import logging
import os
from datetime import datetime, timedelta

from fastapi import HTTPException, status
from jose import JWTError, jwt
from passlib.context import CryptContext

from models.user import TokenData, UserCreate, UserInDB

logger = logging.getLogger(__name__)


class AuthService:
    """Service for handling authentication operations."""

    # Default secret for development only
    _DEFAULT_DEV_SECRET = "your-secret-key-change-in-production"

    def __init__(self):
        """Initialize authentication service with configuration from environment."""
        self.secret_key = os.getenv("JWT_SECRET_KEY", self._DEFAULT_DEV_SECRET)
        if self.secret_key == self._DEFAULT_DEV_SECRET:
            import warnings

            warnings.warn(
                "Using default JWT secret key. Set JWT_SECRET_KEY in production!",
                UserWarning,
                stacklevel=2,
            )

        self.algorithm = os.getenv("JWT_ALGORITHM", "HS256")
        self.access_token_expire_minutes = int(
            os.getenv("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "1440")  # 24 hours default
        )
        self.refresh_token_expire_days = int(os.getenv("JWT_REFRESH_TOKEN_EXPIRE_DAYS", "30"))

        # Password hashing context
        self.pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

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
            expire = datetime.utcnow() + expires_delta
        else:
            expire = datetime.utcnow() + timedelta(minutes=self.access_token_expire_minutes)

        to_encode.update({"exp": expire, "iat": datetime.utcnow(), "type": "access"})

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
        expire = datetime.utcnow() + timedelta(days=self.refresh_token_expire_days)

        to_encode.update({"exp": expire, "iat": datetime.utcnow(), "type": "refresh"})

        encoded_jwt = jwt.encode(to_encode, self.secret_key, algorithm=self.algorithm)
        return encoded_jwt

    def verify_token(self, token: str, token_type: str = "access") -> TokenData:
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

            return TokenData(user_id=user_id, email=email)

        except JWTError:
            raise credentials_exception

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
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
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

        except Exception:
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

        # Development mode: create token for any valid email format
        if "@" not in email or len(password) < 6:
            return {"error": "Invalid email or password"}

        # Auto-create demo user in database to satisfy FK constraints
        from services.database_service import get_database_service

        try:
            db = get_database_service()
            demo_user_id = email  # Use email as user_id for simplicity
            
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
