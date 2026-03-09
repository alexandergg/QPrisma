"""
Tests for services/editor_route_service.py

Unit tests for the extracted editor business logic.
Covers clip validation, data building, export formatting,
source-media info construction, and reorder validation.
"""

from unittest.mock import MagicMock

import pytest

from services.editor_route_service import EditorRouteService, EditorValidationError

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def service():
    """EditorRouteService with no SAS URL generator."""
    return EditorRouteService()


@pytest.fixture
def service_with_sas():
    """EditorRouteService with a mock SAS URL generator."""
    sas_gen = MagicMock(
        return_value="https://storage.blob.core.windows.net/container/blob?sas=token"
    )
    return EditorRouteService(sas_url_generator=sas_gen)


@pytest.fixture
def mock_project_data():
    """Mock ProjectCreate-like object."""
    data = MagicMock()
    data.source_media_id = "media_123"
    data.name = "Test Project"
    data.description = "A description"
    data.settings = None
    return data


@pytest.fixture
def mock_project_data_with_settings():
    """Mock ProjectCreate-like object with settings."""
    data = MagicMock()
    data.source_media_id = "media_123"
    data.name = "Test Project"
    data.description = "A description"
    settings = MagicMock()
    settings.model_dump.return_value = {"target_aspect_ratio": "9:16"}
    data.settings = settings
    return data


@pytest.fixture
def mock_clip_data():
    """Mock ClipCreate-like object."""
    data = MagicMock()
    data.start_time = 10.0
    data.end_time = 30.0
    data.title = "Great Clip"
    data.notes = "hook at start"
    data.order = 0
    data.is_ai_suggested = False
    data.viral_score = 85.0
    data.viral_reasons = ["hook", "emotion"]
    data.transcript_snippet = "This is the transcript"
    return data


@pytest.fixture
def mock_clip_update():
    """Mock ClipUpdate-like object (partial update)."""
    upd = MagicMock()
    upd.start_time = 5.0
    upd.end_time = 25.0
    upd.title = "Updated Title"
    upd.notes = None
    upd.order = None
    return upd


@pytest.fixture
def mock_project_update():
    """Mock ProjectUpdate-like object."""
    upd = MagicMock()
    upd.name = "New Name"
    upd.description = None
    upd.status = None
    upd.settings = None
    return upd


@pytest.fixture
def mock_project_update_with_status():
    """Mock ProjectUpdate with status."""
    upd = MagicMock()
    upd.name = None
    upd.description = None
    upd.status = MagicMock()
    upd.status.value = "completed"
    upd.settings = None
    return upd


@pytest.fixture
def mock_current_clip():
    """Mock existing clip in database."""
    clip = MagicMock()
    clip.start_time = 10.0
    clip.end_time = 30.0
    clip.project_id = "proj_1"
    return clip


@pytest.fixture
def mock_subtitle_config():
    """Mock ClipSubtitleUpdate-like object."""
    cfg = MagicMock()
    cfg.subtitles_enabled = True
    cfg.subtitle_style = MagicMock()
    cfg.subtitle_style.value = "hormozi"
    cfg.subtitle_settings = None
    return cfg


@pytest.fixture
def mock_subtitle_config_with_settings():
    """Mock ClipSubtitleUpdate with settings."""
    cfg = MagicMock()
    cfg.subtitles_enabled = True
    cfg.subtitle_style = MagicMock()
    cfg.subtitle_style.value = "mrbeast"
    settings_mock = MagicMock()
    settings_mock.model_dump.return_value = {
        "font_family": "Impact",
        "font_size": "L",
    }
    cfg.subtitle_settings = settings_mock
    return cfg


@pytest.fixture
def mock_db():
    """Minimal mock database service."""
    db = MagicMock()
    db.get_media.return_value = None
    db.get_clips_by_project.return_value = []
    return db


# =============================================================================
# Clip Time Validation
# =============================================================================


