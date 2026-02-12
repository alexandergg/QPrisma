"""
Tests for services/database_service.py

Uses SQLite in-memory for fast, isolated tests of CRUD operations.
"""

import pytest
from sqlalchemy import create_engine
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

    def test_health_check(self, db_service):
        result = db_service.health_check()
        assert result["status"] == "healthy"


# =============================================================================
# User CRUD
# =============================================================================


@pytest.mark.unit
class TestUserCRUD:
    def test_create_user(self, db_service):
        user = db_service.create_user(
            email="test@example.com",
            hashed_password="$2b$12$hash",
            full_name="Test User",
        )
        assert user.email == "test@example.com"
        assert user.id is not None

    def test_get_user_by_email(self, db_service):
        db_service.create_user(
            email="lookup@example.com",
            hashed_password="$2b$12$hash",
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
            hashed_password="$2b$12$hash",
            full_name="Custom",
            user_id="user_custom123",
        )
        assert user.id == "user_custom123"

    def test_create_duplicate_email_raises(self, db_service):
        db_service.create_user(email="dup@example.com", hashed_password="hash1", full_name="First")
        with pytest.raises(Exception):
            db_service.create_user(email="dup@example.com", hashed_password="hash2", full_name="Second")


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
            hashed_password="$2b$12$hash",
            full_name="Media User",
            user_id="user_media_test",
        )

    def test_create_media(self, db_service):
        media = db_service.create_media({
            "id": "media_001",
            "user_id": "user_media_test",
            "blob_name": "video.mp4",
            "media_type": "video",
            "original_filename": "myvideo.mp4",
        })
        assert media.id == "media_001"

    def test_get_media(self, db_service):
        db_service.create_media({
            "id": "media_002",
            "user_id": "user_media_test",
            "blob_name": "vid2.mp4",
            "media_type": "video",
        })
        media = db_service.get_media("media_002")
        assert media is not None
        assert media.blob_name == "vid2.mp4"

    def test_get_media_not_found(self, db_service):
        media = db_service.get_media("nonexistent")
        assert media is None

    def test_get_media_by_user(self, db_service):
        db_service.create_media({
            "id": "media_003",
            "user_id": "user_media_test",
            "blob_name": "vid3.mp4",
            "media_type": "video",
        })
        media_list = db_service.get_media_by_user("user_media_test")
        assert len(media_list) >= 1

    def test_get_media_by_user_empty(self, db_service):
        media_list = db_service.get_media_by_user("nonexistent_user")
        assert media_list == []

    def test_update_media(self, db_service):
        db_service.create_media({
            "id": "media_004",
            "user_id": "user_media_test",
            "blob_name": "vid4.mp4",
            "media_type": "video",
        })
        updated = db_service.update_media("media_004", {"processing_status": "completed"})
        assert updated.processing_status == "completed"

    def test_delete_media(self, db_service):
        db_service.create_media({
            "id": "media_005",
            "user_id": "user_media_test",
            "blob_name": "vid5.mp4",
            "media_type": "video",
        })
        db_service.delete_media("media_005")
        assert db_service.get_media("media_005") is None

    def test_pagination(self, db_service):
        for i in range(5):
            db_service.create_media({
                "id": f"media_page_{i}",
                "user_id": "user_media_test",
                "blob_name": f"v{i}.mp4",
                "media_type": "video",
            })
        page = db_service.get_media_by_user("user_media_test", limit=2, offset=0)
        assert len(page) == 2


# =============================================================================
# Job Operations
# =============================================================================


@pytest.mark.unit
class TestJobOperations:
    @pytest.fixture(autouse=True)
    def _setup_user_and_media(self, db_service):
        self.user = db_service.create_user(
            email="jobuser@example.com",
            hashed_password="hash",
            full_name="Job User",
            user_id="user_job_test",
        )
        self.media = db_service.create_media({
            "id": "media_job",
            "user_id": "user_job_test",
            "blob_name": "job_vid.mp4",
            "media_type": "video",
        })

    def test_create_job(self, db_service):
        job = db_service.create_job({
            "id": "job_001",
            "media_id": "media_job",
            "user_id": "user_job_test",
            "job_type": "process",
            "status": "pending",
        })
        assert job.id == "job_001"
        assert job.status == "pending"

    def test_get_job(self, db_service):
        created = db_service.create_job({
            "id": "job_002",
            "media_id": "media_job",
            "user_id": "user_job_test",
            "job_type": "process",
            "status": "pending",
        })
        job = db_service.get_job(created.id)
        assert job is not None

    def test_update_job(self, db_service):
        created = db_service.create_job({
            "id": "job_003",
            "media_id": "media_job",
            "user_id": "user_job_test",
            "job_type": "process",
            "status": "pending",
        })
        updated = db_service.update_job(created.id, {"status": "completed", "progress": 100})
        assert updated.status == "completed"


# =============================================================================
# Project & Clip Operations
# =============================================================================


@pytest.mark.unit
class TestProjectClipOperations:
    @pytest.fixture(autouse=True)
    def _setup(self, db_service):
        self.user = db_service.create_user(
            email="projuser@example.com",
            hashed_password="hash",
            full_name="Proj User",
            user_id="user_proj_test",
        )
        self.media = db_service.create_media({
            "id": "media_proj",
            "user_id": "user_proj_test",
            "blob_name": "proj_vid.mp4",
            "media_type": "video",
        })

    def test_create_project(self, db_service):
        project = db_service.create_project({
            "user_id": "user_proj_test",
            "source_media_id": "media_proj",
            "name": "Test Project",
        })
        assert project.id is not None
        assert project.name == "Test Project"

    def test_get_project(self, db_service):
        created = db_service.create_project({
            "user_id": "user_proj_test",
            "source_media_id": "media_proj",
            "name": "Get Project",
        })
        project = db_service.get_project(created.id)
        assert project is not None

    def test_get_project_not_found(self, db_service):
        assert db_service.get_project("nonexistent") is None

    def test_create_clip(self, db_service):
        project = db_service.create_project({
            "user_id": "user_proj_test",
            "source_media_id": "media_proj",
            "name": "Clip Project",
        })
        clip = db_service.create_clip({
            "project_id": project.id,
            "start_time": 10.0,
            "end_time": 30.0,
            "title": "Test Clip",
        })
        assert clip.id is not None
        assert clip.start_time == 10.0

    def test_get_clips_by_project(self, db_service):
        project = db_service.create_project({
            "user_id": "user_proj_test",
            "source_media_id": "media_proj",
            "name": "Clips Project",
        })
        db_service.create_clip({"project_id": project.id, "start_time": 0, "end_time": 10})
        db_service.create_clip({"project_id": project.id, "start_time": 10, "end_time": 20})
        clips = db_service.get_clips_by_project(project.id)
        assert len(clips) == 2

    def test_delete_project(self, db_service):
        project = db_service.create_project({
            "user_id": "user_proj_test",
            "source_media_id": "media_proj",
            "name": "Delete Me",
        })
        db_service.delete_project(project.id)
        assert db_service.get_project(project.id) is None
