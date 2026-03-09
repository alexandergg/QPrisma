"""
FFmpeg Video Processor
Ultra-fast video processing system with FFmpeg.
Inspired by Edconv for maximum customization and performance.

Supports two decoder backends:
- ``pyav`` (default): in-process decoding via PyAV for lower latency
- ``ffmpeg_subprocess``: traditional subprocess-based extraction
"""

import asyncio
import base64
import io
import logging
import os
import subprocess
import tempfile
import time
from collections.abc import AsyncIterator
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import ffmpeg
import imagehash
import numpy as np
from PIL import Image

from models.ffmpeg_config import (
    FFmpegProcessingConfig,
    FrameExtractionMethod,
    ProcessingPipeline,
    ProcessingStatus,
)
from services.coverage_analyzer import CoverageAnalyzer
from services.hwaccel_resolver import HardwareAccelerationResolver
from services.scene_detect_service import SceneDetectService, map_ffmpeg_threshold
from services.timestamp_calculator import TimestampCalculator

logger = logging.getLogger(__name__)


def _get_optimal_workers() -> int:
    """Get optimal worker count based on available CPUs.

    Container-aware: uses ``os.sched_getaffinity`` on Linux (respects
    cgroup limits), falls back to ``os.cpu_count`` elsewhere.
    """
    try:
        try:
            cpu_count = len(os.sched_getaffinity(0))
        except AttributeError:
            cpu_count = os.cpu_count() or 4
        return max(2, min(cpu_count - 1, 16))
    except Exception:
        return 4  # Safe default