@pytest.mark.unit
class TestValidateClipTimes:
    def test_valid_times(self, service):
        service.validate_clip_times(0.0, 30.0)

    def test_end_equal_start_raises(self, service):
        with pytest.raises(EditorValidationError, match="end_time must be greater"):
            service.validate_clip_times(10.0, 10.0)

    def test_end_before_start_raises(self, service):
        with pytest.raises(EditorValidationError, match="end_time must be greater"):
            service.validate_clip_times(20.0, 10.0)

    def test_exceeds_duration_raises(self, service, mock_db):
        media = MagicMock()
        media.video_metadata = {"duration": 60.0}
        mock_db.get_media.return_value = media

        with pytest.raises(EditorValidationError, match="exceeds video duration"):
            service.validate_clip_times(0.0, 90.0, db=mock_db, source_media_id="media_1")

    def test_within_duration_passes(self, service, mock_db):
        media = MagicMock()
        media.video_metadata = {"duration": 120.0}
        mock_db.get_media.return_value = media

        service.validate_clip_times(0.0, 90.0, db=mock_db, source_media_id="media_1")

    def test_no_media_found_skips_duration_check(self, service, mock_db):
        mock_db.get_media.return_value = None
        # Should not raise even though end_time might be huge
        service.validate_clip_times(0.0, 9999.0, db=mock_db, source_media_id="media_1")

    def test_no_video_metadata_skips_duration_check(self, service, mock_db):
        media = MagicMock()
        media.video_metadata = None
        mock_db.get_media.return_value = media

        service.validate_clip_times(0.0, 9999.0, db=mock_db, source_media_id="media_1")

    def test_zero_duration_skips_check(self, service, mock_db):
        media = MagicMock()
        media.video_metadata = {"duration": 0}
        mock_db.get_media.return_value = media

        service.validate_clip_times(0.0, 100.0, db=mock_db, source_media_id="media_1")

    def test_no_db_skips_duration_check(self, service):
        # No db or source_media_id → no duration check
        service.validate_clip_times(0.0, 99999.0)

    def test_no_source_media_id_skips_duration_check(self, service, mock_db):
        service.validate_clip_times(0.0, 99999.0, db=mock_db, source_media_id=None)


# =============================================================================
# Clip Update Time Validation
# =============================================================================


@pytest.mark.unit
class TestValidateClipUpdateTimes:
    def test_valid_update(self, service, mock_current_clip):
        service.validate_clip_update_times({"start_time": 5.0, "end_time": 25.0}, mock_current_clip)

    def test_only_start_updated_valid(self, service, mock_current_clip):
        # end_time falls back to clip.end_time (30.0)
        service.validate_clip_update_times({"start_time": 5.0}, mock_current_clip)

    def test_only_end_updated_valid(self, service, mock_current_clip):
        # start_time falls back to clip.start_time (10.0)
        service.validate_clip_update_times({"end_time": 25.0}, mock_current_clip)

    def test_start_after_end_raises(self, service, mock_current_clip):
        with pytest.raises(EditorValidationError, match="end_time must be greater"):
            service.validate_clip_update_times({"start_time": 35.0}, mock_current_clip)

    def test_equal_times_raises(self, service, mock_current_clip):
        with pytest.raises(EditorValidationError, match="end_time must be greater"):
            service.validate_clip_update_times({"start_time": 30.0}, mock_current_clip)

    def test_empty_update_uses_clip_values(self, service, mock_current_clip):
        # clip.start_time=10, clip.end_time=30 → valid
        service.validate_clip_update_times({}, mock_current_clip)


# =============================================================================
# Build Clip Create Dict
# =============================================================================


@pytest.mark.unit
class TestBuildClipCreateDict:
    def test_all_fields(self, service, mock_clip_data):
        result = service.build_clip_create_dict("proj_1", mock_clip_data)

        assert result["project_id"] == "proj_1"
        assert result["start_time"] == 10.0
        assert result["end_time"] == 30.0
        assert result["title"] == "Great Clip"
        assert result["notes"] == "hook at start"
        assert result["order"] == 0
        assert result["is_ai_suggested"] is False
        assert result["viral_score"] == 85.0
        assert result["viral_reasons"] == ["hook", "emotion"]
        assert result["transcript_snippet"] == "This is the transcript"

    def test_keys_present(self, service, mock_clip_data):
        result = service.build_clip_create_dict("proj_1", mock_clip_data)
        expected_keys = {
            "project_id",
            "start_time",
            "end_time",
            "title",
            "notes",
            "order",
            "is_ai_suggested",
            "viral_score",
            "viral_reasons",
            "transcript_snippet",
        }
        assert set(result.keys()) == expected_keys


# =============================================================================
# Build Clip Update Dict
# =============================================================================


