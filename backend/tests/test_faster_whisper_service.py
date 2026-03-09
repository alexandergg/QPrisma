"""
Tests for services/faster_whisper_service.py

Covers:
- Model lazy loading
- Transcribe returns expected format
- Chunk transcription
- Graceful handling when library not installed
- Config integration (AzureSettings fields)
- Dependency singleton in api/dependencies.py
"""

import types
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers — build mock objects that mimic faster-whisper types
# ---------------------------------------------------------------------------


def _fake_segment(start: float, end: float, text: str):
    """Return an object that looks like a faster-whisper Segment."""
    seg = MagicMock()
    seg.start = start
    seg.end = end
    seg.text = f" {text} "  # leading/trailing space like real Whisper
    return seg


def _fake_info(language: str = "en", probability: float = 0.97, duration: float = 120.0):
    """Return an object that looks like faster-whisper TranscriptionInfo."""
    info = MagicMock()
    info.language = language
    info.language_probability = probability
    info.duration = duration
    return info


# ===========================================================================
# Unit tests — faster_whisper IS available (mocked)
# ===========================================================================


@pytest.mark.unit
class TestFasterWhisperTranscriber:
    """Tests with the faster-whisper library mocked as available."""

    @pytest.fixture(autouse=True)
    def _patch_faster_whisper(self):
        """Patch the faster-whisper imports so the service thinks the lib is present."""
        mock_model_cls = MagicMock(name="WhisperModel")
        mock_pipeline_cls = MagicMock(name="BatchedInferencePipeline")

        fake_module = types.ModuleType("faster_whisper")
        fake_module.WhisperModel = mock_model_cls
        fake_module.BatchedInferencePipeline = mock_pipeline_cls

        with patch.dict("sys.modules", {"faster_whisper": fake_module}):
            # Re-import so module-level try/except picks up the fake
            import services.faster_whisper_service as mod

            mod._faster_whisper_available = True
            mod.WhisperModel = mock_model_cls
            mod.BatchedInferencePipeline = mock_pipeline_cls

            self.mod = mod
            self.mock_model_cls = mock_model_cls
            self.mock_pipeline_cls = mock_pipeline_cls
            yield

    # ----- lazy loading -----

    def test_init_does_not_load_model(self):
        """Instantiation must NOT trigger model loading."""
        t = self.mod.FasterWhisperTranscriber()
        assert t._model is None
        assert t._pipeline is None
        self.mock_model_cls.assert_not_called()

    def test_ensure_model_loads_once(self):
        t = self.mod.FasterWhisperTranscriber(
            model_size="small", device="cpu", compute_type="float32"
        )
        t._ensure_model()

        self.mock_model_cls.assert_called_once_with("small", device="cpu", compute_type="float32")
        self.mock_pipeline_cls.assert_called_once_with(model=t._model)

        # Second call is a no-op
        t._ensure_model()
        assert self.mock_model_cls.call_count == 1

    # ----- transcribe -----

    async def test_transcribe_returns_expected_keys(self):
        t = self.mod.FasterWhisperTranscriber(model_size="tiny", device="cpu")

        # Wire up the pipeline mock
        segments = [
            _fake_segment(0.0, 5.0, "Hello world"),
            _fake_segment(5.0, 10.0, "Goodbye world"),
        ]
        info = _fake_info(language="en", probability=0.95, duration=10.0)
        t._model = MagicMock()
        t._pipeline = MagicMock()
        t._pipeline.transcribe.return_value = (iter(segments), info)

        result = await t.transcribe("/tmp/audio.mp3", language="en")

        assert set(result.keys()) == {
            "text",
            "segments",
            "language",
            "language_probability",
            "duration",
        }
        assert result["text"] == "Hello world Goodbye world"
        assert result["language"] == "en"
        assert result["language_probability"] == 0.95
        assert result["duration"] == 10.0
        assert len(result["segments"]) == 2
        assert result["segments"][0]["start"] == 0.0
        assert result["segments"][1]["text"] == "Goodbye world"

    async def test_transcribe_passes_vad_params(self):
        t = self.mod.FasterWhisperTranscriber(batch_size=8)
        t._model = MagicMock()
        t._pipeline = MagicMock()
        t._pipeline.transcribe.return_value = (iter([]), _fake_info(duration=0.0))

        await t.transcribe("/tmp/audio.mp3")

        call_kwargs = t._pipeline.transcribe.call_args
        assert call_kwargs.kwargs["vad_filter"] is True
        assert call_kwargs.kwargs["batch_size"] == 8
        assert call_kwargs.kwargs["vad_parameters"]["min_silence_duration_ms"] == 500

    async def test_transcribe_auto_detects_language(self):
        """When language=None the pipeline should receive language=None."""
        t = self.mod.FasterWhisperTranscriber()
        t._model = MagicMock()
        t._pipeline = MagicMock()
        t._pipeline.transcribe.return_value = (iter([]), _fake_info(language="es"))

        result = await t.transcribe("/tmp/audio.mp3")

        call_kwargs = t._pipeline.transcribe.call_args
        assert call_kwargs.kwargs["language"] is None
        assert result["language"] == "es"

    # ----- transcribe_chunks -----

    async def test_transcribe_chunks_returns_list(self):
        t = self.mod.FasterWhisperTranscriber()
        t._model = MagicMock()
        t._pipeline = MagicMock()

        segs1 = [_fake_segment(0, 5, "chunk one")]
        segs2 = [_fake_segment(0, 3, "chunk two")]

        t._pipeline.transcribe.side_effect = [
            (iter(segs1), _fake_info(duration=5.0)),
            (iter(segs2), _fake_info(duration=3.0)),
        ]

        results = await t.transcribe_chunks(["/tmp/a.mp3", "/tmp/b.mp3"])

        assert len(results) == 2
        assert results[0]["text"] == "chunk one"
        assert results[1]["text"] == "chunk two"

    async def test_transcribe_chunks_handles_partial_failure(self):
        t = self.mod.FasterWhisperTranscriber()
        t._model = MagicMock()
        t._pipeline = MagicMock()

        ok_segs = [_fake_segment(0, 5, "ok")]
        t._pipeline.transcribe.side_effect = [
            (iter(ok_segs), _fake_info(duration=5.0)),
            RuntimeError("GPU OOM"),
        ]

        results = await t.transcribe_chunks(["/tmp/ok.mp3", "/tmp/fail.mp3"])

        assert len(results) == 2
        assert results[0]["text"] == "ok"
        assert results[1]["text"] == ""
        assert "error" in results[1]

    # ----- is_faster_whisper_available -----

    def test_is_available_returns_true_when_patched(self):
        assert self.mod.is_faster_whisper_available() is True


