"""
Hardware Acceleration Resolver

Detects and resolves FFmpeg hardware acceleration capabilities.
"""

import logging
import subprocess

logger = logging.getLogger(__name__)


class HardwareAccelerationResolver:
    """Detect and resolve FFmpeg hardware acceleration capabilities."""

    # Cached result of hardware acceleration detection
    _hwaccel_available: str | None = None
    _hwaccel_checked: bool = False

    @staticmethod
    def detect_available() -> str | None:
        """
        Auto-detect available hardware acceleration using FFmpeg.

        Returns the best available hwaccel method, or None if only CPU is available.
        Priority: cuda > qsv > d3d11va > dxva2 > vaapi > videotoolbox
        """
        if HardwareAccelerationResolver._hwaccel_checked:
            return HardwareAccelerationResolver._hwaccel_available

        # Preferred order by decode performance
        preferred = ["cuda", "qsv", "d3d11va", "dxva2", "vaapi", "videotoolbox"]

        try:
            result = subprocess.run(
                ["ffmpeg", "-hwaccels"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            available = result.stdout.lower().split()
            for method in preferred:
                if method in available:
                    HardwareAccelerationResolver._hwaccel_available = method
                    HardwareAccelerationResolver._hwaccel_checked = True
                    logger.info(f"Hardware acceleration detected: {method}")
                    return method
        except Exception as e:
            logger.debug(f"Hardware acceleration detection failed: {e}")

        HardwareAccelerationResolver._hwaccel_available = None
        HardwareAccelerationResolver._hwaccel_checked = True
        logger.info("No hardware acceleration available, using CPU decoding")
        return None

    @staticmethod
    def resolve(preferred: str | None) -> str | None:
        """Resolve hardware acceleration: use config value, auto-detect, or None."""
        if preferred == "auto":
            return HardwareAccelerationResolver.detect_available()
        elif preferred:
            return preferred
        return None

    @staticmethod
    def build_args(hwaccel: str | None) -> list[str]:
        """Build FFmpeg hardware acceleration arguments (inserted before -i)."""
        if not hwaccel:
            return []
        return ["-hwaccel", hwaccel]
