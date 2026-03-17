"""
Video preparation service for Video-MME evaluation.

Handles the full video lifecycle against a remote QPrisma API:
discover already-indexed videos, download missing ones via yt-dlp,
upload and wait for processing, and build the ID mapping.
"""

import asyncio
import json
import logging
import re
import shutil
import subprocess
import sys
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

VMME_FILENAME_PREFIX = "vmme_"
UPLOAD_CHUNK_DELAY = 2.0  # seconds between uploads to avoid rate limits
POLL_INTERVAL_INITIAL = 10.0  # seconds
POLL_INTERVAL_MAX = 60.0
POLL_BACKOFF_FACTOR = 1.5
DEFAULT_PROCESSING_TIMEOUT = 900  # 15 minutes per video


def _find_yt_dlp() -> str:
    """Find yt-dlp executable, checking venv Scripts dir and PATH."""
    # Check alongside the running Python interpreter first (venv Scripts/)
    python_dir = Path(sys.executable).parent
    for name in ("yt-dlp", "yt-dlp.exe"):
        candidate = python_dir / name
        if candidate.exists():
            return str(candidate)
    # Fall back to PATH
    found = shutil.which("yt-dlp")
    if found:
        return found
    raise FileNotFoundError("yt-dlp not found. Install it: pip install yt-dlp")


