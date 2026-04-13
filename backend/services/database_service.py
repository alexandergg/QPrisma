"""
Database Service for QPrisma

Provides PostgreSQL connection management and CRUD operations.
Replaces Cosmos DB for metadata storage.
"""

import logging
import os
from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError, ProgrammingError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from core.config import settings
from models.database import (
    A2ATaskModel,
    Base,
    BatchJobModel,
    JobModel,
    MediaModel,
    ToolArtifactModel,
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
        self.database_url = database_url or settings.postgres.database_url

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
            self._run_migrations()
            self._initialized = True
            logger.info("PostgreSQL database initialized successfully")
            return True
        except SQLAlchemyError as e:
            logger.error(f"Failed to initialize database: {e}")
            return False

    def _run_migrations(self) -> None:
        """Run lightweight schema migrations for columns added after initial table creation.

        Uses SQLAlchemy inspect to check for missing columns, then adds them.
        Works with both PostgreSQL and SQLite (for tests).
        """
        from sqlalchemy import inspect as sa_inspect

        migrations: list[tuple[str, str, str]] = [
            # (table_name, column_name, column_type_sql)
            ("media", "upload_session", "JSON"),
        ]
        with self.engine.begin() as conn:
            inspector = sa_inspect(conn)
            applied = 0
            for table, column, col_type in migrations:
                existing = {c["name"] for c in inspector.get_columns(table)}
                if column not in existing:
                    try:
                        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}"))
                        applied += 1
                    except (OperationalError, ProgrammingError) as e:
                        # Column may already exist due to concurrent replica startup
                        logger.info(
                            "Column %s.%s already exists (concurrent migration): %s",
                            table,
                            column,
                            e,
                        )
            logger.info(
                "Schema migrations checked (%d applied, %d total)", applied, len(migrations)
            )

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
        full_name: str | None = None,
        user_id: str | None = None,
        entra_oid: str | None = None,
    ) -> UserModel:
        """Create a new user."""
        with self.get_session() as session:
            user = UserModel(
                id=user_id or f"user_{os.urandom(6).hex()}",
                email=email,
                full_name=full_name,
                entra_oid=entra_oid,
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

    def get_user_by_entra_oid(self, entra_oid: str) -> UserModel | None:
        """Get user by Microsoft Entra ID Object ID."""
        with self.get_session() as session:
            user = session.query(UserModel).filter(UserModel.entra_oid == entra_oid).first()
            if user:
                session.expunge(user)
            return user

    def update_user_entra_oid(self, user_id: str, entra_oid: str) -> UserModel | None:
        """Link an existing user to a Microsoft Entra ID Object ID."""
        with self.get_session() as session:
            user = session.query(UserModel).filter(UserModel.id == user_id).first()
            if user:
                user.entra_oid = entra_oid
                session.flush()
                session.refresh(user)
                session.expunge(user)
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

    def get_user_media_ids(
        self,
        user_id: str,
        *,
        processed_only: bool = False,
        batch_size: int = 500,
    ) -> list[str]:
        """Return media IDs for a user, optionally restricted to processed items."""
        media_ids: list[str] = []
        offset = 0

        while True:
            media_batch = self.get_media_by_user(user_id, limit=batch_size, offset=offset)
            if not media_batch:
                break

            media_ids.extend(
                media.id
                for media in media_batch
                if not processed_only or getattr(media, "processed", False)
            )

            if len(media_batch) < batch_size:
                break
            offset += batch_size

        return media_ids

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
        """Delete media record and all associated data."""
        with self.get_session() as session:
            media = session.query(MediaModel).filter(MediaModel.id == media_id).first()
            if not media:
                return False

            # Delete related records that have FK references to media
            session.query(ToolArtifactModel).filter(ToolArtifactModel.media_id == media_id).delete()
            session.query(BatchJobModel).filter(BatchJobModel.media_id == media_id).delete()
            session.query(JobModel).filter(JobModel.media_id == media_id).delete()

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

    # =========================================================================
    # A2A Task Persistence Operations
    # =========================================================================

    def upsert_a2a_task(self, task_data: dict[str, Any]) -> A2ATaskModel:
        """Insert or update a persisted A2A task."""
        with self.get_session() as session:
            task = session.query(A2ATaskModel).filter(A2ATaskModel.id == task_data["id"]).first()

            if task is None:
                task = A2ATaskModel(**task_data)
                session.add(task)
            else:
                task.context_id = task_data.get("context_id", task.context_id)
                task.status_state = task_data.get("status_state", task.status_state)
                task.status_timestamp = task_data.get("status_timestamp", task.status_timestamp)
                task.status_payload = task_data.get("status_payload", task.status_payload)
                task.artifacts = task_data.get("artifacts")
                task.history = task_data.get("history")
                task.task_metadata = task_data.get("task_metadata")

            session.flush()
            session.refresh(task)
            session.expunge(task)
            return task

    def get_a2a_task(self, task_id: str) -> A2ATaskModel | None:
        """Get a persisted A2A task by ID."""
        with self.get_session() as session:
            task = session.query(A2ATaskModel).filter(A2ATaskModel.id == task_id).first()
            if task:
                session.expunge(task)
            return task

    def list_a2a_tasks(
        self,
        context_id: str | None = None,
        status_state: str | None = None,
        page_size: int = 50,
    ) -> tuple[list[A2ATaskModel], int]:
        """List persisted A2A tasks with optional filtering."""
        with self.get_session() as session:
            query = session.query(A2ATaskModel)

            if context_id:
                query = query.filter(A2ATaskModel.context_id == context_id)

            if status_state:
                query = query.filter(A2ATaskModel.status_state == status_state)

            total = query.count()

            rows = (
                query.order_by(A2ATaskModel.status_timestamp.desc(), A2ATaskModel.created_at.desc())
                .limit(page_size)
                .all()
            )

            for row in rows:
                session.expunge(row)

            return rows, total

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
    # Tool Artifact Operations
    # =========================================================================

    def create_tool_artifact(self, artifact_data: dict[str, Any]) -> ToolArtifactModel:
        """Create a new tool artifact metadata record."""
        with self.get_session() as session:
            artifact = ToolArtifactModel(**artifact_data)
            session.add(artifact)
            session.flush()
            session.refresh(artifact)
            session.expunge(artifact)
            return artifact

    def get_tool_artifact(self, artifact_id: str) -> ToolArtifactModel | None:
        """Get tool artifact metadata by ID."""
        with self.get_session() as session:
            artifact = (
                session.query(ToolArtifactModel).filter(ToolArtifactModel.id == artifact_id).first()
            )
            if artifact:
                session.expunge(artifact)
            return artifact

    def update_tool_artifact_accessed_at(self, artifact_id: str) -> ToolArtifactModel | None:
        """Update last accessed timestamp for a tool artifact."""
        with self.get_session() as session:
            artifact = (
                session.query(ToolArtifactModel).filter(ToolArtifactModel.id == artifact_id).first()
            )
            if not artifact:
                return None

            artifact.last_accessed_at = datetime.now(UTC)
            session.flush()
            session.refresh(artifact)
            session.expunge(artifact)
            return artifact


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