@pytest.mark.unit
class TestBuildClipUpdateDict:
    def test_partial_update(self, service, mock_clip_update):
        result = service.build_clip_update_dict(mock_clip_update)
        assert result["start_time"] == 5.0
        assert result["end_time"] == 25.0
        assert result["title"] == "Updated Title"
        # notes and order are None → not included
        assert "notes" not in result
        assert "order" not in result

    def test_empty_update(self, service):
        upd = MagicMock()
        upd.start_time = None
        upd.end_time = None
        upd.title = None
        upd.notes = None
        upd.order = None
        result = service.build_clip_update_dict(upd)
        assert result == {}


# =============================================================================
# Build Project Create Dict
# =============================================================================


@pytest.mark.unit
class TestBuildProjectCreateDict:
    def test_without_settings(self, service, mock_project_data):
        result = service.build_project_create_dict("user_1", mock_project_data)
        assert result["user_id"] == "user_1"
        assert result["source_media_id"] == "media_123"
        assert result["name"] == "Test Project"
        assert result["description"] == "A description"
        assert result["settings"] == {}

    def test_with_settings(self, service, mock_project_data_with_settings):
        result = service.build_project_create_dict("user_1", mock_project_data_with_settings)
        assert result["settings"] == {"target_aspect_ratio": "9:16"}


# =============================================================================
# Build Project Update Dict
# =============================================================================


@pytest.mark.unit
class TestBuildProjectUpdateDict:
    def test_name_only(self, service, mock_project_update):
        result = service.build_project_update_dict(mock_project_update)
        assert result == {"name": "New Name"}

    def test_with_status(self, service, mock_project_update_with_status):
        result = service.build_project_update_dict(mock_project_update_with_status)
        assert result == {"status": "completed"}

    def test_empty(self, service):
        upd = MagicMock()
        upd.name = None
        upd.description = None
        upd.status = None
        upd.settings = None
        result = service.build_project_update_dict(upd)
        assert result == {}

    def test_all_fields(self, service):
        upd = MagicMock()
        upd.name = "Name"
        upd.description = "Desc"
        upd.status = MagicMock()
        upd.status.value = "archived"
        upd.settings = MagicMock()
        upd.settings.model_dump.return_value = {"resolution": "1080p"}
        result = service.build_project_update_dict(upd)
        assert result == {
            "name": "Name",
            "description": "Desc",
            "status": "archived",
            "settings": {"resolution": "1080p"},
        }


# =============================================================================
# Build Project With Details
# =============================================================================


@pytest.mark.unit
class TestBuildProjectWithDetails:
    def test_no_source_media(self, service):
        project = MagicMock()
        project.to_dict.return_value = {"id": "p1", "name": "proj"}
        clip1 = MagicMock()
        clip1.to_dict.return_value = {"id": "c1"}
        clip2 = MagicMock()
        clip2.to_dict.return_value = {"id": "c2"}
        project.clips = [clip1, clip2]
        project.source_media = None

        result = service.build_project_with_details(project)
        assert result["id"] == "p1"
        assert result["clips"] == [{"id": "c1"}, {"id": "c2"}]
        assert result["source_media"] is None

    def test_with_source_media(self, service_with_sas):
        project = MagicMock()
        project.to_dict.return_value = {"id": "p1"}
        project.clips = []

        media = MagicMock()
        media.id = "m1"
        media.original_filename = "video.mp4"
        media.blob_name = "uploads/video.mp4"
        media.video_metadata = {"duration": 120.0}
        media.media_type = "video"
        media.processed = True
        project.source_media = media

        result = service_with_sas.build_project_with_details(project)
        assert result["source_media"]["id"] == "m1"
        assert result["source_media"]["filename"] == "video.mp4"
        assert result["source_media"]["duration"] == 120.0
        assert result["source_media"]["blob_url"] is not None


# =============================================================================
# Build Source Media Info
# =============================================================================


