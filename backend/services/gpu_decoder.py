"""GPU-accelerated video decoder using NVIDIA PyNvVideoCodec.

This module provides a GPU-accelerated :class:`VideoDecoder` implementation
that leverages NVIDIA's hardware video decoder (NVDEC) for 10-50×
faster frame extraction compared to CPU decoding.

Requirements:
    - NVIDIA GPU with NVDEC support (Kepler or newer)
    - ``pip install 'qprisma-backend[gpu]'``
    - CUDA toolkit installed and on ``PATH``

Usage::

    from services.gpu_decoder import NvVideoCodecDecoder

    decoder = NvVideoCodecDecoder()
    if decoder.is_available:
        info = await decoder.get_video_info("video.mp4")
"""

from __future__ import annotations

import logging
from typing import Any

from services.video_decoder import ExtractedFrame, VideoInfo

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lazy dependency check — never crashes on import
# ---------------------------------------------------------------------------

_nvcodec_available = False
try:
    import PyNvVideoCodec  # noqa: F401

    _nvcodec_available = True
except ImportError:
    pass


def is_gpu_decoder_available() -> bool:
    """Check if GPU decoder dependencies are installed."""
    return _nvcodec_available


# ---------------------------------------------------------------------------
# NvVideoCodecDecoder
# ---------------------------------------------------------------------------


class NvVideoCodecDecoder:
    """GPU-accelerated video decoder using NVIDIA NVDEC.

    Implements the :class:`~services.video_decoder.VideoDecoder` protocol
    for hardware-accelerated video decoding.  Falls back gracefully when
    GPU hardware or the ``PyNvVideoCodec`` package is unavailable.

    Performance characteristics:

    * 10-50× faster than CPU decoding for 4K content
    * Direct GPU memory → avoids CPU-GPU transfer overhead
    * Supports H.264, H.265/HEVC, VP9, AV1

    This is currently a **stub** — the interface is defined and the class
    passes protocol conformance checks, but actual GPU decode raises
    :class:`NotImplementedError` until ``PyNvVideoCodec ≥ 2.1`` is
    available on PyPI.
    """

    def __init__(self) -> None:
        self._decoder: Any = None

    # -- Protocol properties -------------------------------------------------

    @property
    def name(self) -> str:
        return "nvvideocodec"

    @property
    def is_available(self) -> bool:
        return _nvcodec_available

    # -- Protocol methods ----------------------------------------------------

    async def get_video_info(self, video_path: str) -> VideoInfo:
        """Get video metadata.

        The GPU decoder itself does not expose container-level metadata,
        so this delegates to the FFmpeg subprocess backend (``ffprobe``)
        which is always available.

        Raises:
            RuntimeError: If ``PyNvVideoCodec`` is not installed.
        """
        if not self.is_available:
            raise RuntimeError(
                "PyNvVideoCodec is not installed. " "Install with: pip install PyNvVideoCodec"
            )
        # Delegate to ffprobe for metadata (GPU decoder doesn't provide this)
        from services.video_decoder import FFmpegSubprocessDecoder

        return await FFmpegSubprocessDecoder().get_video_info(video_path)

    async def extract_frames(
        self,
        video_path: str,
        *,
        timestamps: list[float] | None = None,
        max_frames: int = 0,
        interval_seconds: float = 0,
        start_time: float = 0,
        end_time: float = 0,
    ) -> list[ExtractedFrame]:
        """Extract frames using GPU hardware decoder.

        .. note::

            **Stub** — raises :class:`NotImplementedError` with setup
            instructions.  Full implementation requires
            ``PyNvVideoCodec 2.1+`` and the CUDA toolkit.

        Raises:
            RuntimeError: If ``PyNvVideoCodec`` is not installed.
            NotImplementedError: Always (stub).
        """
        if not self.is_available:
            raise RuntimeError(
                "PyNvVideoCodec is not installed. " "Install with: pip install PyNvVideoCodec"
            )
        raise NotImplementedError(
            "NvVideoCodecDecoder.extract_frames() is a stub. "
            "Full implementation requires PyNvVideoCodec 2.1+ and CUDA toolkit. "
            "Use PyAVDecoder as the primary CPU decoder."
        )
