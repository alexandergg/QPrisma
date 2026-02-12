"""Basic FFmpeg frame extraction smoke test."""

import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.slow]


@pytest.fixture(scope="module")
def sample_video() -> Path:
    video_path = Path(__file__).parent / "test_data" / "test_video.mp4"
    if not video_path.exists():
        pytest.skip(f"Sample video not found: {video_path}")
    return video_path


@pytest.fixture(scope="module")
def output_frame_path() -> Path:
    return Path(__file__).parent / "test_data" / "test_frame.jpg"


def test_ffmpeg_extraction(sample_video: Path, output_frame_path: Path) -> None:
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg executable not found in PATH")

    output_frame_path.unlink(missing_ok=True)
    command = [
        "ffmpeg",
        "-ss",
        "5.0",
        "-i",
        str(sample_video),
        "-vframes",
        "1",
        "-q:v",
        "2",
        "-y",
        str(output_frame_path),
    ]

    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert output_frame_path.exists()
    assert output_frame_path.stat().st_size > 0