@pytest.mark.unit
class TestBuildSourceMediaInfo:
    def test_returns_none_when_no_source_media(self, service):
        project = MagicMock()
        project.source_media = None
        assert service.build_source_media_info(project) is None

    def test_full_info(self, service_with_sas):
        project = MagicMock()
        media = MagicMock()
        media.id = "m1"
        media.original_filename = "my_video.mp4"
        media.blob_name = "uploads/my_video.mp4"
        media.video_metadata = {"duration": 300.5}
        media.media_type = "video"
        media.processed = True
        project.source_media = media

        result = service_with_sas.build_source_media_info(project)
        assert result["id"] == "m1"
        assert result["filename"] == "my_video.mp4"
        assert result["duration"] == 300.5
        assert "blob.core.windows.net" in result["blob_url"]
        assert result["media_type"] == "video"
        assert result["processed"] is True

    def test_no_original_filename_falls_back_to_blob_name(self, service):
        project = MagicMock()
        media = MagicMock()
        media.id = "m1"
        media.original_filename = None
        media.blob_name = "uploads/abc123.mp4"
        media.video_metadata = None
        media.media_type = "video"
        media.processed = False
        project.source_media = media

        result = service.build_source_media_info(project)
        assert result["filename"] == "uploads/abc123.mp4"
        assert result["duration"] is None
        assert result["blob_url"] is None  # no SAS generator

    def test_no_blob_name_returns_none_url(self, service_with_sas):
        project = MagicMock()
        media = MagicMock()
        media.id = "m1"
        media.original_filename = "vid.mp4"
        media.blob_name = None
        media.video_metadata = {}
        media.media_type = "video"
        media.processed = True
        project.source_media = media

        result = service_with_sas.build_source_media_info(project)
        assert result["blob_url"] is None


# =============================================================================
# Build Subtitle Update Dict
# =============================================================================


@pytest.mark.unit
class TestBuildSubtitleUpdateDict:
    def test_without_settings(self, service, mock_subtitle_config):
        result = service.build_subtitle_update_dict(mock_subtitle_config)
        assert result == {
            "subtitles_enabled": True,
            "subtitle_style": "hormozi",
        }

    def test_with_settings(self, service, mock_subtitle_config_with_settings):
        result = service.build_subtitle_update_dict(mock_subtitle_config_with_settings)
        assert result == {
            "subtitles_enabled": True,
            "subtitle_style": "mrbeast",
            "subtitle_settings": {"font_family": "Impact", "font_size": "L"},
        }


# =============================================================================
# Validate and Prepare Bulk Clips
# =============================================================================


@pytest.mark.unit
class TestValidateAndPrepareBulkClips:
    def test_valid_clips(self, service):
        clip1 = MagicMock()
        clip1.start_time = 0.0
        clip1.end_time = 10.0
        clip1.title = "C1"
        clip1.notes = None
        clip1.order = 0
        clip1.is_ai_suggested = True
        clip1.viral_score = 90.0
        clip1.viral_reasons = ["hook"]
        clip1.transcript_snippet = "text"

        clip2 = MagicMock()
        clip2.start_time = 15.0
        clip2.end_time = 30.0
        clip2.title = "C2"
        clip2.notes = "note"
        clip2.order = 1
        clip2.is_ai_suggested = False
        clip2.viral_score = None
        clip2.viral_reasons = None
        clip2.transcript_snippet = None

        result = service.validate_and_prepare_bulk_clips("proj_1", [clip1, clip2])
        assert len(result) == 2
        assert result[0]["project_id"] == "proj_1"
        assert result[0]["start_time"] == 0.0
        assert result[1]["title"] == "C2"

    def test_invalid_clip_raises(self, service):
        bad_clip = MagicMock()
        bad_clip.start_time = 20.0
        bad_clip.end_time = 10.0  # end before start

        with pytest.raises(
            EditorValidationError,
            match="Invalid clip: end_time must be greater",
        ):
            service.validate_and_prepare_bulk_clips("proj_1", [bad_clip])

    def test_empty_list(self, service):
        result = service.validate_and_prepare_bulk_clips("proj_1", [])
        assert result == []


# =============================================================================
# Validate Reorder IDs
# =============================================================================


@pytest.mark.unit
class TestValidateReorderIds:
    def test_valid_ids(self, service, mock_db):
        c1 = MagicMock()
        c1.id = "c1"
        c2 = MagicMock()
        c2.id = "c2"
        mock_db.get_clips_by_project.return_value = [c1, c2]

        service.validate_reorder_ids(mock_db, "proj_1", ["c2", "c1"])

    def test_unknown_id_raises(self, service, mock_db):
        c1 = MagicMock()
        c1.id = "c1"
        mock_db.get_clips_by_project.return_value = [c1]

        with pytest.raises(
            EditorValidationError,
            match="Clip c_unknown not found in project",
        ):
            service.validate_reorder_ids(mock_db, "proj_1", ["c1", "c_unknown"])

    def test_empty_project_all_ids_invalid(self, service, mock_db):
        mock_db.get_clips_by_project.return_value = []
        with pytest.raises(EditorValidationError, match="not found in project"):
            service.validate_reorder_ids(mock_db, "proj_1", ["c1"])