# ===========================================================================
# Unit tests — faster_whisper NOT available
# ===========================================================================


@pytest.mark.unit
class TestFasterWhisperNotInstalled:
    """Tests when faster-whisper is genuinely missing."""

    def test_instantiation_raises_runtime_error(self):
        import services.faster_whisper_service as mod

        original = mod._faster_whisper_available
        try:
            mod._faster_whisper_available = False
            with pytest.raises(RuntimeError, match="faster-whisper is not installed"):
                mod.FasterWhisperTranscriber()
        finally:
            mod._faster_whisper_available = original

    def test_is_available_returns_false(self):
        import services.faster_whisper_service as mod

        original = mod._faster_whisper_available
        try:
            mod._faster_whisper_available = False
            assert mod.is_faster_whisper_available() is False
        finally:
            mod._faster_whisper_available = original


# ===========================================================================
# Config integration
# ===========================================================================


@pytest.mark.unit
class TestFasterWhisperConfig:
    """Verify the new AzureSettings fields."""

    def test_default_whisper_backend_is_azure(self):
        from core.config import AzureSettings

        s = AzureSettings()
        assert s.whisper_backend == "azure"

    def test_faster_whisper_defaults(self):
        from core.config import AzureSettings

        s = AzureSettings()
        assert s.faster_whisper_model == "large-v3"
        assert s.faster_whisper_device == "auto"
        assert s.faster_whisper_compute_type == "int8"
        assert s.faster_whisper_batch_size == 16

    def test_custom_faster_whisper_config(self):
        from core.config import AzureSettings

        s = AzureSettings(
            whisper_backend="faster_whisper",
            faster_whisper_model="medium",
            faster_whisper_device="cuda",
            faster_whisper_compute_type="float16",
            faster_whisper_batch_size=32,
        )
        assert s.whisper_backend == "faster_whisper"
        assert s.faster_whisper_model == "medium"
        assert s.faster_whisper_device == "cuda"
        assert s.faster_whisper_compute_type == "float16"
        assert s.faster_whisper_batch_size == 32


# ===========================================================================
# Dependency singleton
# ===========================================================================


