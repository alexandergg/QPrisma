"""faster-whisper transcription backend for QPrisma.

Provides 4x faster local transcription with INT8 quantization,
batched inference, and built-in Silero VAD.  Falls back gracefully
when the library isn't installed.

Install the optional dependency group to enable:

    pip install 'qprisma-backend[gpu]'
"""

import asyncio
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

_faster_whisper_available = False
try:
    from faster_whisper import BatchedInferencePipeline, WhisperModel

    _faster_whisper_available = True
except ImportError:
    pass


def is_faster_whisper_available() -> bool:
    """Return *True* when the faster-whisper package is importable."""
    return _faster_whisper_available


class FasterWhisperTranscriber:
    """Local Whisper transcription using CTranslate2.

    The heavy model is **lazy-loaded** on first ``transcribe()`` call so
    instantiation is cheap and safe to use in a singleton pattern.

    Parameters
    ----------
    model_size:
        Model identifier (e.g. ``"large-v3"``, ``"medium"``, ``"small"``).
    device:
        ``"auto"`` | ``"cpu"`` | ``"cuda"``.
    compute_type:
        ``"int8"`` | ``"float16"`` | ``"float32"``.
    batch_size:
        Batch size forwarded to :class:`BatchedInferencePipeline`.
    """

    def __init__(
        self,
        model_size: str = "large-v3",
        device: str = "auto",
        compute_type: str = "int8",
        batch_size: int = 16,
    ):
        if not _faster_whisper_available:
            raise RuntimeError(
                "faster-whisper is not installed. "
                "Install with: pip install 'qprisma-backend[gpu]'"
            )
        self._model_size = model_size
        self._device = device
        self._compute_type = compute_type
        self._batch_size = batch_size
        self._model: Any = None
        self._pipeline: Any = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_model(self) -> None:
        """Lazy-load the model on first use."""
        if self._model is not None:
            return

        logger.info(
            "Loading faster-whisper model: %s (device=%s, compute=%s)",
            self._model_size,
            self._device,
            self._compute_type,
        )
        load_start = time.perf_counter()
        self._model = WhisperModel(
            self._model_size,
            device=self._device,
            compute_type=self._compute_type,
        )
        self._pipeline = BatchedInferencePipeline(model=self._model)
        elapsed = time.perf_counter() - load_start
        logger.info("faster-whisper model loaded in %.2fs", elapsed)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def transcribe(
        self,
        audio_path: str,
        language: str | None = None,
    ) -> dict[str, Any]:
        """Transcribe an audio file using faster-whisper.

        The heavy inference runs in a thread-pool via
        :func:`asyncio.to_thread` so the event loop stays unblocked.

        Returns
        -------
        dict
            Keys: ``text``, ``segments``, ``language``,
            ``language_probability``, ``duration``.
        """

        def _do_transcribe() -> dict[str, Any]:
            self._ensure_model()

            t0 = time.perf_counter()
            segments_iter, info = self._pipeline.transcribe(
                audio_path,
                language=language,
                batch_size=self._batch_size,
                vad_filter=True,  # built-in Silero VAD
                vad_parameters={
                    "min_silence_duration_ms": 500,
                    "speech_pad_ms": 200,
                },
            )

            result_segments: list[dict[str, Any]] = []
            full_text_parts: list[str] = []

            for seg in segments_iter:
                text = seg.text.strip()
                result_segments.append(
                    {
                        "start": seg.start,
                        "end": seg.end,
                        "text": text,
                    }
                )
                full_text_parts.append(text)

            elapsed = time.perf_counter() - t0
            logger.info(
                "faster-whisper transcribed %.1fs audio in %.2fs " "(%d segments, lang=%s)",
                info.duration,
                elapsed,
                len(result_segments),
                info.language,
            )

            return {
                "text": " ".join(full_text_parts),
                "segments": result_segments,
                "language": info.language,
                "language_probability": info.language_probability,
                "duration": info.duration,
            }

        return await asyncio.to_thread(_do_transcribe)

    async def transcribe_chunks(
        self,
        chunk_paths: list[str],
        language: str | None = None,
    ) -> list[dict[str, Any]]:
        """Transcribe multiple audio chunks sequentially.

        Unlike the Azure API path which fans out parallel HTTP calls,
        faster-whisper already handles batching internally so sequential
        invocation per file avoids GPU contention.
        """
        results: list[dict[str, Any]] = []
        for path in chunk_paths:
            try:
                result = await self.transcribe(path, language=language)
                results.append(result)
            except Exception:
                logger.exception("Failed to transcribe chunk: %s", path)
                results.append({"text": "", "segments": [], "error": f"Failed: {path}"})
        return results
