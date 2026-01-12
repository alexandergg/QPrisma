"""
Database Service for QPrisma

Provides PostgreSQL connection management and CRUD operations.
Replaces Cosmos DB for metadata storage.
"""

import logging
import os
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Generator

from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from models.database import Base, BatchJobModel, JobModel, MediaModel, UserModel

logger = logging.getLogger(__name__)


class DatabaseService:
    """
    PostgreSQL database service for QPrisma.

    Handles connection pooling, session management, and CRUD operations
    for users, media metadata, and jobs.
    """

    def __init__(self, database_url: str | None = None):
        """
        Initialize database service.

        Args:
            database_url: PostgreSQL connection URL. If not provided,
                         reads from DATABASE_URL environment variable.
        """
        self.database_url = database_url or os.getenv(
            "DATABASE_URL", "postgresql://qprisma:qprisma123@localhost:5432/qprisma"
        )

        # Create engine with connection pooling
        self.engine = create_engine(
            self.database_url,
            pool_size=10,
            max_overflow=20,
            pool_pre_ping=True,  # Check connections before use
            pool_recycle=3600,  # Recycle connections after 1 hour
        )

        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        self._initialized = False

    def initialize(self) -> bool:
        """
        Initialize database schema (create tables if not exist).

        Returns:
            True if successful, False otherwise.
        """
        try:
            Base.metadata.create_all(bind=self.engine)
            self._initialized = True
            logger.info("PostgreSQL database initialized successfully")
            return True
        except SQLAlchemyError as e:
            logger.error(f"Failed to initialize database: {e}")
            return False

    def health_check(self) -> dict[str, Any]:
        """Check database connectivity."""
        try:
            with self.engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return {"status": "healthy", "database": "postgresql"}
        except SQLAlchemyError as e:
            return {"status": "unhealthy", "error": str(e)}

    @contextmanager
    def get_session(self) -> Generator[Session, None, None]:
        """Get a database session with automatic cleanup."""
        session = self.SessionLocal()
        try:
            yield session
            session.commit()
        except SQLAlchemyError as e:
            session.rollback()
            logger.error(f"Database error: {e}")
            raise
        finally:
            session.close()

    # =========================================================================
    # User Operations
    # =========================================================================

    def create_user(
        self,
        email: str,
        hashed_password: str,
        full_name: str | None = None,
        user_id: str | None = None,
    ) -> UserModel:
        """Create a new user."""
        with self.get_session() as session:
            user = UserModel(
                id=user_id or f"user_{os.urandom(6).hex()}",
                email=email,
                full_name=full_name,
                hashed_password=hashed_password,
            )
            session.add(user)
            session.flush()
            session.refresh(user)
            session.expunge(user)
            return user

    def get_user_by_email(self, email: str) -> UserModel | None:
        """Get user by email."""
        with self.get_session() as session:
            user = session.query(UserModel).filter(UserModel.email == email).first()
            if user:
                session.expunge(user)  # Detach from session to use after close
            return user

    def get_user_by_id(self, user_id: str) -> UserModel | None:
        """Get user by ID."""
        with self.get_session() as session:
            user = session.query(UserModel).filter(UserModel.id == user_id).first()
            if user:
                session.expunge(user)  # Detach from session to use after close
            return user

    # =========================================================================
    # Media Operations
    # =========================================================================

    def create_media(self, media_data: dict[str, Any]) -> MediaModel:
        """Create a new media record."""
        with self.get_session() as session:
            media = MediaModel(**media_data)
            session.add(media)
            session.flush()
            session.refresh(media)
            session.expunge(media)  # Detach from session
            return media

    def get_media(self, media_id: str) -> MediaModel | None:
        """Get media by ID."""
        with self.get_session() as session:
            media = session.query(MediaModel).filter(MediaModel.id == media_id).first()
            if media:
                session.expunge(media)
            return media

    def get_media_by_user(
        self, user_id: str, limit: int = 100, offset: int = 0
    ) -> list[MediaModel]:
        """Get all media for a user."""
        with self.get_session() as session:
            media_list = (
                session.query(MediaModel)
                .filter(MediaModel.user_id == user_id)
                .order_by(MediaModel.upload_date.desc())
                .limit(limit)
                .offset(offset)
                .all()
            )
            for media in media_list:
                session.expunge(media)
            return media_list

    def update_media(self, media_id: str, updates: dict[str, Any]) -> MediaModel | None:
        """Update media record."""
        with self.get_session() as session:
            media = session.query(MediaModel).filter(MediaModel.id == media_id).first()
            if not media:
                return None

            for key, value in updates.items():
                if hasattr(media, key):
                    setattr(media, key, value)

            media.last_updated = datetime.utcnow()
            session.flush()
            session.refresh(media)
            session.expunge(media)
            return media

    def delete_media(self, media_id: str) -> bool:
        """Delete media record."""
        with self.get_session() as session:
            media = session.query(MediaModel).filter(MediaModel.id == media_id).first()
            if not media:
                return False

            session.delete(media)
            return True

    def get_media_status(self, media_id: str) -> dict[str, Any] | None:
        """Get processing status for media."""
        with self.get_session() as session:
            media = session.query(MediaModel).filter(MediaModel.id == media_id).first()
            if not media:
                return None

            return {
                "media_id": media.id,
                "processing_status": media.processing_status,
                "processing_message": media.processing_message,
                "processing_progress": media.processing_progress,
                "processed": media.processed,
                "processing_method": media.processing_method,
                "frames_analyzed": (media.processing_result or {}).get("frames_analyzed", 0),
                "last_updated": media.last_updated.isoformat() if media.last_updated else None,
                "video_metadata": media.video_metadata,
            }

    # =========================================================================
    # Job Operations
    # =========================================================================

    def create_job(self, job_data: dict[str, Any]) -> JobModel:
        """Create a new job record."""
        with self.get_session() as session:
            job = JobModel(**job_data)
            session.add(job)
            session.flush()
            session.refresh(job)
            session.expunge(job)
            return job

    def get_job(self, job_id: str) -> JobModel | None:
        """Get job by ID."""
        with self.get_session() as session:
            job = session.query(JobModel).filter(JobModel.id == job_id).first()
            if job:
                session.expunge(job)
            return job

    def update_job(self, job_id: str, updates: dict[str, Any]) -> JobModel | None:
        """Update job record."""
        with self.get_session() as session:
            job = session.query(JobModel).filter(JobModel.id == job_id).first()
            if not job:
                return None

            for key, value in updates.items():
                if hasattr(job, key):
                    setattr(job, key, value)

            session.flush()
            session.refresh(job)
            session.expunge(job)
            return job

    # =========================================================================
    # Batch Job Operations (Azure OpenAI Batch API)
    # =========================================================================

    def create_batch_job(self, batch_data: dict[str, Any]) -> BatchJobModel:
        """Create a new batch job record for tracking Azure OpenAI batch operations."""
        with self.get_session() as session:
            batch_job = BatchJobModel(**batch_data)
            session.add(batch_job)
            session.flush()
            session.refresh(batch_job)
            session.expunge(batch_job)
            return batch_job

    def get_batch_job(self, batch_id: str) -> BatchJobModel | None:
        """Get batch job by internal ID."""
        with self.get_session() as session:
            batch_job = session.query(BatchJobModel).filter(BatchJobModel.id == batch_id).first()
            if batch_job:
                session.expunge(batch_job)
            return batch_job

    def get_batch_job_by_azure_id(self, azure_batch_id: str) -> BatchJobModel | None:
        """Get batch job by Azure batch ID."""
        with self.get_session() as session:
            batch_job = (
                session.query(BatchJobModel)
                .filter(BatchJobModel.azure_batch_id == azure_batch_id)
                .first()
            )
            if batch_job:
                session.expunge(batch_job)
            return batch_job

    def get_batch_jobs_by_media(self, media_id: str) -> list[BatchJobModel]:
        """Get all batch jobs for a media item."""
        with self.get_session() as session:
            jobs = (
                session.query(BatchJobModel)
                .filter(BatchJobModel.media_id == media_id)
                .order_by(BatchJobModel.created_at.desc())
                .all()
            )
            for job in jobs:
                session.expunge(job)
            return jobs

    def get_batch_jobs_by_user(
        self, user_id: str, status: str | None = None, limit: int = 50
    ) -> list[BatchJobModel]:
        """Get batch jobs for a user, optionally filtered by status."""
        with self.get_session() as session:
            query = session.query(BatchJobModel).filter(BatchJobModel.user_id == user_id)
            if status:
                query = query.filter(BatchJobModel.status == status)
            jobs = query.order_by(BatchJobModel.created_at.desc()).limit(limit).all()
            for job in jobs:
                session.expunge(job)
            return jobs

    def get_pending_batch_jobs(self, limit: int = 100) -> list[BatchJobModel]:
        """Get all pending/in-progress batch jobs for polling."""
        with self.get_session() as session:
            jobs = (
                session.query(BatchJobModel)
                .filter(BatchJobModel.status.in_(["validating", "in_progress", "finalizing"]))
                .order_by(BatchJobModel.created_at.asc())
                .limit(limit)
                .all()
            )
            for job in jobs:
                session.expunge(job)
            return jobs

    def update_batch_job(self, batch_id: str, updates: dict[str, Any]) -> BatchJobModel | None:
        """Update batch job record."""
        with self.get_session() as session:
            batch_job = session.query(BatchJobModel).filter(BatchJobModel.id == batch_id).first()
            if not batch_job:
                return None

            for key, value in updates.items():
                if hasattr(batch_job, key):
                    setattr(batch_job, key, value)

            session.flush()
            session.refresh(batch_job)
            session.expunge(batch_job)
            return batch_job

    def update_batch_job_by_azure_id(
        self, azure_batch_id: str, updates: dict[str, Any]
    ) -> BatchJobModel | None:
        """Update batch job record by Azure batch ID."""
        with self.get_session() as session:
            batch_job = (
                session.query(BatchJobModel)
                .filter(BatchJobModel.azure_batch_id == azure_batch_id)
                .first()
            )
            if not batch_job:
                return None

            for key, value in updates.items():
                if hasattr(batch_job, key):
                    setattr(batch_job, key, value)

            session.flush()
            session.refresh(batch_job)
            session.expunge(batch_job)
            return batch_job

    def get_batch_cost_summary(self, user_id: str | None = None) -> dict[str, Any]:
        """Get cost summary for batch jobs."""
        with self.get_session() as session:
            query = session.query(BatchJobModel).filter(BatchJobModel.status == "completed")
            if user_id:
                query = query.filter(BatchJobModel.user_id == user_id)

            jobs = query.all()

            total_estimated = sum(j.estimated_cost or 0 for j in jobs)
            total_actual = sum(j.actual_cost or 0 for j in jobs)
            total_tokens = sum(j.tokens_used or 0 for j in jobs)
            total_requests = sum(j.completed_requests or 0 for j in jobs)

            # Batch API is 50% cheaper, so savings = estimated regular cost - batch cost
            estimated_regular_cost = total_actual * 2  # Regular API would be 2x
            savings = estimated_regular_cost - total_actual

            return {
                "total_batch_jobs": len(jobs),
                "total_requests_processed": total_requests,
                "total_tokens_used": total_tokens,
                "total_estimated_cost": round(total_estimated, 4),
                "total_actual_cost": round(total_actual, 4),
                "estimated_savings_usd": round(savings, 4),
                "savings_percentage": 50.0,  # Batch API is always 50% cheaper
            }


# =============================================================================
# Singleton Instance
# =============================================================================

_db_service: DatabaseService | None = None


def get_database_service() -> DatabaseService:
    """Get or create database service singleton."""
    global _db_service
    if _db_service is None:
        _db_service = DatabaseService()
        _db_service.initialize()
    return _db_service


def get_db_session() -> Generator[Session, None, None]:
    """FastAPI dependency for database session."""
    db = get_database_service()
    session = db.SessionLocal()
    try:
        yield session
        session.commit()
    except SQLAlchemyError:
        session.rollback()
        raise
    finally:
        session.close()
