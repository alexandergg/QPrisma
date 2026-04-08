"""
Tests for api/routes/jobs_routes.py

Covers job submission, status, cancellation, and listing.
"""

from unittest.mock import patch

import pytest


@pytest.mark.unit
class TestSubmitJobRemoved:
    """POST /jobs/submit was removed — verify 404/405."""

    def test_submit_endpoint_gone(self, authenticated_client):
        resp = authenticated_client.post(
            "/jobs/submit", json={"video_id": "v1", "blob_name": "v1.mp4"}
        )
        assert resp.status_code in (404, 405)


@pytest.mark.unit
class TestGetJobStatus:
    def test_requires_auth(self, client):
        resp = client.get("/jobs/job_123")
        assert resp.status_code in (401, 403)

    def test_no_celery_returns_503(self, authenticated_client):
        with patch("api.routes.jobs_routes.get_celery_app", return_value=None):
            resp = authenticated_client.get("/jobs/job_123")
        assert resp.status_code == 503


@pytest.mark.unit
class TestCancelJob:
    def test_requires_auth(self, client):
        resp = client.post("/jobs/job_123/cancel")
        assert resp.status_code in (401, 403)

    def test_no_celery_returns_503(self, authenticated_client):
        with patch("api.routes.jobs_routes.get_celery_app", return_value=None):
            resp = authenticated_client.post("/jobs/job_123/cancel")
        assert resp.status_code == 503


@pytest.mark.unit
class TestListJobs:
    def test_requires_auth(self, client):
        resp = client.get("/jobs/")
        assert resp.status_code in (401, 403)

    def test_fallback_on_error(self, authenticated_client):
        """When cache fails, returns empty list gracefully."""
        with patch(
            "api.routes.jobs_routes.get_cache_service",
            side_effect=ImportError("no cache"),
            create=True,
        ):
            resp = authenticated_client.get("/jobs/")

        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 0
        assert body["jobs"] == []


@pytest.mark.unit
class TestGetJobResult:
    def test_requires_auth(self, client):
        resp = client.get("/jobs/job_123/result")
        assert resp.status_code in (401, 403)

    def test_no_celery_returns_503(self, authenticated_client):
        with patch("api.routes.jobs_routes.get_celery_app", return_value=None):
            resp = authenticated_client.get("/jobs/job_123/result")
        assert resp.status_code == 503


@pytest.mark.unit
class TestCeleryStateMapping:
    def test_known_states(self):
        from api.routes.jobs_routes import JobStatus, celery_state_to_job_status

        assert celery_state_to_job_status("PENDING") == JobStatus.PENDING
        assert celery_state_to_job_status("STARTED") == JobStatus.STARTED
        assert celery_state_to_job_status("SUCCESS") == JobStatus.SUCCESS
        assert celery_state_to_job_status("FAILURE") == JobStatus.FAILURE
        assert celery_state_to_job_status("REVOKED") == JobStatus.REVOKED

    def test_unknown_state_defaults_to_processing(self):
        from api.routes.jobs_routes import JobStatus, celery_state_to_job_status

        assert celery_state_to_job_status("CUSTOM_STATE") == JobStatus.PROCESSING
