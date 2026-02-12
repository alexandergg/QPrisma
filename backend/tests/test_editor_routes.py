"""
Tests for api/routes/editor_routes.py

Covers project CRUD, clip CRUD, clip reordering.
"""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


def _mock_project(user_id, project_id="proj_123", source_media_id="media_456"):
    """Create a mock project object."""
    p = MagicMock()
    p.id = project_id
    p.user_id = user_id
    p.source_media_id = source_media_id
    p.name = "Test Project"
    p.description = "desc"
    p.status = "draft"
    p.to_dict.return_value = {
        "id": project_id,
        "user_id": user_id,
        "source_media_id": source_media_id,
        "name": "Test Project",
        "description": "desc",
        "status": "draft",
        "settings": {},
        "export_format": None,
        "export_url": None,
        "created_at": "2024-01-01T00:00:00",
        "updated_at": "2024-01-01T00:00:00",
        "clips_count": 0,
    }
    p.clips = []
    p.source_media = None
    return p


def _mock_clip(project_id="proj_123", clip_id="clip_789"):
    """Create a mock clip object."""
    c = MagicMock()
    c.id = clip_id
    c.project_id = project_id
    c.start_time = 10.0
    c.end_time = 30.0
    c.to_dict.return_value = {
        "id": clip_id,
        "project_id": project_id,
        "start_time": 10.0,
        "end_time": 30.0,
        "duration": 20.0,
        "order": 0,
        "title": "Test Clip",
        "notes": None,
        "is_ai_suggested": False,
        "viral_score": None,
        "viral_reasons": None,
        "transcript_snippet": None,
        "subtitle_style": None,
        "subtitles_enabled": False,
        "subtitles_data": None,
        "subtitle_settings": None,
        "export_status": "pending",
        "export_url": None,
        "export_format": None,
        "created_at": "2024-01-01T00:00:00",
        "updated_at": "2024-01-01T00:00:00",
    }
    return c


# =============================================================================
# Project Endpoints
# =============================================================================


@pytest.mark.unit
class TestCreateProject:
    def test_requires_auth(self, client):
        resp = client.post("/editor/projects", json={"source_media_id": "m1", "name": "P"})
        assert resp.status_code in (401, 403)

    def test_success(self, authenticated_client, mock_db_service, test_user):
        mock_media = MagicMock()
        mock_media.user_id = test_user.id
        mock_db_service.get_media.return_value = mock_media
        mock_db_service.create_project.return_value = _mock_project(test_user.id)

        with patch("api.routes.editor_routes.get_database_service", return_value=mock_db_service):
            resp = authenticated_client.post(
                "/editor/projects",
                json={"source_media_id": "media_456", "name": "My Project"},
            )

        assert resp.status_code == 201

    def test_media_not_found(self, authenticated_client, mock_db_service):
        mock_db_service.get_media.return_value = None
        with patch("api.routes.editor_routes.get_database_service", return_value=mock_db_service):
            resp = authenticated_client.post(
                "/editor/projects",
                json={"source_media_id": "nonexistent", "name": "P"},
            )
        assert resp.status_code == 404

    def test_media_not_owned(self, authenticated_client, mock_db_service):
        mock_media = MagicMock()
        mock_media.user_id = "other_user"
        mock_db_service.get_media.return_value = mock_media

        with patch("api.routes.editor_routes.get_database_service", return_value=mock_db_service):
            resp = authenticated_client.post(
                "/editor/projects",
                json={"source_media_id": "media_456", "name": "P"},
            )
        assert resp.status_code == 403


@pytest.mark.unit
class TestListProjects:
    def test_empty(self, authenticated_client, mock_db_service):
        mock_db_service.get_projects_by_user.return_value = []
        with patch("api.routes.editor_routes.get_database_service", return_value=mock_db_service):
            resp = authenticated_client.get("/editor/projects")
        assert resp.status_code == 200
        assert resp.json() == []


@pytest.mark.unit
class TestGetProject:
    def test_not_found(self, authenticated_client, mock_db_service):
        mock_db_service.get_project_with_clips.return_value = None
        with patch("api.routes.editor_routes.get_database_service", return_value=mock_db_service):
            resp = authenticated_client.get("/editor/projects/nonexistent")
        assert resp.status_code == 404

    def test_forbidden(self, authenticated_client, mock_db_service):
        project = _mock_project("other_user")
        mock_db_service.get_project_with_clips.return_value = project
        with patch("api.routes.editor_routes.get_database_service", return_value=mock_db_service):
            resp = authenticated_client.get("/editor/projects/proj_123")
        assert resp.status_code == 403

    def test_success(self, authenticated_client, mock_db_service, test_user):
        project = _mock_project(test_user.id)
        mock_db_service.get_project_with_clips.return_value = project
        with patch("api.routes.editor_routes.get_database_service", return_value=mock_db_service):
            resp = authenticated_client.get("/editor/projects/proj_123")
        assert resp.status_code == 200