# =============================================================================
# Format Export Result
# =============================================================================


@pytest.mark.unit
class TestFormatExportResult:
    def test_success_result(self, service):
        result = MagicMock()
        result.status = "done"
        result.clip_id = "clip_1"
        result.output_url = "https://storage/exports/clip_1.mp4"
        result.file_size_bytes = 5_000_000
        result.duration_seconds = 30.0
        result.error_message = None

        formatted = service.format_export_result(result)
        assert formatted["success"] is True
        assert formatted["clip_id"] == "clip_1"
        assert formatted["status"] == "done"
        assert formatted["output_url"] == "https://storage/exports/clip_1.mp4"
        assert formatted["file_size_bytes"] == 5_000_000
        assert formatted["duration_seconds"] == 30.0
        assert formatted["error"] is None

    def test_failed_result(self, service):
        result = MagicMock()
        result.status = "failed"
        result.clip_id = "clip_2"
        result.output_url = None
        result.file_size_bytes = None
        result.duration_seconds = None
        result.error_message = "FFmpeg error"

        formatted = service.format_export_result(result)
        assert formatted["success"] is False
        assert formatted["error"] == "FFmpeg error"


# =============================================================================
# Summarize Batch Export Results
# =============================================================================


@pytest.mark.unit
class TestSummarizeBatchExportResults:
    def test_mixed_results(self, service):
        r1 = MagicMock()
        r1.status = "done"
        r1.clip_id = "c1"
        r1.output_url = "url1"
        r1.file_size_bytes = 1000
        r1.error_message = None

        r2 = MagicMock()
        r2.status = "failed"
        r2.clip_id = "c2"
        r2.output_url = None
        r2.file_size_bytes = None
        r2.error_message = "codec error"

        r3 = MagicMock()
        r3.status = "done"
        r3.clip_id = "c3"
        r3.output_url = "url3"
        r3.file_size_bytes = 2000
        r3.error_message = None

        summary = service.summarize_batch_export_results([r1, r2, r3])
        assert summary["total"] == 3
        assert summary["successful"] == 2
        assert summary["failed"] == 1
        assert len(summary["results"]) == 3
        assert summary["results"][1]["error"] == "codec error"

    def test_empty_results(self, service):
        summary = service.summarize_batch_export_results([])
        assert summary["total"] == 0
        assert summary["successful"] == 0
        assert summary["failed"] == 0
        assert summary["results"] == []

    def test_all_successful(self, service):
        r = MagicMock()
        r.status = "done"
        r.clip_id = "c1"
        r.output_url = "url"
        r.file_size_bytes = 1000
        r.error_message = None

        summary = service.summarize_batch_export_results([r])
        assert summary["successful"] == 1
        assert summary["failed"] == 0

    def test_result_keys(self, service):
        r = MagicMock()
        r.status = "done"
        r.clip_id = "c1"
        r.output_url = "url"
        r.file_size_bytes = 1000
        r.error_message = None

        summary = service.summarize_batch_export_results([r])
        entry = summary["results"][0]
        assert set(entry.keys()) == {
            "clip_id",
            "status",
            "output_url",
            "file_size_bytes",
            "error",
        }


# =============================================================================
# EditorValidationError
# =============================================================================


@pytest.mark.unit
class TestEditorValidationError:
    def test_is_value_error(self):
        err = EditorValidationError("bad input")
        assert isinstance(err, ValueError)

    def test_message(self):
        err = EditorValidationError("end_time must be greater")
        assert str(err) == "end_time must be greater"


# =============================================================================
# Constructor Injection
# =============================================================================


@pytest.mark.unit
class TestConstructorInjection:
    def test_default_no_sas_generator(self, service):
        assert service._generate_sas_url is None

    def test_sas_generator_injected(self, service_with_sas):
        assert service_with_sas._generate_sas_url is not None

    def test_sas_generator_called_for_blob(self, service_with_sas):
        project = MagicMock()
        media = MagicMock()
        media.id = "m1"
        media.original_filename = "v.mp4"
        media.blob_name = "uploads/v.mp4"
        media.video_metadata = {"duration": 60}
        media.media_type = "video"
        media.processed = True
        project.source_media = media

        service_with_sas.build_source_media_info(project)
        service_with_sas._generate_sas_url.assert_called_once_with("uploads/v.mp4", 4)
