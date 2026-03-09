"""
Tests for the transcribe_audio_task Celery task.

Verifies:
- Whisper backend logging and metadata in the return dict
- Granular progress updates (extract → transcribe → analyse)
- Fallback to standalone AudioProcessor when VideoProcessor is unavailable
- Error handling preserves metadata fields
- Chunked / parallel flags propagated from transcription result
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SETTINGS_PATCH_TARGET = "core.config.settings"


def _make_transcription(
    text: str = "Hello world",
    language: str = "en",
    duration: float = 10.0,
    chunked: bool = False,
    chunk_count: int | None = None,
) -> dict:
    """Build a minimal Whisper-style transcription result."""
    result = {
        "text": text,
        "language": language,
        "duration": duration,
        "segments": [{"start": 0.0, "end": duration, "text": text}],
        "words": [{"word": w, "start": 0.0, "end": 1.0} for w in text.split()],
    }
    if chunked:
        result["chunked"] = True
        result["chunk_count"] = chunk_count or 3
    return result


def _reset_module_globals():
    """Reset the module-level singletons used by video_tasks."""
    import tasks.video_tasks as vt

    vt._services_initialized = False
    vt._blob_service = None
    vt._openai_client = None
    vt._video_processor = None
    vt._cached_processor = None
    vt._cache_service = None
    vt._db_service = None


def _setup_audio_proc(
    transcription: dict | None = None,
    analysis: dict | None = None,
    extract_side_effect: Exception | None = None,
) -> MagicMock:
    """Create a mocked AudioProcessor with configurable behaviour."""
    mock = MagicMock()
    if extract_side_effect:
        mock.extract_audio_from_video.side_effect = extract_side_effect
    else:
        mock.extract_audio_from_video.return_value = "/tmp/audio.mp3"
    mock.transcribe_audio = AsyncMock(return_value=transcription or _make_transcription())
    mock.analyze_transcription = AsyncMock(return_value=analysis or {})
    return mock


def _attach_video_processor(vt_module, audio_proc: MagicMock):
    """Wire *audio_proc* into a fake VideoProcessor on the tasks module."""
    mock_vp = MagicMock()
    mock_vp.audio_processor = audio_proc
    vt_module._video_processor = mock_vp


def _collect_progress_messages(mock_update) -> list[str]:
    """Extract the *message* arg from every ``update_job_status.delay()`` call."""
    return [
        call.args[4] if len(call.args) > 4 else call.kwargs.get("message", "")
        for call in mock_update.delay.call_args_list
    ]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestTranscribeAudioTask:
    """Tests for transcribe_audio_task."""

    def setup_method(self):
        _reset_module_globals()

    # -- success path: via VideoProcessor -----------------------------------

    @patch("tasks.video_tasks.update_job_status")
    @patch("tasks.video_tasks._initialize_services")
    def test_success_azure_backend(self, mock_init, mock_update):
        """Happy path: Azure backend returns transcription with metadata."""
        import tasks.video_tasks as vt

        long_text = (
            "Hello world, this is a sufficiently long transcription text "
            "that exceeds the fifty character analysis threshold"
        )
        audio_proc = _setup_audio_proc(
            transcription=_make_transcription(text=long_text),
            analysis={"summary": "greeting"},
        )
        _attach_video_processor(vt, audio_proc)
        mock_update.delay = MagicMock()

        with patch(_SETTINGS_PATCH_TARGET) as mock_settings:
            mock_settings.azure.whisper_backend = "azure"
            mock_settings.azure.openai_whisper_rpm = 3

            result = vt.transcribe_audio_task.__wrapped__("/tmp/video.mp4", "job-1")

        assert result["success"] is True
        assert result["error"] is None
        assert result["whisper_backend"] == "azure"
        assert result["chunked"] is False
        assert result["chunk_count"] == 1
        assert result["parallel_transcription"] is False
        assert result["transcription"]["text"] == long_text
        assert result["analysis"] == {"summary": "greeting"}

    @patch("tasks.video_tasks.update_job_status")
    @patch("tasks.video_tasks._initialize_services")
    def test_success_faster_whisper_backend(self, mock_init, mock_update):
        """faster-whisper backend is reported correctly."""
        import tasks.video_tasks as vt

        _attach_video_processor(vt, _setup_audio_proc())
        mock_update.delay = MagicMock()

        with patch(_SETTINGS_PATCH_TARGET) as mock_settings:
            mock_settings.azure.whisper_backend = "faster_whisper"
            mock_settings.azure.openai_whisper_rpm = 3

            result = vt.transcribe_audio_task.__wrapped__("/tmp/video.mp4", "job-2")

        assert result["whisper_backend"] == "faster_whisper"

    # -- chunked transcription metadata -------------------------------------

    @patch("tasks.video_tasks.update_job_status")
    @patch("tasks.video_tasks._initialize_services")
    def test_chunked_transcription_metadata(self, mock_init, mock_update):
        """When audio is chunked, metadata reflects chunk info."""
        import tasks.video_tasks as vt

        _attach_video_processor(
            vt,
            _setup_audio_proc(
                transcription=_make_transcription(chunked=True, chunk_count=5),
            ),
        )
        mock_update.delay = MagicMock()

        with patch(_SETTINGS_PATCH_TARGET) as mock_settings:
            mock_settings.azure.whisper_backend = "azure"
            mock_settings.azure.openai_whisper_rpm = 3

            result = vt.transcribe_audio_task.__wrapped__("/tmp/video.mp4", "job-3")

        assert result["chunked"] is True
        assert result["chunk_count"] == 5
        assert result["parallel_transcription"] is True

    # -- granular progress updates ------------------------------------------

    @patch("tasks.video_tasks.update_job_status")
    @patch("tasks.video_tasks._initialize_services")
    def test_progress_updates_sent(self, mock_init, mock_update):
        """Three progress updates: extract, transcribe, analyse."""
        import tasks.video_tasks as vt

        long_text = (
            "This is a longer text that passes the fifty character minimum "
            "for analysis triggering"
        )
        audio_proc = _setup_audio_proc(
            transcription=_make_transcription(text=long_text),
            analysis={"key": "val"},
        )
        _attach_video_processor(vt, audio_proc)
        mock_update.delay = MagicMock()

        with patch(_SETTINGS_PATCH_TARGET) as mock_settings:
            mock_settings.azure.whisper_backend = "azure"
            mock_settings.azure.openai_whisper_rpm = 3

            vt.transcribe_audio_task.__wrapped__("/tmp/video.mp4", "job-4")

        messages = _collect_progress_messages(mock_update)
        assert any("Extracting audio" in m for m in messages)
        assert any("Transcribing with" in m for m in messages)
        assert any("Analyzing transcription" in m for m in messages)

    @patch("tasks.video_tasks.update_job_status")
    @patch("tasks.video_tasks._initialize_services")
    def test_progress_label_faster_whisper(self, mock_init, mock_update):
        """Transcribing step shows 'faster-whisper (local)' label."""
        import tasks.video_tasks as vt

        _attach_video_processor(vt, _setup_audio_proc())
        mock_update.delay = MagicMock()

        with patch(_SETTINGS_PATCH_TARGET) as mock_settings:
            mock_settings.azure.whisper_backend = "faster_whisper"
            mock_settings.azure.openai_whisper_rpm = 3

            vt.transcribe_audio_task.__wrapped__("/tmp/video.mp4", "job-5")

        messages = _collect_progress_messages(mock_update)
        assert any("faster-whisper (local)" in m for m in messages)

    # -- fallback: standalone AudioProcessor --------------------------------

    @patch("tasks.video_tasks.update_job_status")
    @patch("tasks.video_tasks._initialize_services")
    def test_fallback_standalone_audio_processor(self, mock_init, mock_update):
        """When VideoProcessor is None but _openai_client exists, create AudioProcessor."""
        import tasks.video_tasks as vt

        vt._video_processor = None
        vt._openai_client = AsyncMock()

        mock_audio_proc = _setup_audio_proc()
        mock_update.delay = MagicMock()

        with (
            patch(_SETTINGS_PATCH_TARGET) as mock_settings,
            patch(
                "services.audio_processor.AudioProcessor",
                return_value=mock_audio_proc,
            ) as mock_cls,
        ):
            mock_settings.azure.whisper_backend = "azure"
            mock_settings.azure.openai_whisper_rpm = 3

            result = vt.transcribe_audio_task.__wrapped__("/tmp/video.mp4", "job-6")

        assert result["success"] is True
        # AudioProcessor was constructed with the openai_client
        mock_cls.assert_called_once_with(vt._openai_client, rate_limit_rpm=3)

    # -- no processor available ---------------------------------------------

    @patch("tasks.video_tasks.update_job_status")
    @patch("tasks.video_tasks._initialize_services")
    def test_no_processor_available(self, mock_init, mock_update):
        """When neither VideoProcessor nor OpenAI client exist, return error."""
        import tasks.video_tasks as vt

        vt._video_processor = None
        vt._openai_client = None

        with patch(_SETTINGS_PATCH_TARGET) as mock_settings:
            mock_settings.azure.whisper_backend = "azure"

            result = vt.transcribe_audio_task.__wrapped__("/tmp/video.mp4", "job-7")

        assert result["success"] is False
        assert "not available" in result["error"]
        assert result["whisper_backend"] == "azure"
        assert result["chunked"] is False
        assert result["chunk_count"] == 0
        assert result["parallel_transcription"] is False

    # -- error handling preserves metadata ----------------------------------

    @patch("tasks.video_tasks.update_job_status")
    @patch("tasks.video_tasks._initialize_services")
    def test_exception_preserves_metadata(self, mock_init, mock_update):
        """On exception, return includes whisper_backend and error details."""
        import tasks.video_tasks as vt

        _attach_video_processor(
            vt,
            _setup_audio_proc(extract_side_effect=RuntimeError("ffmpeg boom")),
        )
        mock_update.delay = MagicMock()

        with patch(_SETTINGS_PATCH_TARGET) as mock_settings:
            mock_settings.azure.whisper_backend = "azure"
            mock_settings.azure.openai_whisper_rpm = 3

            result = vt.transcribe_audio_task.__wrapped__("/tmp/video.mp4", "job-8")

        assert result["success"] is False
        assert "ffmpeg boom" in result["error"]
        assert result["whisper_backend"] == "azure"
        assert result["chunked"] is False
        assert result["parallel_transcription"] is False

    # -- short transcription skips analysis ---------------------------------

    @patch("tasks.video_tasks.update_job_status")
    @patch("tasks.video_tasks._initialize_services")
    def test_short_transcription_skips_analysis(self, mock_init, mock_update):
        """Transcription < 50 chars skips GPT analysis; no analyse progress update."""
        import tasks.video_tasks as vt

        audio_proc = _setup_audio_proc(
            transcription=_make_transcription(text="Hi"),
        )
        _attach_video_processor(vt, audio_proc)
        mock_update.delay = MagicMock()

        with patch(_SETTINGS_PATCH_TARGET) as mock_settings:
            mock_settings.azure.whisper_backend = "azure"
            mock_settings.azure.openai_whisper_rpm = 3

            result = vt.transcribe_audio_task.__wrapped__("/tmp/video.mp4", "job-9")

        assert result["success"] is True
        assert result["analysis"] == {}
        audio_proc.analyze_transcription.assert_not_called()

        messages = _collect_progress_messages(mock_update)
        assert not any("Analyzing transcription" in m for m in messages)

    # -- return shape compat: downstream fields still present ---------------

    @patch("tasks.video_tasks.update_job_status")
    @patch("tasks.video_tasks._initialize_services")
    def test_return_shape_compatible(self, mock_init, mock_update):
        """Return dict has all fields consumed by process_video_pipeline."""
        import tasks.video_tasks as vt

        _attach_video_processor(
            vt, _setup_audio_proc(transcription=_make_transcription(text="Short"))
        )
        mock_update.delay = MagicMock()

        with patch(_SETTINGS_PATCH_TARGET) as mock_settings:
            mock_settings.azure.whisper_backend = "azure"
            mock_settings.azure.openai_whisper_rpm = 3

            result = vt.transcribe_audio_task.__wrapped__("/tmp/video.mp4", "job-10")

        # Fields used by the orchestrator pipeline
        assert "transcription" in result
        assert "success" in result
        assert "error" in result

        transcription = result["transcription"]
        assert "text" in transcription
        assert "language" in transcription
        assert "duration" in transcription
        assert "segments" in transcription
        assert "words" in transcription