class FFmpegVideoProcessor:
    """Video processor with FFmpeg for ultra-fast frame extraction"""

    def __init__(self, config: FFmpegProcessingConfig | None = None):
        """
        Initialize processor

        Args:
            config: Processing configuration (None = use defaults)
        """
        self.config = config or FFmpegProcessingConfig()
        self.status = ProcessingStatus(status="pending")
        self._resolved_hwaccel = HardwareAccelerationResolver.resolve(self.config.hardware_accel)

        # Determine decoder backend (pyav | ffmpeg_subprocess)
        self._decoder_backend = self._resolve_decoder_backend()

        # PySceneDetect integration — preferred over FFmpeg scene filter
        self._use_pyscenedetect: bool = True
        self._scene_detect_service = SceneDetectService()

        # Specialist delegates
        self._timestamp_calculator = TimestampCalculator()
        self._coverage_analyzer = CoverageAnalyzer()

    def _resolve_decoder_backend(self) -> str:
        """Pick the decoder backend from config → settings → fallback chain."""
        # 1. Check frame_extraction config on the processing config
        backend = getattr(self.config.frame_extraction, "decoder_backend", None)

        # 2. Fall back to centralised settings
        if not backend:
            try:
                from core.config import get_settings

                backend = get_settings().app.video_decoder_backend
            except Exception:
                backend = None

        backend = backend or "pyav"

        # 3. If pyav is requested but unavailable, fall back silently
        if backend == "pyav":
            try:
                from services.pyav_extractor import is_pyav_available

                if not is_pyav_available():
                    logger.info(
                        "PyAV requested but not installed — falling back to ffmpeg_subprocess"
                    )
                    return "ffmpeg_subprocess"
            except ImportError:
                logger.info("pyav_extractor module not found — falling back to ffmpeg_subprocess")
                return "ffmpeg_subprocess"

        return backend

    @staticmethod
    def _detect_available_hwaccel() -> str | None:
        """Auto-detect available hardware acceleration using FFmpeg.

        Delegates to :class:`HardwareAccelerationResolver`.
        """
        return HardwareAccelerationResolver.detect_available()

    def _resolve_hwaccel(self) -> str | None:
        """Resolve hardware acceleration: use config value, auto-detect, or None."""
        return HardwareAccelerationResolver.resolve(self.config.hardware_accel)

    def _build_hwaccel_args(self) -> list[str]:
        """Build FFmpeg hardware acceleration arguments (inserted before -i)."""
        return HardwareAccelerationResolver.build_args(self._resolved_hwaccel)

    def get_video_info(self, video_path: str) -> dict[str, Any]:
        """
        Get video information using ffprobe

        Args:
            video_path: Path to the video file

        Returns:
            Dictionary with video information
        """
        try:
            probe = ffmpeg.probe(video_path)

            # Find video stream
            video_stream = next((s for s in probe["streams"] if s["codec_type"] == "video"), None)

            if not video_stream:
                raise ValueError("No video stream found")

            # Extract relevant information
            format_info = probe.get("format", {})

            info = {
                "duration": float(format_info.get("duration", 0)),
                "size_bytes": int(format_info.get("size", 0)),
                "bit_rate": int(format_info.get("bit_rate", 0)),
                "format_name": format_info.get("format_name", ""),
                "width": int(video_stream.get("width", 0)),
                "height": int(video_stream.get("height", 0)),
                "codec_name": video_stream.get("codec_name", ""),
                "codec_long_name": video_stream.get("codec_long_name", ""),
                "pix_fmt": video_stream.get("pix_fmt", ""),
                "level": video_stream.get("level"),
                "profile": video_stream.get("profile", ""),
            }

            # Calculate FPS
            r_frame_rate = video_stream.get("r_frame_rate", "0/1")
            if "/" in r_frame_rate:
                num, den = map(int, r_frame_rate.split("/"))
                info["fps"] = num / den if den != 0 else 0
            else:
                info["fps"] = float(r_frame_rate)

            # Calculate estimated frame count
            if info["fps"] > 0 and info["duration"] > 0:
                info["frame_count"] = int(info["fps"] * info["duration"])
            else:
                info["frame_count"] = int(video_stream.get("nb_frames", 0))

            # Aspect ratio
            if "display_aspect_ratio" in video_stream:
                info["aspect_ratio"] = video_stream["display_aspect_ratio"]
            elif info["width"] > 0 and info["height"] > 0:
                from math import gcd

                g = gcd(info["width"], info["height"])
                info["aspect_ratio"] = f"{info['width']//g}:{info['height']//g}"

            return info

        except Exception as e:
            raise RuntimeError(f"Error getting video information: {str(e)}")

    def _build_filter_chain(self, video_info: dict[str, Any]) -> list[str]:
        """
        Build FFmpeg filter chain

        Args:
            video_info: Video information

        Returns:
            List of filters to apply
        """
        filters = []
        vf = self.config.video_filters

        # Crop
        if all(
            [
                vf.crop_x is not None,
                vf.crop_y is not None,
                vf.crop_width is not None,
                vf.crop_height is not None,
            ]
        ):
            filters.append(f"crop={vf.crop_width}:{vf.crop_height}:{vf.crop_x}:{vf.crop_y}")

        # Deinterlace
        if vf.deinterlace:
            filters.append("yadif")

        # HDR to SDR
        if vf.hdr_to_sdr:
            filters.append(
                "zscale=t=linear:npl=100,format=gbrpf32le,"
                "tonemap=hable:desat=0,"
                "zscale=t=bt709:m=bt709:p=bt709:r=tv"
            )

        # Scale
        if vf.scale_width or vf.scale_height:
            w = vf.scale_width or -1
            h = vf.scale_height or -1
            scale_filter = f"scale={w}:{h}"

            # Add scaling algorithm
            if vf.scaling_filter:
                scale_filter += f":flags={vf.scaling_filter.value}"

            filters.append(scale_filter)

        # Pixel format
        if vf.pixel_format:
            filters.append(f"format={vf.pixel_format.value}")

        # Color adjustments
        eq_params = []
        if vf.brightness is not None:
            eq_params.append(f"brightness={vf.brightness}")
        if vf.contrast is not None:
            eq_params.append(f"contrast={vf.contrast}")
        if vf.saturation is not None:
            eq_params.append(f"saturation={vf.saturation}")

        if eq_params:
            filters.append(f"eq={':'.join(eq_params)}")

        # Rotation
        if vf.rotate:
            if vf.rotate == 90:
                filters.append("transpose=1")
            elif vf.rotate == 180:
                filters.append("transpose=1,transpose=1")
            elif vf.rotate == 270:
                filters.append("transpose=2")

        # Custom filters
        if vf.custom_filters:
            filters.extend(vf.custom_filters)

        return filters

    def _calculate_frame_timestamps(self, video_info: dict[str, Any]) -> list[float]:
        """Calculate timestamps of frames to extract.

        Delegates to :class:`TimestampCalculator`.
        """
        return self._timestamp_calculator.calculate_frame_timestamps(
            video_info,
            self.config.frame_extraction,
            self._detect_scene_timestamps,
        )

    def _detect_scene_timestamps(
        self, video_path: str, threshold: float, max_scenes: int
    ) -> list[float]:
        """
        Detect scene-change timestamps.

        Uses PySceneDetect (adaptive detector) as the primary method, with
        the legacy FFmpeg ``select='gt(scene,...)'`` filter as a fallback.

        Args:
            video_path: Path to the video file
            threshold: Detection threshold (0-1, FFmpeg scale)
            max_scenes: Maximum number of scenes to detect

        Returns:
            List of timestamps where scene changes occur
        """
        if not video_path or not os.path.exists(video_path):
            return []

        # --- Primary path: PySceneDetect ------------------------------------
        if self._use_pyscenedetect:
            psd_threshold = map_ffmpeg_threshold(threshold, method="adaptive")
            timestamps = self._scene_detect_service.detect_scene_timestamps(
                video_path, method="adaptive", threshold=psd_threshold
            )
            if timestamps:
                return timestamps[:max_scenes]
            # If PySceneDetect returned nothing, fall through to FFmpeg
            logger.info(
                "PySceneDetect returned no scenes for %s; falling back to FFmpeg",
                video_path,
            )

        # --- Fallback: FFmpeg scene filter ----------------------------------
        return self._detect_scene_timestamps_ffmpeg(video_path, threshold, max_scenes)

    def _detect_scene_timestamps_ffmpeg(
        self, video_path: str, threshold: float, max_scenes: int
    ) -> list[float]:
        """
        Detect scene-change timestamps using the FFmpeg scene filter (legacy).

        Args:
            video_path: Path to the video file
            threshold: Detection threshold (0-1)
            max_scenes: Maximum number of scenes to detect

        Returns:
            List of timestamps where scene changes occur
        """
        try:
            # Use FFmpeg for scene detection
            cmd = [
                "ffmpeg",
                *self._build_hwaccel_args(),
                "-i",
                video_path,
                "-vf",
                f"select='gt(scene,{threshold})',showinfo",
                "-f",
                "null",
                "-",
            ]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,  # 2 minute maximum
            )

            # Parse output to extract timestamps
            timestamps = []
            for line in result.stderr.split("\n"):
                if "pts_time:" in line:
                    try:
                        # Extract pts_time from showinfo output
                        pts_part = line.split("pts_time:")[1].split()[0]
                        ts = float(pts_part)
                        timestamps.append(ts)
                        if len(timestamps) >= max_scenes:
                            break
                    except (IndexError, ValueError):
                        continue

            return timestamps

        except subprocess.TimeoutExpired:
            logger.warning("FFmpeg scene detection timed out")
            return []
        except (subprocess.SubprocessError, FileNotFoundError) as e:
            logger.error(f"Error during FFmpeg scene detection: {e}")
            return []

    def extract_frames_ffmpeg(
        self, video_path: str, output_dir: str | None = None, return_as_bytes: bool = True
    ) -> list[dict[str, Any]]:
        """
        Extract frames using FFmpeg (ultra-fast method)

        Args:
            video_path: Path to the video file
            output_dir: Output directory (None = use temp directory)
            return_as_bytes: If True, returns frames as in-memory bytes

        Returns:
            List of dictionaries with information for each frame:
            {
                'timestamp': float,
                'frame_number': int,
                'image_data': bytes (if return_as_bytes=True),
                'file_path': str (if return_as_bytes=False)
            }
        """
        logger.info(f"extract_frames_ffmpeg started for: {video_path}")
        logger.debug(f"Video exists: {os.path.exists(video_path)}")

        video_info = self.get_video_info(video_path)

        logger.info(
            f"Video info: duration={video_info.get('duration', 'N/A')}s, "
            f"fps={video_info.get('fps', 'N/A')}, "
            f"resolution={video_info.get('width', 'N/A')}x{video_info.get('height', 'N/A')}"
        )

        # Update status
        self.status.video_duration = video_info["duration"]
        self.status.video_fps = video_info["fps"]
        self.status.video_width = video_info["width"]
        self.status.video_height = video_info["height"]
        self.status.status = "processing"

        # Create temporary directory if necessary
        if output_dir is None:
            output_dir = tempfile.mkdtemp(prefix="qprisma_frames_")
        else:
            os.makedirs(output_dir, exist_ok=True)

        logger.debug(f"Output directory: {output_dir}")

        start_time = time.time()
        frames: list[dict[str, Any]] = []

        # ---- PyAV fast-path ---------------------------------------------------
        if self._decoder_backend == "pyav":
            try:
                pyav_frames = self._extract_with_pyav(video_path, video_info)
                if pyav_frames is not None:
                    frames = pyav_frames

                    # Load images as bytes if required
                    if return_as_bytes:
                        for frame in frames:
                            if "file_path" in frame and "image_data" not in frame:
                                with open(frame["file_path"], "rb") as f:
                                    frame["image_data"] = f.read()
                                if output_dir.startswith(tempfile.gettempdir()):
                                    os.remove(frame["file_path"])

                    elapsed = time.time() - start_time
                    self.status.status = "completed"
                    self.status.progress = 100.0
                    self.status.frames_extracted = len(frames)
                    self.status.fps = len(frames) / elapsed if elapsed > 0 else 0

                    logger.info(
                        "Frame extraction finished: %d frames in %.2fs (%.1f fps), decoder=%s",
                        len(frames),
                        elapsed,
                        self.status.fps,
                        self._decoder_backend,
                        extra={"extraction_fps": self.status.fps, "decoder": self._decoder_backend},
                    )

                    # Deduplicate if enabled and frames have image_data
                    if (
                        self.config.frame_extraction.deduplication_enabled
                        and return_as_bytes
                        and frames
                        and "image_data" in frames[0]
                    ):
                        pre_dedup = len(frames)
                        frames = self._deduplicate_frames(
                            frames,
                            threshold=self.config.frame_extraction.deduplication_threshold,
                        )
                        self.status.frames_extracted = len(frames)
                        if pre_dedup != len(frames):
                            logger.info(
                                "Deduplication: %d -> %d frames (removed %d)",
                                pre_dedup,
                                len(frames),
                                pre_dedup - len(frames),
                                extra={"dedup_before": pre_dedup, "dedup_after": len(frames)},
                            )

                    return frames
            except Exception as e:
                logger.warning("PyAV extraction failed — falling back to subprocess: %s", e)
        # ---- end PyAV fast-path -----------------------------------------------

        try:
            extraction = self.config.frame_extraction

            logger.info(
                f"Extraction config: method={extraction.method}, max_frames={extraction.max_frames}"
            )
            if extraction.method == FrameExtractionMethod.FPS:
                logger.debug(f"FPS: {extraction.fps}")

            # Build filter chain
            filters = self._build_filter_chain(video_info)

            # Add path to video_info for methods that need it
            video_info["path"] = video_path

            # Specific extraction method
            if extraction.method == FrameExtractionMethod.KEYFRAMES:
                # Extract keyframes only
                filters.append("select='eq(pict_type\\,I)'")
                self._extract_with_select_filter(
                    video_path, output_dir, filters, video_info, frames
                )

            elif extraction.method == FrameExtractionMethod.SCENE_DETECT:
                # Scene change detection
                scene_filter = f"select='gt(scene\\,{extraction.scene_threshold})'"
                filters.append(scene_filter)
                self._extract_with_select_filter(
                    video_path, output_dir, filters, video_info, frames
                )

            else:
                # Timestamp-based methods (FPS, INTERVAL, UNIFORM, ADAPTIVE, HYBRID)
                timestamps = self._calculate_frame_timestamps(video_info)
                self.status.total_frames = len(timestamps)

                logger.info(f"Calculated timestamps: {len(timestamps)} frames")
                if timestamps:
                    logger.debug(
                        f"First timestamp: {timestamps[0]:.2f}s, Last: {timestamps[-1]:.2f}s"
                    )

                    # Calculate and log coverage metrics
                    coverage = self.calculate_coverage_metrics(timestamps, video_info["duration"])
                    logger.info(
                        f"Coverage score: {coverage['coverage_score']}%, "
                        f"avg_gap={coverage['average_gap']:.1f}s, max_gap={coverage['max_gap']:.1f}s"
                    )
                    if coverage["total_problematic_gaps"] > 0:
                        logger.warning(
                            f"{coverage['total_problematic_gaps']} gaps over {coverage['gap_threshold']}s"
                        )

                self._extract_at_timestamps(video_path, output_dir, timestamps, filters, frames)

            # Load images as bytes if required
            if return_as_bytes:
                for frame in frames:
                    if "file_path" in frame:
                        with open(frame["file_path"], "rb") as f:
                            frame["image_data"] = f.read()
                        # Optionally remove temporary file
                        if output_dir.startswith(tempfile.gettempdir()):
                            os.remove(frame["file_path"])

            # Update status
            elapsed = time.time() - start_time
            self.status.status = "completed"
            self.status.progress = 100.0
            self.status.frames_extracted = len(frames)
            self.status.fps = len(frames) / elapsed if elapsed > 0 else 0

            logger.info(
                "Frame extraction finished: %d frames in %.2fs (%.1f fps), decoder=%s",
                len(frames),
                elapsed,
                self.status.fps,
                self._decoder_backend,
                extra={"extraction_fps": self.status.fps, "decoder": self._decoder_backend},
            )

            # Deduplicate if enabled and frames have image_data
            if (
                self.config.frame_extraction.deduplication_enabled
                and return_as_bytes
                and frames
                and "image_data" in frames[0]
            ):
                pre_dedup = len(frames)
                frames = self._deduplicate_frames(
                    frames,
                    threshold=self.config.frame_extraction.deduplication_threshold,
                )
                self.status.frames_extracted = len(frames)
                if pre_dedup != len(frames):
                    logger.info(
                        "Deduplication: %d -> %d frames (removed %d)",
                        pre_dedup,
                        len(frames),
                        pre_dedup - len(frames),
                        extra={"dedup_before": pre_dedup, "dedup_after": len(frames)},
                    )

            return frames

        except Exception as e:
            self.status.status = "failed"
            self.status.error = str(e)
            raise RuntimeError(f"Error extracting frames: {str(e)}")

    # ------------------------------------------------------------------
    # Streaming frame extraction
    # ------------------------------------------------------------------

    async def extract_frames_stream(
        self,
        video_path: str,
    ) -> AsyncIterator[dict[str, Any]]:
        """Stream frames as they are extracted, yielding one at a time.

        Each yielded dict contains::

            {
                "image_data": bytes,
                "timestamp": float,
                "frame_number": int,
                "metadata": dict,
            }

        When the PyAV backend is available the method performs sequential
        decode inside a single dedicated thread (via
        :pymethod:`_pyav_frame_generator`) so the event-loop is never
        blocked.  If PyAV is unavailable or fails, the method falls back
        to the existing :pymethod:`extract_frames_ffmpeg` batch
        extraction and yields frames one at a time — downstream consumers
        still benefit from reduced peak memory.

        The generator respects ``self.config.frame_extraction.max_frames``
        for early termination.
        """
        video_info = await asyncio.to_thread(self.get_video_info, video_path)
        logger.info(
            "Streaming extraction started for %s (duration=%.1fs, %dx%d)",
            video_path,
            video_info.get("duration", 0),
            video_info.get("width", 0),
            video_info.get("height", 0),
        )

        # Update status metadata
        self.status.video_duration = video_info.get("duration", 0)
        self.status.video_fps = video_info.get("fps", 0)
        self.status.video_width = video_info.get("width", 0)
        self.status.video_height = video_info.get("height", 0)
        self.status.status = "processing"

        max_frames = self.config.frame_extraction.max_frames or 500
        yielded = 0

        # ---- PyAV streaming path -------------------------------------------
        if self._decoder_backend == "pyav":
            try:
                async for frame_dict in self._stream_via_pyav(video_path, video_info):
                    yield frame_dict
                    yielded += 1
                    if yielded >= max_frames:
                        break

                if yielded > 0:
                    self.status.status = "completed"
                    self.status.frames_extracted = yielded
                    logger.info(
                        "Streaming extraction completed (pyav): %d frames",
                        yielded,
                    )
                    return
            except Exception as exc:
                logger.warning(
                    "PyAV streaming failed — falling back to subprocess: %s",
                    exc,
                )

        # ---- Fallback: batch extract then yield one-by-one -----------------
        frames = await asyncio.to_thread(self.extract_frames_ffmpeg, video_path, None, True)
        for frame in frames:
            yield frame
            yielded += 1
            if yielded >= max_frames:
                break

        self.status.status = "completed"
        self.status.frames_extracted = yielded
        logger.info("Streaming extraction completed (fallback): %d frames", yielded)

    # -- helpers for extract_frames_stream ----------------------------------

    async def _stream_via_pyav(
        self,
        video_path: str,
        video_info: dict[str, Any],
    ) -> AsyncIterator[dict[str, Any]]:
        """Wrap the synchronous PyAV frame generator in an async iterator.

        A single-worker :class:`ThreadPoolExecutor` is used so that all
        PyAV container state stays on the same OS thread throughout the
        decode session.
        """
        sync_gen = self._pyav_frame_generator(video_path, video_info)
        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="pyav_stream")

        def _next_frame():
            try:
                return next(sync_gen)
            except StopIteration:
                return None

        loop = asyncio.get_running_loop()
        try:
            while True:
                frame = await loop.run_in_executor(executor, _next_frame)
                if frame is None:
                    break
                yield frame
        finally:
            executor.shutdown(wait=False)

    def _pyav_frame_generator(
        self,
        video_path: str,
        video_info: dict[str, Any],
    ):
        """Synchronous generator: decode video via PyAV, yield frames at
        target timestamps computed from ``self.config.frame_extraction``.

        For ``KEYFRAMES`` extraction the generator iterates demuxed
        packets and only decodes I-frames.  For all other methods it
        performs sequential ``container.decode(video=0)`` and selects the
        frames closest to each target timestamp.
        """
        from services.pyav_extractor import (
            _AV_AVAILABLE,
            _frame_to_rgb_ndarray,
            _open_container,
        )

        if not _AV_AVAILABLE:
            return

        import cv2

        extraction = self.config.frame_extraction
        max_frames = extraction.max_frames or 500

        # --- Keyframe-only path ---------------------------------------------
        if extraction.method == FrameExtractionMethod.KEYFRAMES:
            yield from self._pyav_keyframe_generator(video_path, max_frames)
            return

        # --- Timestamp-based methods ----------------------------------------
        video_info_copy = {**video_info, "path": video_path}
        timestamps = self._calculate_frame_timestamps(video_info_copy)
        if not timestamps:
            return
        timestamps = sorted(timestamps[:max_frames])

        try:
            with _open_container(video_path) as container:
                stream = container.streams.video[0]
                stream.thread_type = "AUTO"
                time_base = stream.time_base
                fps = float(stream.average_rate) if stream.average_rate else 25.0
                tolerance = 0.5 / fps  # half-frame tolerance

                ts_idx = 0
                frame_count = 0

                for av_frame in container.decode(video=0):
                    if ts_idx >= len(timestamps):
                        break

                    current_ts = (
                        float(av_frame.pts * time_base) if av_frame.pts is not None else 0.0
                    )
                    target_ts = timestamps[ts_idx]

                    if current_ts >= target_ts - tolerance:
                        rgb = _frame_to_rgb_ndarray(av_frame)
                        bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
                        ok, buf = cv2.imencode(
                            ".jpg",
                            bgr,
                            [cv2.IMWRITE_JPEG_QUALITY, 95],
                        )
                        if ok:
                            yield {
                                "frame_number": frame_count,
                                "timestamp": current_ts,
                                "image_data": buf.tobytes(),
                                "metadata": {
                                    "width": av_frame.width,
                                    "height": av_frame.height,
                                    "extraction_mode": "streaming_pyav",
                                },
                            }
                            frame_count += 1
                        ts_idx += 1
        except Exception:
            logger.exception(
                "Error in PyAV streaming frame generator for %s",
                video_path,
            )

    def _pyav_keyframe_generator(self, video_path: str, max_frames: int):
        """Yield only I-frames (keyframes) via PyAV demux."""
        import cv2

        from services.pyav_extractor import (
            _frame_to_rgb_ndarray,
            _open_container,
        )

        try:
            with _open_container(video_path) as container:
                stream = container.streams.video[0]
                stream.thread_type = "AUTO"
                time_base = stream.time_base
                frame_count = 0

                for packet in container.demux(stream):
                    if packet.dts is None or not packet.is_keyframe:
                        continue
                    for frame in packet.decode():
                        ts = float(frame.pts * time_base) if frame.pts is not None else 0.0
                        rgb = _frame_to_rgb_ndarray(frame)
                        bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
                        ok, buf = cv2.imencode(
                            ".jpg",
                            bgr,
                            [cv2.IMWRITE_JPEG_QUALITY, 95],
                        )
                        if ok:
                            yield {
                                "frame_number": frame_count,
                                "timestamp": ts,
                                "image_data": buf.tobytes(),
                                "metadata": {
                                    "width": frame.width,
                                    "height": frame.height,
                                    "extraction_mode": ("streaming_pyav_keyframes"),
                                },
                            }
                            frame_count += 1
                            if frame_count >= max_frames:
                                return
        except Exception:
            logger.exception("Error in PyAV keyframe generator for %s", video_path)

    # ------------------------------------------------------------------
    # PyAV backend delegation
    # ------------------------------------------------------------------

    def _extract_with_pyav(
        self, video_path: str, video_info: dict[str, Any]
    ) -> list[dict[str, Any]] | None:
        """Delegate frame extraction to :class:`PyAVFrameExtractor`.

        Returns a list of frame dicts compatible with the subprocess path,
        or ``None`` when extraction cannot be handled (caller should fall back).
        """
        from services.pyav_extractor import PyAVFrameExtractor

        extraction = self.config.frame_extraction
        method = extraction.method
        max_frames = extraction.max_frames
        raw_frames: list[tuple[float, np.ndarray]] = []

        if method == FrameExtractionMethod.KEYFRAMES:
            raw_frames = PyAVFrameExtractor.extract_keyframes(video_path, max_frames=max_frames)

        elif method == FrameExtractionMethod.SCENE_DETECT:
            scene_ts = PyAVFrameExtractor.detect_scenes_basic(
                video_path, threshold=extraction.scene_threshold or 0.4
            )
            if scene_ts:
                raw_frames = PyAVFrameExtractor.extract_frames(
                    video_path, scene_ts, max_frames=max_frames
                )

        elif method == FrameExtractionMethod.UNIFORM:
            num = min(extraction.num_frames or 10, max_frames or 1000)
            raw_frames = PyAVFrameExtractor.extract_frames_uniform(video_path, num)

        elif method == FrameExtractionMethod.FPS:
            raw_frames = PyAVFrameExtractor.extract_frames_fps(
                video_path, fps=extraction.fps or 1.0, max_frames=max_frames
            )

        elif method in (
            FrameExtractionMethod.INTERVAL,
            FrameExtractionMethod.ADAPTIVE,
            FrameExtractionMethod.HYBRID,
        ):
            timestamps = self._calculate_frame_timestamps(video_info)
            self.status.total_frames = len(timestamps)
            if timestamps:
                raw_frames = PyAVFrameExtractor.extract_frames(
                    video_path, timestamps, max_frames=max_frames
                )
        else:
            # Unknown method — let the subprocess path handle it
            return None

        if not raw_frames:
            logger.debug("PyAV returned no frames for method=%s", method)
            return []

        # Convert (ts, ndarray) tuples → frame dicts expected downstream
        import cv2

        results: list[dict[str, Any]] = []
        for idx, (ts, rgb_array) in enumerate(raw_frames):
            # Encode ndarray → JPEG bytes
            bgr = cv2.cvtColor(rgb_array, cv2.COLOR_RGB2BGR)
            ok, buf = cv2.imencode(".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, 95])
            if not ok:
                continue
            results.append(
                {
                    "frame_number": idx,
                    "timestamp": ts,
                    "image_data": buf.tobytes(),
                }
            )

        return results

    def _extract_with_select_filter(
        self,
        video_path: str,
        output_dir: str,
        filters: list[str],
        video_info: dict[str, Any],
        frames: list[dict[str, Any]],
    ):
        """Extract frames using select filter (keyframes/scenes)"""

        # The last filter must be the select filter
        filter_str = ",".join(filters)

        # Construir comando FFmpeg
        output_pattern = os.path.join(output_dir, "frame_%06d.jpg")

        stream = ffmpeg.input(video_path)
        stream = ffmpeg.filter(stream, "fps", fps=1)  # Placeholder, select override

        if filter_str:
            for f in filters:
                parts = f.split("=", 1)
                if len(parts) == 2:
                    filter_name, filter_args = parts
                    stream = ffmpeg.filter(stream, filter_name, filter_args)

        stream = ffmpeg.output(
            stream,
            output_pattern,
            vsync="vfr",  # Variable frame rate
            q=2,  # JPEG quality
            loglevel=self.config.log_level.value,
        )

        # Execute
        ffmpeg.run(stream, overwrite_output=True)

        # Collect generated frames
        frame_files = sorted(Path(output_dir).glob("frame_*.jpg"))

        for idx, frame_file in enumerate(frame_files[: self.config.frame_extraction.max_frames]):
            frames.append(
                {
                    "frame_number": idx,
                    "timestamp": None,  # Exact timestamp not known when using select filter
                    "file_path": str(frame_file),
                }
            )

            self.status.current_frame = idx + 1
            self.status.progress = min(
                (idx + 1) / min(len(frame_files), self.config.frame_extraction.max_frames) * 100,
                100.0,
            )

    @property
    def _max_extraction_workers(self) -> int:
        """Resolve effective extraction worker count.

        Priority:
        1. ``settings.processing.max_extraction_workers`` if explicitly set
        2. Dynamic calculation via ``_get_optimal_workers()``
        """
        try:
            from core.config import get_settings

            configured = get_settings().processing.max_extraction_workers
            if configured is not None:
                return configured
        except Exception:
            pass
        return _get_optimal_workers()

    def _extract_single_frame(
        self,
        video_path: str,
        timestamp: float,
        idx: int,
        filters: list[str],
    ) -> dict[str, Any] | None:
        """
        Extract a single frame via FFmpeg pipe-to-memory (no disk I/O).

        Returns frame dict with image_data bytes, or None on failure.
        """
        try:
            cmd = [
                "ffmpeg",
                *self._build_hwaccel_args(),
                "-ss",
                str(timestamp),
                "-i",
                video_path,
                "-vframes",
                "1",
                "-q:v",
                "2",
                "-f",
                "image2pipe",
                "-vcodec",
                "mjpeg",
                "-",
            ]

            result = subprocess.run(
                cmd,
                capture_output=True,
                timeout=30,
                cwd=os.path.dirname(video_path) or ".",
            )

            if result.returncode == 0 and result.stdout and len(result.stdout) > 0:
                return {
                    "frame_number": idx,
                    "timestamp": timestamp,
                    "image_data": result.stdout,
                }
            else:
                logger.warning(f"Empty frame at t={timestamp}, rc={result.returncode}")
                if result.stderr:
                    logger.debug(f"FFmpeg stderr: {result.stderr[:500]}")
                return None

        except subprocess.TimeoutExpired:
            logger.warning(f"Timeout extracting frame at t={timestamp}")
            return None
        except subprocess.SubprocessError as e:
            logger.error(f"Subprocess error at t={timestamp}: {e}")
            return None
        except Exception as e:
            logger.exception(f"Unexpected error at t={timestamp}: {type(e).__name__}: {e}")
            return None

    def _extract_at_timestamps(
        self,
        video_path: str,
        output_dir: str,
        timestamps: list[float],
        filters: list[str],
        frames: list[dict[str, Any]],
    ) -> None:
        """
        Extract frames at specific timestamps using FFmpeg in parallel.

        Uses ThreadPoolExecutor for concurrent extraction with pipe-to-memory,
        eliminating sequential subprocess overhead and disk I/O.

        Args:
            video_path: Path to the video file.
            output_dir: Output directory for frames (used as fallback).
            timestamps: List of timestamps to extract.
            filters: FFmpeg filters to apply.
            frames: List to append extracted frames to.
        """
        total = len(timestamps)
        max_workers = self._max_extraction_workers
        logger.info(f"Extracting {total} frames in parallel (max {max_workers} workers)")
        logger.debug(f"Video: {video_path}")
        if total > 5:
            logger.debug(f"Timestamps: {timestamps[:5]}...")
        else:
            logger.debug(f"Timestamps: {timestamps}")

        # Debug: log first command
        if timestamps:
            cmd_preview = (
                f"ffmpeg -ss {timestamps[0]} -i {video_path} "
                f"-vframes 1 -f image2pipe -vcodec mjpeg -"
            )
            logger.debug(f"Comando FFmpeg (ejemplo): {cmd_preview}")

        extracted_count = 0
        workers = min(max_workers, total)

        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(self._extract_single_frame, video_path, ts, idx, filters): idx
                for idx, ts in enumerate(timestamps)
            }

            for future in as_completed(futures):
                result = future.result()
                if result is not None:
                    # Write to disk for caller's return_as_bytes handling
                    frame_num = result["frame_number"]
                    output_file = os.path.join(output_dir, f"frame_{frame_num:06d}.jpg")
                    with open(output_file, "wb") as f:
                        f.write(result["image_data"])
                    result["file_path"] = output_file

                    frames.append(result)
                    extracted_count += 1

                    # Update progress
                    self.status.current_frame = extracted_count
                    self.status.progress = extracted_count / total * 100

                    if extracted_count % 10 == 0:
                        logger.debug(f"{extracted_count}/{total} frames extracted")

        # Sort frames by frame_number to maintain temporal order
        frames.sort(key=lambda f: f["frame_number"])
        logger.info(f"Parallel extraction completed: {extracted_count}/{total} frames")

    def frame_to_base64(self, frame_data: bytes) -> str:
        """
        Convert frame to base64

        Args:
            frame_data: Image data as bytes

        Returns:
            Base64-encoded string
        """
        return base64.b64encode(frame_data).decode("utf-8")

    def _deduplicate_frames(
        self,
        frames: list[dict[str, Any]],
        threshold: int = 5,
    ) -> list[dict[str, Any]]:
        """Remove near-duplicate frames using perceptual hashing.

        Compares each frame's phash against previously accepted frames.
        A Hamming distance below ``threshold`` is considered a duplicate.

        Args:
            frames: List of frame dicts containing ``image_data`` bytes.
            threshold: Hamming distance threshold (lower = stricter).

        Returns:
            Filtered list with duplicates removed.
        """
        if not frames:
            return frames

        seen_hashes: list[imagehash.ImageHash] = []
        unique_frames: list[dict[str, Any]] = []

        for frame in frames:
            img = Image.open(io.BytesIO(frame["image_data"]))
            frame_hash = imagehash.phash(img)

            is_duplicate = any((frame_hash - seen) < threshold for seen in seen_hashes)

            if not is_duplicate:
                seen_hashes.append(frame_hash)
                unique_frames.append(frame)

        if len(frames) != len(unique_frames):
            removed = len(frames) - len(unique_frames)
            reduction = (1 - len(unique_frames) / len(frames)) * 100
            logger.info(
                "Frame deduplication: %d → %d " "(%d duplicates removed, %.1f%% reduction)",
                len(frames),
                len(unique_frames),
                removed,
                reduction,
            )

        return unique_frames

    def get_processing_pipeline(self) -> ProcessingPipeline:
        """
        Generate a representation of the processing pipeline for visualization

        Returns:
            ProcessingPipeline with nodes and edges for the graph
        """
        nodes = []
        edges = []
        node_id = 0

        # Node 1: Input
        # Video description (with default values if not yet processed)
        video_desc = "Video source"
        if self.status.video_width and self.status.video_height and self.status.video_fps:
            video_desc = f"{self.status.video_width}x{self.status.video_height} @ {self.status.video_fps:.2f}fps"

        nodes.append(
            {
                "id": f"node_{node_id}",
                "type": "input",
                "data": {"label": "Video Input", "icon": "📹", "description": video_desc},
                "position": {"x": 100, "y": 100},
            }
        )
        prev_node = node_id
        node_id += 1

        # Node 2: Frame Extraction
        extraction = self.config.frame_extraction
        nodes.append(
            {
                "id": f"node_{node_id}",
                "type": "process",
                "data": {
                    "label": "Frame Extraction",
                    "icon": "🎞️",
                    "description": f"Method: {extraction.method.value}",
                    "details": {
                        "method": extraction.method.value,
                        "max_frames": extraction.max_frames,
                        "fps": (
                            extraction.fps
                            if extraction.method == FrameExtractionMethod.FPS
                            else None
                        ),
                        "interval": (
                            extraction.interval_seconds
                            if extraction.method == FrameExtractionMethod.INTERVAL
                            else None
                        ),
                    },
                },
                "position": {"x": 100, "y": 200},
            }
        )
        edges.append(
            {
                "id": f"edge_{prev_node}_{node_id}",
                "source": f"node_{prev_node}",
                "target": f"node_{node_id}",
            }
        )
        prev_node = node_id
        node_id += 1

        # Node 3: Video Filters (if any are configured)
        vf = self.config.video_filters
        has_filters = any(
            [
                vf.scale_width,
                vf.scale_height,
                vf.pixel_format,
                vf.crop_width,
                vf.brightness is not None,
                vf.contrast is not None,
                vf.saturation is not None,
                vf.rotate,
                vf.deinterlace,
                vf.hdr_to_sdr,
            ]
        )

        if has_filters:
            filter_details = []
            if vf.scale_width or vf.scale_height:
                filter_details.append(
                    f'Scale: {vf.scale_width or "auto"}x{vf.scale_height or "auto"}'
                )
            if vf.pixel_format:
                filter_details.append(f"Format: {vf.pixel_format.value}")
            if vf.deinterlace:
                filter_details.append("Deinterlace")
            if vf.hdr_to_sdr:
                filter_details.append("HDR→SDR")

            nodes.append(
                {
                    "id": f"node_{node_id}",
                    "type": "process",
                    "data": {
                        "label": "Video Filters",
                        "icon": "🎨",
                        "description": ", ".join(filter_details[:2]),
                        "details": {"filters": filter_details},
                    },
                    "position": {"x": 100, "y": 300},
                }
            )
            edges.append(
                {
                    "id": f"edge_{prev_node}_{node_id}",
                    "source": f"node_{prev_node}",
                    "target": f"node_{node_id}",
                }
            )
            prev_node = node_id
            node_id += 1

        # Node 4: GPT-Vision Analysis
        nodes.append(
            {
                "id": f"node_{node_id}",
                "type": "process",
                "data": {
                    "label": "GPT-Vision Analysis",
                    "icon": "🤖",
                    "description": "Frame content analysis",
                    "details": {"model": "gpt-5-mini", "task": "Visual scene understanding"},
                },
                "position": {"x": 100, "y": 400 if has_filters else 300},
            }
        )
        edges.append(
            {
                "id": f"edge_{prev_node}_{node_id}",
                "source": f"node_{prev_node}",
                "target": f"node_{node_id}",
            }
        )
        prev_node = node_id
        node_id += 1

        # Node 5: Embedding Generation
        nodes.append(
            {
                "id": f"node_{node_id}",
                "type": "process",
                "data": {
                    "label": "Embedding Generation",
                    "icon": "🧮",
                    "description": "text-embedding-3-large",
                    "details": {"model": "text-embedding-3-large", "dimensions": 3072},
                },
                "position": {"x": 300, "y": 400 if has_filters else 300},
            }
        )
        edges.append(
            {
                "id": f"edge_{prev_node}_{node_id}",
                "source": f"node_{prev_node}",
                "target": f"node_{node_id}",
            }
        )

        # Node 6: Knowledge Graph Indexing
        nodes.append(
            {
                "id": f"node_{node_id + 1}",
                "type": "output",
                "data": {
                    "label": "Index to Knowledge Graph",
                    "icon": "🔍",
                    "description": "Neo4j persistence for retrieval",
                    "details": {"store": "neo4j"},
                },
                "position": {"x": 300, "y": 500 if has_filters else 400},
            }
        )
        edges.append(
            {
                "id": f"edge_{node_id}_{node_id + 1}",
                "source": f"node_{node_id}",
                "target": f"node_{node_id + 1}",
            }
        )

        # Node 7: Cosmos DB Storage
        nodes.append(
            {
                "id": f"node_{node_id + 2}",
                "type": "output",
                "data": {
                    "label": "Store in Cosmos DB",
                    "icon": "💾",
                    "description": "Metadata persistence",
                    "details": {"database": "qprisma", "container": "media-metadata"},
                },
                "position": {"x": 500, "y": 500 if has_filters else 400},
            }
        )
        edges.append(
            {
                "id": f"edge_{node_id}_{node_id + 2}",
                "source": f"node_{node_id}",
                "target": f"node_{node_id + 2}",
            }
        )

        return ProcessingPipeline(nodes=nodes, edges=edges, config=self.config)

    def get_status(self) -> ProcessingStatus:
        """Return the current processing status"""
        return self.status

    def calculate_coverage_metrics(
        self, timestamps: list[float], video_duration: float
    ) -> dict[str, Any]:
        """Calculate video coverage metrics.

        Delegates to :class:`CoverageAnalyzer`.

        Args:
            timestamps: List of extracted timestamps
            video_duration: Total video duration in seconds

        Returns:
            Dict with coverage metrics (coverage_score, average_gap, max_gap, etc.)
        """
        return self._coverage_analyzer.calculate_coverage_metrics(timestamps, video_duration)


def get_recommended_preset(video_duration: float, content_type: str = "general") -> str:
    """
    Recommend the optimal preset based on duration and content type.

    Args:
        video_duration: Duration in seconds
        content_type: Content type (general, interview, action, tutorial)

    Returns:
        Name of the recommended preset
    """
    duration_minutes = video_duration / 60

    # By content type
    if content_type == "interview":
        return "interview_mode"
    elif content_type == "action":
        return "action_mode"
    elif content_type == "tutorial":
        # Tutorials require good visual coverage
        if duration_minutes < 30:
            return "high_quality"
        else:
            return "deep_analysis"

    # By duration (general)
    if duration_minutes < 5:
        return "balanced"
    elif duration_minutes < 30:
        return "high_quality"
    elif duration_minutes < 120:
        return "deep_analysis"
    else:
        return "adaptive"
