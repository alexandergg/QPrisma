"""
Tests for services/structure_service.py

Covers scene title generation, scene summary, and chapter building.
"""

import pytest

from services.structure_service import StructureService


@pytest.fixture
def structure_service():
    """Create a StructureService with mock dependencies."""
    from unittest.mock import MagicMock

    return StructureService(graph_service=MagicMock(), blob_service=None, storage_container="")


# =============================================================================
# Scene Title Generation
# =============================================================================


@pytest.mark.unit
class TestGenerateSceneTitle:
    def test_returns_existing_title(self, structure_service):
        scene = {"title": "Existing Title"}
        assert structure_service._generate_scene_title(scene, []) == "Existing Title"

    def test_generates_from_first_frame(self, structure_service):
        scene = {}
        frames = [{"description": "A person walking in the park."}]
        title = structure_service._generate_scene_title(scene, frames)
        assert title == "A person walking in the park"

    def test_returns_none_for_empty_frames(self, structure_service):
        assert structure_service._generate_scene_title({}, []) is None

    def test_returns_none_for_empty_description(self, structure_service):
        assert structure_service._generate_scene_title({}, [{"description": ""}]) is None

    def test_cleans_markdown_formatting(self, structure_service):
        frames = [{"description": "1. **Bold text** here."}]
        title = structure_service._generate_scene_title({}, frames)
        assert "**" not in title
        assert title is not None

    def test_strips_common_prefixes(self, structure_service):
        frames = [{"description": "General description: A busy street scene."}]
        title = structure_service._generate_scene_title({}, frames)
        assert "General description:" not in title

    def test_truncates_long_titles(self, structure_service):
        frames = [{"description": "A" * 200 + "."}]
        title = structure_service._generate_scene_title({}, frames)
        assert len(title) <= 100


# =============================================================================
# Scene Summary Generation
# =============================================================================


@pytest.mark.unit
class TestGenerateSceneSummary:
    def test_returns_existing_description(self, structure_service):
        scene = {"description": "Existing summary."}
        assert structure_service._generate_scene_summary(scene, []) == "Existing summary."

    def test_generates_from_frames(self, structure_service):
        frames = [
            {"description": "Frame 1 desc."},
            {"description": "Frame 2 desc."},
        ]
        summary = structure_service._generate_scene_summary({}, frames)
        assert "Frame 1 desc." in summary
        assert "Frame 2 desc." in summary

    def test_returns_none_for_empty_frames(self, structure_service):
        assert structure_service._generate_scene_summary({}, []) is None

    def test_uses_max_3_frames(self, structure_service):
        frames = [{"description": f"Frame {i}."} for i in range(10)]
        summary = structure_service._generate_scene_summary({}, frames)
        # Should only include first 3 frames
        assert "Frame 0." in summary
        assert "Frame 2." in summary

    def test_truncates_to_500_chars(self, structure_service):
        frames = [{"description": "X" * 300} for _ in range(3)]
        summary = structure_service._generate_scene_summary({}, frames)
        assert len(summary) <= 500


# =============================================================================
# Chapter Building
# =============================================================================


@pytest.mark.unit
class TestBuildChapters:
    def test_empty_scenes(self, structure_service):
        assert structure_service._build_chapters([]) == []

    def test_groups_scenes(self, structure_service):
        scenes = [
            {"title": f"Scene {i}", "start_time": i * 10, "end_time": (i + 1) * 10, "scene_id": i}
            for i in range(12)
        ]
        chapters = structure_service._build_chapters(scenes, max_scenes_per_chapter=5)
        assert len(chapters) == 3  # 5 + 5 + 2

    def test_single_scene(self, structure_service):
        scenes = [{"title": "Only Scene", "start_time": 0, "end_time": 10, "scene_id": 0}]
        chapters = structure_service._build_chapters(scenes)
        assert len(chapters) == 1

    def test_chapter_title_from_first_scene(self, structure_service):
        scenes = [
            {"title": "Introduction to Topic", "start_time": 0, "end_time": 30, "scene_id": 0},
            {"title": "Details", "start_time": 30, "end_time": 60, "scene_id": 1},
        ]
        chapters = structure_service._build_chapters(scenes, max_scenes_per_chapter=5)
        assert chapters[0]["title"] == "Introduction to Topic"

    def test_chapter_title_fallback(self, structure_service):
        scenes = [{"title": "", "start_time": 0, "end_time": 10, "scene_id": 0}]
        chapters = structure_service._build_chapters(scenes, max_scenes_per_chapter=5)
        assert "Part" in chapters[0]["title"]