@pytest.mark.unit
class TestFasterWhisperDependency:
    """Tests for get_faster_whisper_transcriber in api/dependencies.py."""

    def test_returns_none_when_backend_is_azure(self):
        import api.dependencies as deps

        deps._faster_whisper_transcriber = None

        with patch.object(deps.settings.azure, "whisper_backend", "azure"):
            result = deps.get_faster_whisper_transcriber()

        assert result is None

    def test_returns_none_when_lib_not_installed(self):
        import api.dependencies as deps

        deps._faster_whisper_transcriber = None

        with (
            patch.object(deps.settings.azure, "whisper_backend", "faster_whisper"),
            patch(
                "services.faster_whisper_service.is_faster_whisper_available",
                return_value=False,
            ),
        ):
            result = deps.get_faster_whisper_transcriber()

        assert result is None

    def test_returns_transcriber_when_configured(self):
        import api.dependencies as deps

        deps._faster_whisper_transcriber = None

        mock_transcriber = MagicMock()
        mock_cls = MagicMock(return_value=mock_transcriber)

        with (
            patch.object(deps.settings.azure, "whisper_backend", "faster_whisper"),
            patch(
                "services.faster_whisper_service.is_faster_whisper_available",
                return_value=True,
            ),
            patch(
                "services.faster_whisper_service.FasterWhisperTranscriber",
                mock_cls,
            ),
        ):
            result = deps.get_faster_whisper_transcriber()

        assert result is mock_transcriber
        mock_cls.assert_called_once()

    def test_singleton_caches_instance(self):
        import api.dependencies as deps

        sentinel = MagicMock()
        deps._faster_whisper_transcriber = sentinel

        result = deps.get_faster_whisper_transcriber()
        assert result is sentinel

        # Cleanup
        deps._faster_whisper_transcriber = None


# ===========================================================================
# AudioProcessor integration branch
# ===========================================================================


@pytest.mark.unit
class TestAudioProcessorFasterWhisperBranch:
    """Verify the conditional branch in AudioProcessor.transcribe_audio."""

    async def test_uses_faster_whisper_when_configured(self):
        from services.audio_processor import AudioProcessor

        mock_client = MagicMock()

        with patch("services.audio_processor.settings") as mock_settings:
            mock_settings.azure.whisper_backend = "faster_whisper"
            mock_settings.azure.faster_whisper_model = "small"
            mock_settings.azure.faster_whisper_device = "cpu"
            mock_settings.azure.faster_whisper_compute_type = "int8"
            mock_settings.azure.faster_whisper_batch_size = 8
            mock_settings.azure.openai_deployment_whisper = "whisper"
            mock_settings.azure.openai_deployment_gpt = "gpt-4o"
            mock_settings.azure.max_concurrent_transcriptions = 3

            processor = AudioProcessor(mock_client)

        expected = {
            "text": "hello",
            "segments": [],
            "language": "en",
            "language_probability": 0.99,
            "duration": 5.0,
        }

        with (
            patch("services.audio_processor.settings") as mock_settings,
            patch("services.faster_whisper_service.FasterWhisperTranscriber") as mock_cls,
        ):
            mock_settings.azure.whisper_backend = "faster_whisper"
            mock_settings.azure.faster_whisper_model = "small"
            mock_settings.azure.faster_whisper_device = "cpu"
            mock_settings.azure.faster_whisper_compute_type = "int8"
            mock_settings.azure.faster_whisper_batch_size = 8

            mock_instance = MagicMock()
            mock_instance.transcribe = MagicMock(return_value=expected)
            # Make transcribe awaitable

            async def _fake_transcribe(path, language=None):
                return expected

            mock_instance.transcribe = _fake_transcribe
            mock_cls.return_value = mock_instance

            result = await processor.transcribe_audio("/tmp/audio.mp3", language="en")

        assert result == expected
        mock_cls.assert_called_once_with(
            model_size="small",
            device="cpu",
            compute_type="int8",
            batch_size=8,
        )

    async def test_falls_back_to_azure_by_default(self):
        """When whisper_backend == 'azure', the Azure API path is used."""
        from unittest.mock import AsyncMock

        from services.audio_processor import AudioProcessor

        mock_client = AsyncMock()
        mock_transcription = MagicMock()
        mock_transcription.model_dump.return_value = {
            "text": "azure result",
            "language": "en",
            "duration": 10.0,
            "segments": [],
            "words": [],
        }
        mock_client.audio.transcriptions.create.return_value = mock_transcription

        with patch("services.audio_processor.settings") as mock_settings:
            mock_settings.azure.whisper_backend = "azure"
            mock_settings.azure.openai_deployment_whisper = "whisper"
            mock_settings.azure.openai_deployment_gpt = "gpt-4o"
            mock_settings.azure.max_concurrent_transcriptions = 3

            processor = AudioProcessor(mock_client)

        with (
            patch("services.audio_processor.settings") as mock_settings,
            patch("os.path.getsize", return_value=5 * 1024 * 1024),  # 5MB
        ):
            mock_settings.azure.whisper_backend = "azure"

            result = await processor.transcribe_audio("/tmp/audio.mp3")

        assert result["text"] == "azure result"
