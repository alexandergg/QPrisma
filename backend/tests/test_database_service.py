"""
Tests for services/database_service.py

Uses SQLite in-memory for fast, isolated tests of CRUD operations.
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from models.database import Base
from services.database_service import DatabaseService


@pytest.fixture
def db_service():
    """Create a DatabaseService with in-memory SQLite, bypassing pool kwargs."""
    service = object.__new__(DatabaseService)
    service.database_url = "sqlite://"
    service.engine = create_engine("sqlite://")
    service.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=service.engine)
    service._initialized = False
    Base.metadata.create_all(bind=service.engine)
    service._initialized = True
    return service


# =============================================================================
# Health & Init
# =============================================================================


@pytest.mark.unit
class TestDatabaseInit:
    def test_initialize(self, db_service):
        result = db_service.initialize()
        assert result is True
        assert db_service._initialized is True

    def test_migration_adds_missing_column(self):
        """Pre-create media table without upload_session, run initialize(), assert column added."""
        service = object.__new__(DatabaseService)
        service.database_url = "sqlite://"
        service.engine = create_engine("sqlite://")
        service.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=service.engine)
        service._initialized = False

        # Create a minimal media table WITHOUT the upload_session column
        with service.engine.begin() as conn:
            conn.execute(
                text(
                    "CREATE TABLE media ("
                    "id TEXT PRIMARY KEY, "
                    "user_id TEXT, "
                    "blob_name TEXT, "
                    "media_type TEXT"
                    ")"
                )
            )
            # Also create users table so create_all doesn't fail on FK
            conn.execute(text("CREATE TABLE users (id TEXT PRIMARY KEY, email TEXT)"))

        # Verify upload_session is missing before migration
        with service.engine.connect() as conn:
            cols = {c["name"] for c in sa_inspect(conn).get_columns("media")}
        assert "upload_session" not in cols

        # Run initialize which triggers _run_migrations
        result = service.initialize()
        assert result is True

        # Verify upload_session now exists
        with service.engine.connect() as conn:
            cols = {c["name"] for c in sa_inspect(conn).get_columns("media")}
        assert "upload_session" in cols

        with service.engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO media "
                    "(id, user_id, blob_name, media_type, benchmark_name, benchmark_video_id) "
                    "VALUES "
                    "('media_dup_1', 'user_media_test', 'video.mp4', 'video', 'video_mme', 'video_001')"
                )
            )

        with pytest.raises(IntegrityError), service.engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO media "
                    "(id, user_id, blob_name, media_type, benchmark_name, benchmark_video_id) "
                    "VALUES "
                    "('media_dup_2', 'user_media_test', 'video2.mp4', 'video', 'video_mme', 'video_001')"
                )
            )

    def test_health_check(self, db_service):
        result = db_service.health_check()
        assert result["status"] == "healthy"


@pytest.mark.unit
class TestA2ATaskPersistence:
    def test_list_a2a_tasks_filters_by_user_id(self, db_service):
        now = datetime(2024, 1, 1, tzinfo=UTC)
        db_service.upsert_a2a_task(
            {
                "id": "task-owned",
                "context_id": "ctx-1",
                "status_state": "TASK_STATE_COMPLETED",
                "status_timestamp": now,
                "status_payload": {"state": "TASK_STATE_COMPLETED"},
                "artifacts": [],
                "history": [],
                "task_metadata": {"user_id": "user_test123"},
            }
        )
        db_service.upsert_a2a_task(
            {
                "id": "task-other",
                "context_id": "ctx-1",
                "status_state": "TASK_STATE_COMPLETED",
                "status_timestamp": now,
                "status_payload": {"state": "TASK_STATE_COMPLETED"},
                "artifacts": [],
                "history": [],
                "task_metadata": {"user_id": "other-user"},
            }
        )

        rows, total = db_service.list_a2a_tasks(context_id="ctx-1", user_id="user_test123")

        assert total == 1
        assert [row.id for row in rows] == ["task-owned"]


# =============================================================================
# User CRUD
# =============================================================================


@pytest.mark.unit
class TestUserCRUD:
    def test_create_user(self, db_service):
        user = db_service.create_user(
            email="test@example.com",
            full_name="Test User",
        )
        assert user.email == "test@example.com"
        assert user.id is not None

    def test_get_user_by_email(self, db_service):
        db_service.create_user(
            email="lookup@example.com",
            full_name="Lookup",
        )
        user = db_service.get_user_by_email("lookup@example.com")
        assert user is not None
        assert user.email == "lookup@example.com"

    def test_get_user_by_email_not_found(self, db_service):
        user = db_service.get_user_by_email("nobody@example.com")
        assert user is None

    def test_create_user_with_custom_id(self, db_service):
        user = db_service.create_user(
            email="custom@example.com",
            full_name="Custom",
            user_id="user_custom123",
        )
        assert user.id == "user_custom123"

    def test_create_duplicate_email_raises(self, db_service):
        db_service.create_user(email="dup@example.com", full_name="First")
        with pytest.raises(IntegrityError):
            db_service.create_user(email="dup@example.com", full_name="Second")

    def test_create_user_with_entra_oid(self, db_service):
        user = db_service.create_user(
            email="entra@example.com",
            full_name="Entra User",
            entra_oid="00000000-0000-0000-0000-000000000001",
        )
        assert user.entra_oid == "00000000-0000-0000-0000-000000000001"

    def test_get_user_by_entra_oid(self, db_service):
        db_service.create_user(
            email="oid-lookup@example.com",
            full_name="OID User",
            entra_oid="oid-test-123",
        )
        user = db_service.get_user_by_entra_oid("oid-test-123")
        assert user is not None
        assert user.email == "oid-lookup@example.com"

    def test_update_user_entra_oid(self, db_service):
        user = db_service.create_user(
            email="link@example.com",
            full_name="Link User",
        )
        assert user.entra_oid is None
        updated = db_service.update_user_entra_oid(user.id, "new-oid-456")
        assert updated is not None
        assert updated.entra_oid == "new-oid-456"


# =============================================================================
# Media CRUD
# =============================================================================


@pytest.mark.unit
class TestMediaCRUD:
    @pytest.fixture(autouse=True)
    def _setup_user(self, db_service):
        """Create a user for FK constraints."""
        self.user = db_service.create_user(
            email="mediauser@example.com",
            full_name="Media User",
            user_id="user_media_test",
        )

    def test_create_media(self, db_service):
        media = db_service.create_media(
            {
                "id": "media_001",
                "user_id": "user_media_test",
                "blob_name": "video.mp4",
                "media_type": "video",
                "original_filename": "myvideo.mp4",
            }
        )
        assert media.id == "media_001"

    def test_get_media(self, db_service):
        db_service.create_media(
            {
                "id": "media_002",
                "user_id": "user_media_test",
                "blob_name": "vid2.mp4",
                "media_type": "video",
            }
        )
        media = db_service.get_media("media_002")
        assert media is not None
        assert media.blob_name == "vid2.mp4"

    def test_get_media_not_found(self, db_service):
        media = db_service.get_media("nonexistent")
        assert media is None

    def test_get_media_by_user(self, db_service):
        db_service.create_media(
            {
                "id": "media_003",
                "user_id": "user_media_test",
                "blob_name": "vid3.mp4",
                "media_type": "video",
            }
        )
        media_list = db_service.get_media_by_user("user_media_test")
        assert len(media_list) >= 1

    def test_get_media_by_user_empty(self, db_service):
        media_list = db_service.get_media_by_user("nonexistent_user")
        assert media_list == []

    def test_create_duplicate_benchmark_media_key_raises(self, db_service):
        media_data = {
            "user_id": "user_media_test",
            "blob_name": "benchmark.mp4",
            "media_type": "video",
            "benchmark_name": "video_mme",
            "benchmark_video_id": "video_001",
        }

        db_service.create_media({"id": "media_benchmark_1", **media_data})

        with pytest.raises(IntegrityError):
            db_service.create_media({"id": "media_benchmark_2", **media_data})

    def test_update_media(self, db_service):
        db_service.create_media(
            {
                "id": "media_004",
                "user_id": "user_media_test",
                "blob_name": "vid4.mp4",
                "media_type": "video",
            }
        )
        updated = db_service.update_media("media_004", {"processing_status": "completed"})
        assert updated.processing_status == "completed"

    def test_delete_media(self, db_service):
        db_service.create_media(
            {
                "id": "media_005",
                "user_id": "user_media_test",
                "blob_name": "vid5.mp4",
                "media_type": "video",
            }
        )
        db_service.delete_media("media_005")
        assert db_service.get_media("media_005") is None

    def test_pagination(self, db_service):
        for i in range(5):
            db_service.create_media(
                {
                    "id": f"media_page_{i}",
                    "user_id": "user_media_test",
                    "blob_name": f"v{i}.mp4",
                    "media_type": "video",
                }
            )
        page = db_service.get_media_by_user("user_media_test", limit=2, offset=0)
        assert len(page) == 2

    def test_get_user_media_ids_filters_processed_across_pages(self, db_service):
        for i, processed in enumerate([True, False, True]):
            db_service.create_media(
                {
                    "id": f"media_scope_{i}",
                    "user_id": "user_media_test",
                    "blob_name": f"scope_{i}.mp4",
                    "media_type": "video",
                    "processed": processed,
                }
            )

        media_ids = db_service.get_user_media_ids(
            "user_media_test",
            processed_only=True,
            batch_size=2,
        )

        assert set(media_ids) >= {"media_scope_0", "media_scope_2"}
        assert "media_scope_1" not in media_ids

    def test_create_and_update_upload_session(self, db_service):
        upload_session = {"upload_id": "test-123", "total_blocks": 5, "blocks": []}

        media = db_service.create_media(
            {
                "id": "media_upload_sess",
                "user_id": "user_media_test",
                "blob_name": "chunked.mp4",
                "media_type": "video",
                "upload_session": upload_session,
            }
        )
        assert media.id == "media_upload_sess"

        fetched = db_service.get_media("media_upload_sess")
        assert fetched is not None
        assert fetched.upload_session == upload_session

        updated = db_service.update_media("media_upload_sess", {"upload_session": None})
        assert updated.upload_session is None

        refetched = db_service.get_media("media_upload_sess")
        assert refetched.upload_session is None


# =============================================================================
# Job Operations
# =============================================================================


@pytest.mark.unit
class TestJobOperations:
    @pytest.fixture(autouse=True)
    def _setup_user_and_media(self, db_service):
        self.user = db_service.create_user(
            email="jobuser@example.com",
            full_name="Job User",
            user_id="user_job_test",
        )
        self.media = db_service.create_media(
            {
                "id": "media_job",
                "user_id": "user_job_test",
                "blob_name": "job_vid.mp4",
                "media_type": "video",
            }
        )

    def test_create_job(self, db_service):
        job = db_service.create_job(
            {
                "id": "job_001",
                "media_id": "media_job",
                "user_id": "user_job_test",
                "job_type": "process",
                "status": "pending",
            }
        )
        assert job.id == "job_001"
        assert job.status == "pending"

    def test_get_job(self, db_service):
        created = db_service.create_job(
            {
                "id": "job_002",
                "media_id": "media_job",
                "user_id": "user_job_test",
                "job_type": "process",
                "status": "pending",
            }
        )
        job = db_service.get_job(created.id)
        assert job is not None

    def test_update_job(self, db_service):
        created = db_service.create_job(
            {
                "id": "job_003",
                "media_id": "media_job",
                "user_id": "user_job_test",
                "job_type": "process",
                "status": "pending",
            }
        )
        updated = db_service.update_job(created.id, {"status": "completed", "progress": 100})
        assert updated.status == "completed"


# =============================================================================
# Project & Clip Operations
# =============================================================================
