"""
Database Service for QPrisma

Provides PostgreSQL connection management and CRUD operations.
Replaces Cosmos DB for metadata storage.
"""

import logging
import os
from collections.abc import Generator
from contextlib import contextmanager
from datetime import datetime, UTC
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from models.database import (
    Base,
    BatchJobModel,
    ClipModel,
    EditorProjectModel,
    JobModel,
    MediaModel,
    UserModel,
)

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

            media.last_updated = datetime.now(UTC)
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

    # =========================================================================
    # Editor Project Operations
    # =========================================================================

    def create_project(self, project_data: dict[str, Any]) -> EditorProjectModel:
        """Create a new editor project."""
        with self.get_session() as session:
            project = EditorProjectModel(**project_data)
            session.add(project)
            session.flush()
            session.refresh(project)
            session.expunge(project)
            return project

    def get_project(self, project_id: str) -> EditorProjectModel | None:
        """Get project by ID."""
        with self.get_session() as session:
            project = (
                session.query(EditorProjectModel)
                .filter(EditorProjectModel.id == project_id)
                .first()
            )
            if project:
                session.expunge(project)
            return project

    def get_project_with_clips(self, project_id: str) -> EditorProjectModel | None:
        """Get project with all its clips and source media."""
        with self.get_session() as session:
            project = (
                session.query(EditorProjectModel)
                .filter(EditorProjectModel.id == project_id)
                .first()
            )
            if project:
                # Force load clips
                _ = project.clips
                for clip in project.clips:
                    session.expunge(clip)
                # Force load source_media for editor routes
                if project.source_media:
                    session.expunge(project.source_media)
                session.expunge(project)
            return project

    def get_projects_by_user(
        self, user_id: str, limit: int = 50, offset: int = 0
    ) -> list[EditorProjectModel]:
        """Get all projects for a user."""
        with self.get_session() as session:
            projects = (
                session.query(EditorProjectModel)
                .filter(EditorProjectModel.user_id == user_id)
                .order_by(EditorProjectModel.updated_at.desc())
                .limit(limit)
                .offset(offset)
                .all()
            )
            for project in projects:
                # Force load clips count
                _ = project.clips
                session.expunge(project)
            return projects

    def update_project(
        self, project_id: str, updates: dict[str, Any]
    ) -> EditorProjectModel | None:
        """Update project record."""
        with self.get_session() as session:
            project = (
                session.query(EditorProjectModel)
                .filter(EditorProjectModel.id == project_id)
                .first()
            )
            if not project:
                return None

            for key, value in updates.items():
                if hasattr(project, key):
                    setattr(project, key, value)

            project.updated_at = datetime.now(UTC)
            session.flush()
            session.refresh(project)
            session.expunge(project)
            return project

    def delete_project(self, project_id: str) -> bool:
        """Delete project and all its clips (cascade)."""
        with self.get_session() as session:
            project = (
                session.query(EditorProjectModel)
                .filter(EditorProjectModel.id == project_id)
                .first()
            )
            if not project:
                return False

            session.delete(project)
            return True

    # =========================================================================
    # Clip Operations
    # =========================================================================

    def create_clip(self, clip_data: dict[str, Any]) -> ClipModel:
        """Create a new clip in a project."""
        with self.get_session() as session:
            # If no order specified, add at the end
            if "order" not in clip_data or clip_data["order"] is None:
                max_order = (
                    session.query(ClipModel)
                    .filter(ClipModel.project_id == clip_data["project_id"])
                    .count()
                )
                clip_data["order"] = max_order

            clip = ClipModel(**clip_data)
            session.add(clip)
            session.flush()
            session.refresh(clip)
            session.expunge(clip)
            return clip

    def get_clip(self, clip_id: str) -> ClipModel | None:
        """Get clip by ID."""
        with self.get_session() as session:
            clip = session.query(ClipModel).filter(ClipModel.id == clip_id).first()
            if clip:
                session.expunge(clip)
            return clip

    def get_clips_by_project(self, project_id: str) -> list[ClipModel]:
        """Get all clips for a project, ordered by position."""
        with self.get_session() as session:
            clips = (
                session.query(ClipModel)
                .filter(ClipModel.project_id == project_id)
                .order_by(ClipModel.order.asc())
                .all()
            )
            for clip in clips:
                session.expunge(clip)
            return clips

    def update_clip(self, clip_id: str, updates: dict[str, Any]) -> ClipModel | None:
        """Update clip record."""
        with self.get_session() as session:
            clip = session.query(ClipModel).filter(ClipModel.id == clip_id).first()
            if not clip:
                return None

            for key, value in updates.items():
                if hasattr(clip, key):
                    setattr(clip, key, value)

            clip.updated_at = datetime.now(UTC)
            session.flush()
            session.refresh(clip)
            session.expunge(clip)
            return clip

    def delete_clip(self, clip_id: str) -> bool:
        """Delete a clip."""
        with self.get_session() as session:
            clip = session.query(ClipModel).filter(ClipModel.id == clip_id).first()
            if not clip:
                return False

            project_id = clip.project_id
            deleted_order = clip.order
            session.delete(clip)
            session.flush()

            # Reorder remaining clips
            remaining_clips = (
                session.query(ClipModel)
                .filter(ClipModel.project_id == project_id)
                .filter(ClipModel.order > deleted_order)
                .all()
            )
            for remaining_clip in remaining_clips:
                remaining_clip.order -= 1

            return True

    def reorder_clips(self, project_id: str, clip_ids: list[str]) -> list[ClipModel]:
        """Reorder clips in a project based on the provided ID list."""
        with self.get_session() as session:
            clips = (
                session.query(ClipModel)
                .filter(ClipModel.project_id == project_id)
                .all()
            )

            clip_map = {clip.id: clip for clip in clips}

            for new_order, clip_id in enumerate(clip_ids):
                if clip_id in clip_map:
                    clip_map[clip_id].order = new_order

            session.flush()

            # Return updated clips in new order
            updated_clips = (
                session.query(ClipModel)
                .filter(ClipModel.project_id == project_id)
                .order_by(ClipModel.order.asc())
                .all()
            )
            for clip in updated_clips:
                session.expunge(clip)
            return updated_clips

    def bulk_create_clips(
        self, project_id: str, clips_data: list[dict[str, Any]]
    ) -> list[ClipModel]:
        """Create multiple clips at once."""
        with self.get_session() as session:
            # Get current max order
            current_count = (
                session.query(ClipModel).filter(ClipModel.project_id == project_id).count()
            )

            created_clips = []
            for i, clip_data in enumerate(clips_data):
                clip_data["project_id"] = project_id
                if "order" not in clip_data or clip_data["order"] is None:
                    clip_data["order"] = current_count + i

                clip = ClipModel(**clip_data)
                session.add(clip)
                created_clips.append(clip)

            session.flush()

            for clip in created_clips:
                session.refresh(clip)
                session.expunge(clip)

            return created_clips


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
