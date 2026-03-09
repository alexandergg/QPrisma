"""
Tests for parallel audio chunk transcription.

Verifies that the AudioProcessor correctly parallelizes transcription of
audio chunks using asyncio.gather with semaphore-bounded concurrency.
"""

import asyncio
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from services.audio_processor import AudioProcessor

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_chunk(index: int, start: float, end: float) -> dict[str, Any]:
    """Create a fake chunk metadata dict (no real file needed)."""
    return {
        "path": f"/tmp/fake_chunk_{index:03d}.mp3",
        "start_time": start,
        "end_time": end,
        "index": index,
        "size_mb": 3.0,
    }


def _make_transcription_result(
    text: str,
    language: str = "en",
    duration: float = 60.0,
) -> dict[str, Any]:
    """Build a minimal Whisper-style transcription result dict."""
    return {
        "text": text,
        "language": language,
        "duration": duration,
        "segments": [{"start": 0.0, "end": duration, "text": text}],
        "words": [{"word": w, "start": 0.0, "end": 1.0} for w in text.split()],
    }


def _build_processor(
    max_concurrent: int = 3,
    whisper_rpm: int = 3,
) -> AudioProcessor:
    """Build an AudioProcessor with a mocked OpenAI client and patched settings."""
    mock_client = AsyncMock()
    with patch("services.audio_processor.settings") as mock_settings:
        mock_settings.azure.openai_deployment_whisper = "whisper"
        mock_settings.azure.openai_deployment_gpt = "gpt-4o"
        mock_settings.azure.openai_whisper_rpm = whisper_rpm
        mock_settings.azure.max_concurrent_transcriptions = max_concurrent
        processor = AudioProcessor(mock_client, rate_limit_rpm=whisper_rpm)
    return processor


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestTranscribeChunksParallel:
    """Tests for _transcribe_chunks_parallel."""

    @pytest.mark.asyncio
    async def test_all_chunks_succeed(self):
        """All chunks transcribed successfully, results in correct order."""
        processor = _build_processor()
        chunks = [_make_chunk(i, i * 60.0, (i + 1) * 60.0) for i in range(4)]
        expected_texts = [f"chunk {i} text" for i in range(4)]

        async def _fake_transcribe(path, lang, fmt, gran, *, time_offset=0):
            idx = int(path.split("_")[-1].replace(".mp3", ""))
            return _make_transcription_result(expected_texts[idx])

        with patch.object(processor, "_transcribe_single_file", side_effect=_fake_transcribe):
            results = await processor._transcribe_chunks_parallel(
                chunks, "en", "verbose_json", ["segment", "word"]
            )

        assert len(results) == 4
        for i, result in enumerate(results):
            assert not isinstance(result, BaseException)
            assert result["text"] == expected_texts[i]

    @pytest.mark.asyncio
    async def test_partial_failure_returns_exceptions(self):
        """Failed chunks appear as exceptions; successful ones are preserved."""
        processor = _build_processor()
        chunks = [_make_chunk(i, i * 60.0, (i + 1) * 60.0) for i in range(3)]

        call_count = 0

        async def _fake_transcribe(path, lang, fmt, gran, *, time_offset=0):
            nonlocal call_count
            idx = call_count
            call_count += 1
            if idx == 1:
                raise RuntimeError("API timeout on chunk 1")
            return _make_transcription_result(f"text {idx}")

        with patch.object(processor, "_transcribe_single_file", side_effect=_fake_transcribe):
            results = await processor._transcribe_chunks_parallel(
                chunks, None, "verbose_json", ["segment"]
            )

        assert len(results) == 3
        # Chunk 0 and 2 succeeded
        assert not isinstance(results[0], BaseException)
        assert not isinstance(results[2], BaseException)
        # Chunk 1 failed
        assert isinstance(results[1], RuntimeError)
        assert "chunk 1" in str(results[1])

    @pytest.mark.asyncio
    async def test_single_chunk_identical_to_sequential(self):
        """With 1 chunk, behavior is identical to old sequential path."""
        processor = _build_processor(max_concurrent=1)
        chunks = [_make_chunk(0, 0.0, 120.0)]
        expected = _make_transcription_result("only chunk")

        with patch.object(processor, "_transcribe_single_file", return_value=expected) as mock_tsf:
            results = await processor._transcribe_chunks_parallel(
                chunks, "es", "verbose_json", ["segment", "word"]
            )

        assert len(results) == 1
        assert results[0] == expected
        mock_tsf.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_preserves_order(self):
        """Result order matches input chunk order regardless of completion order."""
        processor = _build_processor(max_concurrent=5)
        chunks = [_make_chunk(i, i * 30.0, (i + 1) * 30.0) for i in range(5)]

        # Chunks complete in reverse order (chunk 4 finishes first, chunk 0 last)
        async def _variable_delay_transcribe(path, lang, fmt, gran, *, time_offset=0):
            idx = int(path.split("_")[-1].replace(".mp3", ""))
            await asyncio.sleep(0.01 * (5 - idx))  # reverse delay
            return _make_transcription_result(f"result_{idx}")

        with patch.object(
            processor, "_transcribe_single_file", side_effect=_variable_delay_transcribe
        ):
            results = await processor._transcribe_chunks_parallel(
                chunks, None, "verbose_json", ["segment"]
            )

        for i, result in enumerate(results):
            assert result["text"] == f"result_{i}"

    @pytest.mark.asyncio
    async def test_semaphore_limits_concurrency(self):
        """At most ``max_concurrent_transcriptions`` tasks run simultaneously."""
        max_concurrent = 2
        processor = _build_processor(max_concurrent=max_concurrent)
        chunks = [_make_chunk(i, i * 60.0, (i + 1) * 60.0) for i in range(6)]

        peak_concurrent = 0
        current_concurrent = 0
        lock = asyncio.Lock()

        async def _tracking_transcribe(path, lang, fmt, gran, *, time_offset=0):
            nonlocal peak_concurrent, current_concurrent
            async with lock:
                current_concurrent += 1
                peak_concurrent = max(peak_concurrent, current_concurrent)
            try:
                await asyncio.sleep(0.02)
                return _make_transcription_result("text")
            finally:
                async with lock:
                    current_concurrent -= 1

        with patch.object(processor, "_transcribe_single_file", side_effect=_tracking_transcribe):
            await processor._transcribe_chunks_parallel(chunks, None, "verbose_json", ["segment"])

        assert peak_concurrent <= max_concurrent

    @pytest.mark.asyncio
    async def test_all_chunks_fail(self):
        """When every chunk fails, results are all exceptions."""
        processor = _build_processor()
        chunks = [_make_chunk(i, i * 60.0, (i + 1) * 60.0) for i in range(3)]

        async def _always_fail(path, lang, fmt, gran, *, time_offset=0):
            raise ConnectionError("service down")

        with patch.object(processor, "_transcribe_single_file", side_effect=_always_fail):
            results = await processor._transcribe_chunks_parallel(
                chunks, None, "verbose_json", ["segment"]
            )

        assert all(isinstance(r, ConnectionError) for r in results)


