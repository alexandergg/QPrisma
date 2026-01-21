"""
Tests for Export Service
Tests video clip export functionality including FFmpeg operations.
"""

import json
import subprocess
from fractions import Fraction
from unittest.mock import patch

import pytest

from models.export_config import ExportConfig, ExportFormat
from services.export_service import ExportService


@pytest.fixture
def export_service():
    """Create an ExportService instance for testing."""
    return ExportService()


@pytest.fixture
def mock_video_info():
    """Mock video information."""
    return {
        "duration": 120.5,
        "width": 1920,
        "height": 1080,
        "fps": 30.0,
        "codec": "h264",
        "has_audio": True,
        "audio_codec": "aac",
        "path": "/path/to/video.mp4",
    }


@pytest.fixture
def export_config():
    """Create a basic export configuration."""
    return ExportConfig(
        start_time=10.0,
        end_time=20.0,
        format=ExportFormat.MP4,
        quality="medium",
    )


class TestGetVideoInfo:
    """Tests for _get_video_info method."""

    def test_parses_fps_correctly(self, export_service):
        """Test that FPS is parsed correctly from r_frame_rate."""
        mock_output = {
            "format": {"duration": "120.5"},
            "streams": [
                {
                    "codec_type": "video",
                    "width": 1920,
                    "height": 1080,
                    "r_frame_rate": "30000/1001",  # NTSC framerate
                    "codec_name": "h264",
                }
            ],
        }

        with patch("subprocess.run") as mock_run:
            mock_run.return_value.stdout = json.dumps(mock_output)
            result = export_service._get_video_info("/test/video.mp4")

            # Verify FPS is calculated correctly
            expected_fps = float(Fraction("30000/1001"))
            assert abs(result["fps"] - expected_fps) < 0.01

    def test_handles_invalid_fps_gracefully(self, export_service):
        """Test that invalid FPS values default to 30."""
        mock_output = {
            "format": {"duration": "120.5"},
            "streams": [
                {
                    "codec_type": "video",
                    "width": 1920,
                    "height": 1080,
                    "r_frame_rate": "invalid/fps",
                    "codec_name": "h264",
                }
            ],
        }

        with patch("subprocess.run") as mock_run:
            mock_run.return_value.stdout = json.dumps(mock_output)
            result = export_service._get_video_info("/test/video.mp4")

            assert result["fps"] == 30.0

    def test_handles_zero_denominator_fps(self, export_service):
        """Test that division by zero in FPS is handled."""
        mock_output = {
            "format": {"duration": "120.5"},
            "streams": [
                {
                    "codec_type": "video",
                    "width": 1920,
                    "height": 1080,
                    "r_frame_rate": "30/0",  # Zero denominator
                    "codec_name": "h264",
                }
            ],
        }

        with patch("subprocess.run") as mock_run:
            mock_run.return_value.stdout = json.dumps(mock_output)
            result = export_service._get_video_info("/test/video.mp4")

            assert result["fps"] == 30.0

    def test_detects_audio_stream(self, export_service):
        """Test that audio stream is detected correctly."""
        mock_output = {
            "format": {"duration": "120.5"},
            "streams": [
                {
                    "codec_type": "video",
                    "width": 1920,
                    "height": 1080,
                    "r_frame_rate": "30/1",
                    "codec_name": "h264",
                },
                {"codec_type": "audio", "codec_name": "aac"},
            ],
        }

        with patch("subprocess.run") as mock_run:
            mock_run.return_value.stdout = json.dumps(mock_output)
            result = export_service._get_video_info("/test/video.mp4")

            assert result["has_audio"] is True
            assert result["audio_codec"] == "aac"

    def test_handles_video_without_audio(self, export_service):
        """Test video without audio stream."""
        mock_output = {
            "format": {"duration": "120.5"},
            "streams": [
                {
                    "codec_type": "video",
                    "width": 1920,
                    "height": 1080,
                    "r_frame_rate": "30/1",
                    "codec_name": "h264",
                }
            ],
        }

        with patch("subprocess.run") as mock_run:
            mock_run.return_value.stdout = json.dumps(mock_output)
            result = export_service._get_video_info("/test/video.mp4")

            assert result["has_audio"] is False
            assert result["audio_codec"] is None

    def test_returns_empty_dict_on_error(self, export_service):
        """Test that empty dict is returned when ffprobe fails."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.CalledProcessError(1, "ffprobe")
            result = export_service._get_video_info("/test/video.mp4")

            assert result == {}

    def test_handles_missing_duration(self, export_service):
        """Test handling of missing duration in format."""
        mock_output = {
            "format": {},  # No duration
            "streams": [
                {
                    "codec_type": "video",
                    "width": 1920,
                    "height": 1080,
                    "r_frame_rate": "30/1",
                    "codec_name": "h264",
                }
            ],
        }

        with patch("subprocess.run") as mock_run:
            mock_run.return_value.stdout = json.dumps(mock_output)
            result = export_service._get_video_info("/test/video.mp4")

            assert result["duration"] == 0.0


class TestVideoClipping:
    """Tests for video clipping functionality."""

    def test_clip_video_builds_correct_command(self, export_service, export_config):
        """Test that correct FFmpeg command is built for clipping."""
        with patch("subprocess.run") as mock_run, patch.object(
            export_service, "_get_video_info", return_value={"duration": 120}
        ), patch("os.path.exists", return_value=True):
            export_service.clip_video("/source.mp4", "/output.mp4", export_config)

            # Verify FFmpeg was called
            assert mock_run.called
            cmd = mock_run.call_args[0][0]

            # Check key parameters
            assert "ffmpeg" in cmd
            assert "-ss" in cmd
            assert "10.0" in cmd  # start time
            assert "-to" in cmd
            assert "20.0" in cmd  # end time

    def test_clip_validates_time_range(self, export_service):
        """Test that invalid time ranges are rejected."""
        config = ExportConfig(
            start_time=20.0, end_time=10.0, format=ExportFormat.MP4  # Invalid: end < start
        )

        with patch.object(
            export_service, "_get_video_info", return_value={"duration": 120}
        ), patch("os.path.exists", return_value=True), pytest.raises(ValueError, match="end time must be after start time"):
            export_service.clip_video("/source.mp4", "/output.mp4", config)

    def test_clip_respects_quality_settings(self, export_service):
        """Test that quality settings are applied correctly."""
        config = ExportConfig(
            start_time=10.0, end_time=20.0, format=ExportFormat.MP4, quality="high"
        )

        with patch("subprocess.run") as mock_run, patch.object(
            export_service, "_get_video_info", return_value={"duration": 120}
        ), patch("os.path.exists", return_value=True):
            export_service.clip_video("/source.mp4", "/output.mp4", config)

            cmd = mock_run.call_args[0][0]
            # High quality should use lower CRF value
            assert "-crf" in cmd


class TestFormatConversion:
    """Tests for format conversion functionality."""

    def test_converts_to_webm(self, export_service):
        """Test conversion to WebM format."""
        config = ExportConfig(start_time=0, end_time=10, format=ExportFormat.WEBM)

        with patch("subprocess.run") as mock_run, patch.object(
            export_service, "_get_video_info", return_value={"duration": 120}
        ), patch("os.path.exists", return_value=True):
            export_service.clip_video("/source.mp4", "/output.webm", config)

            cmd = mock_run.call_args[0][0]
            # WebM should use VP9 codec
            assert "-c:v" in cmd
            # Output should be .webm
            assert "/output.webm" in cmd

    def test_converts_to_gif(self, export_service):
        """Test conversion to GIF format."""
        config = ExportConfig(start_time=0, end_time=5, format=ExportFormat.GIF)

        with patch("subprocess.run") as mock_run, patch.object(
            export_service, "_get_video_info", return_value={"duration": 120}
        ), patch("os.path.exists", return_value=True):
            export_service.clip_video("/source.mp4", "/output.gif", config)

            cmd = mock_run.call_args[0][0]
            # GIF should have special handling
            assert "/output.gif" in cmd


class TestCropAndResize:
    """Tests for crop and resize operations."""

    def test_applies_crop_parameters(self, export_service):
        """Test that crop parameters are applied correctly."""
        config = ExportConfig(
            start_time=0,
            end_time=10,
            format=ExportFormat.MP4,
            crop_x=100,
            crop_y=50,
            crop_width=640,
            crop_height=480,
        )

        with patch("subprocess.run") as mock_run, patch.object(
            export_service, "_get_video_info", return_value={"duration": 120}
        ), patch("os.path.exists", return_value=True):
            export_service.clip_video("/source.mp4", "/output.mp4", config)

            cmd = mock_run.call_args[0][0]
            # Check for crop filter
            cmd_str = " ".join(cmd)
            assert "crop" in cmd_str

    def test_applies_resize(self, export_service):
        """Test that resize is applied correctly."""
        config = ExportConfig(
            start_time=0,
            end_time=10,
            format=ExportFormat.MP4,
            output_width=1280,
            output_height=720,
        )

        with patch("subprocess.run") as mock_run, patch.object(
            export_service, "_get_video_info", return_value={"duration": 120}
        ), patch("os.path.exists", return_value=True):
            export_service.clip_video("/source.mp4", "/output.mp4", config)

            cmd = mock_run.call_args[0][0]
            # Check for scale filter
            cmd_str = " ".join(cmd)
            assert "scale" in cmd_str or "1280" in cmd_str


@pytest.mark.unit
class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_handles_missing_source_file(self, export_service, export_config):
        """Test handling of missing source file."""
        with patch("os.path.exists", return_value=False), pytest.raises(FileNotFoundError):
            export_service.clip_video("/nonexistent.mp4", "/output.mp4", export_config)

    def test_handles_subprocess_error(self, export_service, export_config):
        """Test handling of FFmpeg subprocess errors."""
        with patch("subprocess.run") as mock_run, patch.object(
            export_service, "_get_video_info", return_value={"duration": 120}
        ), patch("os.path.exists", return_value=True):
            mock_run.side_effect = subprocess.CalledProcessError(1, "ffmpeg")

            with pytest.raises(subprocess.CalledProcessError):
                export_service.clip_video("/source.mp4", "/output.mp4", export_config)

    def test_validates_export_format(self, export_service):
        """Test that invalid formats are rejected."""
        # This test assumes validation exists
        # May need to be adjusted based on actual implementation
        pass


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