class VideoPreparationService:
    """Manages video lifecycle for Video-MME evaluation against a remote API.

    Naming convention: videos are uploaded as ``vmme_{youtube_id}.mp4``
    so they can be discovered by original_filename on subsequent runs.
    """

    def __init__(
        self,
        api_url: str,
        token: str,
        video_dir: str | Path = "evaluation/data/videos",
        mapping_path: str | Path = "evaluation/data/video_mme_id_mapping.json",
    ):
        self.api_url = api_url.rstrip("/")
        self.token = token
        self.video_dir = Path(video_dir)
        self.mapping_path = Path(mapping_path)
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self):
        self._client = httpx.AsyncClient(
            base_url=self.api_url,
            headers={"Authorization": f"Bearer {self.token}"},
            timeout=httpx.Timeout(60.0),
        )
        return self

    async def __aexit__(self, *exc):
        if self._client:
            await self._client.aclose()
            self._client = None

    # -------------------------------------------------------------------------
    # Phase 1: Discover already-indexed videos
    # -------------------------------------------------------------------------

    async def discover_indexed_videos(self) -> dict[str, str]:
        """Query GET /media to find already-indexed Video-MME videos.

        Matches videos by ``original_filename`` starting with ``vmme_``.

        Returns:
            Dict mapping YouTube ID → QPrisma media UUID.
        """
        assert self._client is not None
        mapping: dict[str, str] = {}
        offset = 0
        limit = 100

        while True:
            try:
                resp = await self._client.get("/media", params={"limit": limit, "offset": offset})
                resp.raise_for_status()
                data = resp.json()
            except httpx.HTTPError as e:
                logger.error("Failed to list media: %s", e)
                break

            media_list = data.get("media", [])
            if not media_list:
                break

            for item in media_list:
                filename = item.get("original_filename", "")
                media_id = item.get("id", "")
                status = item.get("processing_status", "")

                if filename.startswith(VMME_FILENAME_PREFIX) and status == "completed":
                    # Extract YouTube ID from filename: vmme_{youtube_id}.mp4
                    yt_id = filename[len(VMME_FILENAME_PREFIX) :]
                    yt_id = Path(yt_id).stem  # strip extension
                    if yt_id:
                        mapping[yt_id] = media_id

            if len(media_list) < limit:
                break
            offset += limit

        logger.info("Discovered %d already-indexed Video-MME videos", len(mapping))
        return mapping

    # -------------------------------------------------------------------------
    # Phase 2: Download videos from YouTube via yt-dlp
    # -------------------------------------------------------------------------

    def download_videos(
        self,
        youtube_ids: list[str],
        max_resolution: int = 720,
    ) -> dict[str, Path]:
        """Download Video-MME videos from YouTube using yt-dlp.

        Args:
            youtube_ids: List of YouTube video IDs to download.
            max_resolution: Maximum video resolution (default 720p).

        Returns:
            Dict mapping YouTube ID → local file path for successfully
            downloaded videos.
        """
        self.video_dir.mkdir(parents=True, exist_ok=True)
        downloaded: dict[str, Path] = {}

        try:
            yt_dlp_bin = _find_yt_dlp()
        except FileNotFoundError:
            logger.error("yt-dlp not found. Install it: pip install yt-dlp")
            return downloaded

        for yt_id in youtube_ids:
            safe_id = _sanitize_filename(yt_id)
            output_path = self.video_dir / f"{VMME_FILENAME_PREFIX}{safe_id}.mp4"

            if output_path.exists() and output_path.stat().st_size > 0:
                logger.info("Already downloaded: %s", output_path.name)
                downloaded[yt_id] = output_path
                continue

            url = f"https://www.youtube.com/watch?v={yt_id}"
            output_template = str(self.video_dir / f"{VMME_FILENAME_PREFIX}{safe_id}.%(ext)s")

            cmd = [
                yt_dlp_bin,
                "--no-playlist",
                "-f",
                f"best[height<={max_resolution}][ext=mp4]/best[height<={max_resolution}]/best",
                "--merge-output-format",
                "mp4",
                "-o",
                output_template,
                "--no-overwrites",
                "--socket-timeout",
                "30",
                "--retries",
                "3",
                url,
            ]

            logger.info("Downloading %s ...", yt_id)
            try:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=600,
                )
                # yt-dlp writes to the template path with resolved extension
                actual_path = self.video_dir / f"{VMME_FILENAME_PREFIX}{safe_id}.mp4"
                if actual_path.exists() and actual_path.stat().st_size > 0:
                    downloaded[yt_id] = actual_path
                    logger.info(
                        "Downloaded: %s (%.1f MB)",
                        actual_path.name,
                        actual_path.stat().st_size / 1e6,
                    )
                elif result.returncode != 0:
                    logger.warning(
                        "yt-dlp failed for %s (exit %d): %s",
                        yt_id,
                        result.returncode,
                        result.stderr[:300],
                    )
                else:
                    logger.warning("Download completed but file not found for %s", yt_id)
            except subprocess.TimeoutExpired:
                logger.warning("Download timed out for %s", yt_id)

        logger.info("Downloaded %d/%d videos", len(downloaded), len(youtube_ids))
        return downloaded

    # -------------------------------------------------------------------------
    # Phase 3: Upload videos to QPrisma API
    # -------------------------------------------------------------------------

    async def upload_videos(
        self,
        video_paths: dict[str, Path],
    ) -> dict[str, str]:
        """Upload video files to the QPrisma API.

        Args:
            video_paths: Dict mapping YouTube ID → local file path.

        Returns:
            Dict mapping YouTube ID → QPrisma media UUID for
            successfully uploaded videos.
        """
        assert self._client is not None
        mapping: dict[str, str] = {}

        for yt_id, path in video_paths.items():
            if not path.exists():
                logger.warning("Video file not found: %s", path)
                continue

            logger.info("Uploading %s ...", path.name)
            try:
                with open(path, "rb") as f:
                    files = {"file": (path.name, f, "video/mp4")}
                    resp = await self._client.post(
                        "/upload",
                        files=files,
                        timeout=httpx.Timeout(300.0),
                    )
                    resp.raise_for_status()

                data = resp.json()
                media_id = data.get("media_id", "")
                if media_id:
                    mapping[yt_id] = media_id
                    logger.info(
                        "Uploaded %s → %s (status: %s)",
                        path.name,
                        media_id,
                        data.get("status"),
                    )
                else:
                    logger.error("Upload returned no media_id for %s", path.name)
            except httpx.HTTPStatusError as e:
                logger.error(
                    "Upload failed for %s: HTTP %d – %s",
                    path.name,
                    e.response.status_code,
                    e.response.text[:200],
                )
            except httpx.HTTPError as e:
                logger.error("Upload error for %s: %s", path.name, e)

            # Brief delay between uploads to avoid rate limits
            await asyncio.sleep(UPLOAD_CHUNK_DELAY)

        logger.info("Uploaded %d/%d videos", len(mapping), len(video_paths))
        return mapping

    # -------------------------------------------------------------------------
    # Phase 4: Wait for processing to complete
    # -------------------------------------------------------------------------

    async def wait_for_processing(
        self,
        media_ids: dict[str, str],
        timeout_per_video: float = DEFAULT_PROCESSING_TIMEOUT,
    ) -> dict[str, str]:
        """Poll processing status until all videos are completed or failed.

        Args:
            media_ids: Dict mapping YouTube ID → QPrisma media UUID.
            timeout_per_video: Max seconds to wait per video.

        Returns:
            Dict of YouTube ID → media UUID for successfully processed videos.
        """
        assert self._client is not None
        completed: dict[str, str] = {}
        pending = dict(media_ids)

        logger.info("Waiting for %d videos to finish processing...", len(pending))

        start = asyncio.get_event_loop().time()
        interval = POLL_INTERVAL_INITIAL

        while pending:
            elapsed = asyncio.get_event_loop().time() - start
            if elapsed > timeout_per_video * len(media_ids):
                logger.error(
                    "Global timeout: %d videos still processing after %.0fs",
                    len(pending),
                    elapsed,
                )
                break

            still_pending: dict[str, str] = {}
            for yt_id, mid in pending.items():
                try:
                    resp = await self._client.get(f"/media/{mid}/status")
                    resp.raise_for_status()
                    status_data = resp.json()
                    status = status_data.get("processing_status", "unknown")
                except httpx.HTTPError as e:
                    logger.warning("Status check failed for %s: %s", mid, e)
                    still_pending[yt_id] = mid
                    continue

                if status == "completed":
                    completed[yt_id] = mid
                    logger.info("✓ %s processing completed", yt_id)
                elif status in ("failed", "error"):
                    logger.error(
                        "✗ %s processing failed: %s",
                        yt_id,
                        status_data.get("error", "unknown"),
                    )
                else:
                    still_pending[yt_id] = mid

            pending = still_pending

            if pending:
                logger.info(
                    "  %d/%d still processing (%.0fs elapsed, next poll in %.0fs)",
                    len(pending),
                    len(media_ids),
                    elapsed,
                    interval,
                )
                await asyncio.sleep(interval)
                interval = min(interval * POLL_BACKOFF_FACTOR, POLL_INTERVAL_MAX)

        logger.info(
            "Processing complete: %d/%d succeeded",
            len(completed),
            len(media_ids),
        )
        return completed

    # -------------------------------------------------------------------------
    # Phase 5: Build and persist the ID mapping
    # -------------------------------------------------------------------------

    def build_and_persist_mapping(
        self,
        mapping: dict[str, str],
    ) -> dict[str, str]:
        """Merge new mappings with any existing mapping file and persist.

        Args:
            mapping: Dict mapping YouTube ID → QPrisma media UUID.

        Returns:
            The full merged mapping.
        """
        existing = self.load_mapping()
        existing.update(mapping)

        self.mapping_path.parent.mkdir(parents=True, exist_ok=True)
        self.mapping_path.write_text(
            json.dumps(existing, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        logger.info("ID mapping saved to %s (%d entries)", self.mapping_path, len(existing))
        return existing

    def load_mapping(self) -> dict[str, str]:
        """Load existing ID mapping from disk, if any."""
        if self.mapping_path.exists():
            try:
                return json.loads(self.mapping_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("Failed to load mapping: %s", e)
        return {}

    # -------------------------------------------------------------------------
    # High-level orchestration
    # -------------------------------------------------------------------------

    async def prepare_videos(
        self,
        required_youtube_ids: list[str],
        skip_upload: bool = False,
    ) -> dict[str, str]:
        """Full preparation pipeline: discover → download → upload → wait → map.

        Args:
            required_youtube_ids: YouTube IDs needed for evaluation.
            skip_upload: If True, skip download/upload (use existing indexed
                videos and saved mapping only).

        Returns:
            Dict mapping YouTube ID → QPrisma media UUID for all
            available videos (may be fewer than requested).
        """
        # Load saved mapping
        saved_mapping = self.load_mapping()

        # Discover what's already indexed on the remote API
        indexed = await self.discover_indexed_videos()

        # Merge discoveries
        full_mapping = {**saved_mapping, **indexed}
        already_available = {yt_id for yt_id in required_youtube_ids if yt_id in full_mapping}
        missing = [yt_id for yt_id in required_youtube_ids if yt_id not in already_available]

        logger.info(
            "Video status: %d available, %d missing (of %d required)",
            len(already_available),
            len(missing),
            len(required_youtube_ids),
        )

        if missing and not skip_upload:
            # Download missing videos
            downloaded = self.download_videos(missing)

            if downloaded:
                # Upload to API
                uploaded = await self.upload_videos(downloaded)

                if uploaded:
                    # Wait for processing
                    processed = await self.wait_for_processing(uploaded)
                    full_mapping.update(processed)

        # Persist the complete mapping
        result = {
            yt_id: full_mapping[yt_id] for yt_id in required_youtube_ids if yt_id in full_mapping
        }
        self.build_and_persist_mapping(result)

        logger.info(
            "Preparation complete: %d/%d videos ready",
            len(result),
            len(required_youtube_ids),
        )
        return result


def _sanitize_filename(yt_id: str) -> str:
    """Sanitize a YouTube ID for use in filenames."""
    return re.sub(r"[^\w\-]", "_", yt_id)