class TestTranscribeWithChunking:
    """Integration-level tests for _transcribe_with_chunking."""

    @pytest.mark.asyncio
    async def test_combines_results_correctly(self):
        """Successful chunks are merged into a single combined result."""
        processor = _build_processor()
        chunks = [
            _make_chunk(0, 0.0, 60.0),
            _make_chunk(1, 60.0, 120.0),
            _make_chunk(2, 120.0, 180.0),
        ]

        results = [
            _make_transcription_result("Hello world", duration=60.0),
            _make_transcription_result("How are you", duration=60.0),
            _make_transcription_result("Goodbye", duration=60.0),
        ]

        with (
            patch.object(processor, "split_audio_into_chunks", return_value=chunks),
            patch.object(processor, "_transcribe_chunks_parallel", return_value=results),
            patch("services.audio_processor.settings") as mock_settings,
        ):
            mock_settings.azure.max_concurrent_transcriptions = 3
            combined = await processor._transcribe_with_chunking(
                "/tmp/audio.mp3", "en", "verbose_json", ["segment", "word"]
            )

        assert combined["text"] == "Hello world How are you Goodbye"
        assert combined["chunked"] is True
        assert combined["chunk_count"] == 3
        assert len(combined["segments"]) == 3
        assert combined["language"] == "en"

    @pytest.mark.asyncio
    async def test_partial_failure_returns_partial_results(self):
        """When some chunks fail, the combined result contains only the successes."""
        processor = _build_processor()
        chunks = [
            _make_chunk(0, 0.0, 60.0),
            _make_chunk(1, 60.0, 120.0),
            _make_chunk(2, 120.0, 180.0),
        ]

        results = [
            _make_transcription_result("First part"),
            RuntimeError("API error"),  # chunk 1 failed
            _make_transcription_result("Third part"),
        ]

        with (
            patch.object(processor, "split_audio_into_chunks", return_value=chunks),
            patch.object(processor, "_transcribe_chunks_parallel", return_value=results),
            patch("services.audio_processor.settings") as mock_settings,
            patch("os.path.exists", return_value=False),
        ):
            mock_settings.azure.max_concurrent_transcriptions = 3
            combined = await processor._transcribe_with_chunking(
                "/tmp/audio.mp3", None, "verbose_json", ["segment"]
            )

        assert "First part" in combined["text"]
        assert "Third part" in combined["text"]
        assert combined["chunk_count"] == 3
        # Only 2 chunks contributed segments
        assert len(combined["segments"]) == 2

    @pytest.mark.asyncio
    async def test_all_failures_returns_empty(self):
        """When every chunk fails, result is an empty combined transcription."""
        processor = _build_processor()
        chunks = [_make_chunk(0, 0.0, 60.0), _make_chunk(1, 60.0, 120.0)]

        results = [
            RuntimeError("fail 0"),
            RuntimeError("fail 1"),
        ]

        with (
            patch.object(processor, "split_audio_into_chunks", return_value=chunks),
            patch.object(processor, "_transcribe_chunks_parallel", return_value=results),
            patch("services.audio_processor.settings") as mock_settings,
            patch("os.path.exists", return_value=False),
        ):
            mock_settings.azure.max_concurrent_transcriptions = 3
            combined = await processor._transcribe_with_chunking(
                "/tmp/audio.mp3", None, "verbose_json", ["segment"]
            )

        assert combined["text"] == ""
        assert combined["segments"] == []
        assert combined["words"] == []
        assert combined["chunked"] is True

    @pytest.mark.asyncio
    async def test_cleanup_temp_files(self):
        """Temporary chunk files are unlinked after parallel transcription."""
        processor = _build_processor()
        chunks = [_make_chunk(0, 0.0, 60.0), _make_chunk(1, 60.0, 120.0)]
        results = [
            _make_transcription_result("a"),
            _make_transcription_result("b"),
        ]

        with (
            patch.object(processor, "split_audio_into_chunks", return_value=chunks),
            patch.object(processor, "_transcribe_chunks_parallel", return_value=results),
            patch("services.audio_processor.settings") as mock_settings,
            patch("os.path.exists", return_value=True),
            patch("os.unlink") as mock_unlink,
        ):
            mock_settings.azure.max_concurrent_transcriptions = 3
            await processor._transcribe_with_chunking(
                "/tmp/audio.mp3", None, "verbose_json", ["segment"]
            )

        # Both chunk files should be cleaned up
        assert mock_unlink.call_count == 2

    @pytest.mark.asyncio
    async def test_no_cleanup_for_original_file(self):
        """The original audio file is never deleted (only temp chunk files)."""
        processor = _build_processor()
        audio_path = "/tmp/audio.mp3"
        # Chunk 0 has path == audio_path (single-chunk scenario from split)
        chunks = [{"path": audio_path, "start_time": 0, "end_time": 120.0, "index": 0}]
        results = [_make_transcription_result("full")]

        with (
            patch.object(processor, "split_audio_into_chunks", return_value=chunks),
            patch.object(processor, "_transcribe_chunks_parallel", return_value=results),
            patch("services.audio_processor.settings") as mock_settings,
            patch("os.path.exists", return_value=True),
            patch("os.unlink") as mock_unlink,
        ):
            mock_settings.azure.max_concurrent_transcriptions = 3
            await processor._transcribe_with_chunking(audio_path, None, "verbose_json", ["segment"])

        mock_unlink.assert_not_called()


class TestConfigConcurrency:
    """Verify the config setting is wired correctly."""

    def test_default_max_concurrent_transcriptions(self):
        """Default concurrency matches Azure Whisper RPM limit."""
        from core.config import AzureSettings

        s = AzureSettings()
        assert s.max_concurrent_transcriptions == 3

    def test_custom_max_concurrent_transcriptions(self):
        """Setting can be overridden via env var."""
        from core.config import AzureSettings

        s = AzureSettings(max_concurrent_transcriptions=5)
        assert s.max_concurrent_transcriptions == 5

    def test_semaphore_uses_config_value(self):
        """AudioProcessor creates semaphore from settings value."""
        processor = _build_processor(max_concurrent=5)
        # asyncio.Semaphore stores initial value as _value
        assert processor._transcription_semaphore._value == 5