@pytest.mark.unit
class TestDeleteProject:
    def test_not_found(self, authenticated_client, mock_db_service):
        mock_db_service.get_project.return_value = None
        with patch("api.routes.editor_routes.get_database_service", return_value=mock_db_service):
            resp = authenticated_client.delete("/editor/projects/nonexistent")
        assert resp.status_code == 404

    def test_success(self, authenticated_client, mock_db_service, test_user):
        mock_db_service.get_project.return_value = _mock_project(test_user.id)
        with patch("api.routes.editor_routes.get_database_service", return_value=mock_db_service):
            resp = authenticated_client.delete("/editor/projects/proj_123")
        assert resp.status_code == 204


# =============================================================================
# Clip Endpoints
# =============================================================================


@pytest.mark.unit
class TestCreateClip:
    def test_success(self, authenticated_client, mock_db_service, test_user):
        mock_db_service.get_project.return_value = _mock_project(test_user.id)
        mock_media = MagicMock()
        mock_media.video_metadata = {"duration": 300}
        mock_db_service.get_media.return_value = mock_media
        mock_db_service.create_clip.return_value = _mock_clip()

        with patch("api.routes.editor_routes.get_database_service", return_value=mock_db_service):
            resp = authenticated_client.post(
                "/editor/projects/proj_123/clips",
                json={"start_time": 10, "end_time": 30, "title": "Clip 1"},
            )

        assert resp.status_code == 201

    def test_invalid_times(self, authenticated_client, mock_db_service, test_user):
        mock_db_service.get_project.return_value = _mock_project(test_user.id)
        with patch("api.routes.editor_routes.get_database_service", return_value=mock_db_service):
            resp = authenticated_client.post(
                "/editor/projects/proj_123/clips",
                json={"start_time": 30, "end_time": 10},
            )
        assert resp.status_code == 400


@pytest.mark.unit
class TestGetClip:
    def test_not_found(self, authenticated_client, mock_db_service):
        mock_db_service.get_clip.return_value = None
        with patch("api.routes.editor_routes.get_database_service", return_value=mock_db_service):
            resp = authenticated_client.get("/editor/clips/nonexistent")
        assert resp.status_code == 404

    def test_success(self, authenticated_client, mock_db_service, test_user):
        clip = _mock_clip()
        mock_db_service.get_clip.return_value = clip
        mock_db_service.get_project.return_value = _mock_project(test_user.id)

        with patch("api.routes.editor_routes.get_database_service", return_value=mock_db_service):
            resp = authenticated_client.get("/editor/clips/clip_789")
        assert resp.status_code == 200


@pytest.mark.unit
class TestDeleteClip:
    def test_not_found(self, authenticated_client, mock_db_service):
        mock_db_service.get_clip.return_value = None
        with patch("api.routes.editor_routes.get_database_service", return_value=mock_db_service):
            resp = authenticated_client.delete("/editor/clips/nonexistent")
        assert resp.status_code == 404

    def test_success(self, authenticated_client, mock_db_service, test_user):
        clip = _mock_clip()
        mock_db_service.get_clip.return_value = clip
        mock_db_service.get_project.return_value = _mock_project(test_user.id)

        with patch("api.routes.editor_routes.get_database_service", return_value=mock_db_service):
            resp = authenticated_client.delete("/editor/clips/clip_789")
        assert resp.status_code == 204


@pytest.mark.unit
class TestReorderClips:
    def test_success(self, authenticated_client, mock_db_service, test_user):
        project = _mock_project(test_user.id)
        mock_db_service.get_project.return_value = project

        clip1 = _mock_clip(clip_id="c1")
        clip2 = _mock_clip(clip_id="c2")
        mock_db_service.get_clips_by_project.return_value = [clip1, clip2]
        mock_db_service.reorder_clips.return_value = [clip2, clip1]

        with patch("api.routes.editor_routes.get_database_service", return_value=mock_db_service):
            resp = authenticated_client.post(
                "/editor/projects/proj_123/clips/reorder",
                json={"clip_ids": ["c2", "c1"]},
            )

        assert resp.status_code == 200

    def test_invalid_clip_id(self, authenticated_client, mock_db_service, test_user):
        project = _mock_project(test_user.id)
        mock_db_service.get_project.return_value = project
        mock_db_service.get_clips_by_project.return_value = []

        with patch("api.routes.editor_routes.get_database_service", return_value=mock_db_service):
            resp = authenticated_client.post(
                "/editor/projects/proj_123/clips/reorder",
                json={"clip_ids": ["nonexistent"]},
            )

        assert resp.status_code == 400
