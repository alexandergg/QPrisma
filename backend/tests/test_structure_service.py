"""
Tests for services/structure_service.py

Covers scene title generation, scene summary, video summary, structure resolution,
and chapter building.
"""

from unittest.mock import MagicMock, patch

import pytest

from services.structure_service import StructureService


@pytest.fixture
def structure_service():
    """Create a StructureService with mock dependencies."""
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

    def test_cleans_existing_description_prefixes(self, structure_service):
        scene = {"description": "General scene description: A busy street scene."}
        summary = structure_service._generate_scene_summary(scene, [])
        assert summary == "A busy street scene."

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

    def test_cleans_frame_descriptions_before_joining(self, structure_service):
        frames = [
            {"description": "1. **General description:** A busy street scene."},
            {"description": "Scene description: People walk by storefronts."},
        ]
        summary = structure_service._generate_scene_summary({}, frames)
        assert "General description:" not in summary
        assert "Scene description:" not in summary
        assert "**" not in summary

    def test_truncates_to_500_chars(self, structure_service):
        frames = [{"description": "X" * 300} for _ in range(3)]
        summary = structure_service._generate_scene_summary({}, frames)
        assert len(summary) <= 500


# =============================================================================
# Video Summary Generation
# =============================================================================


@pytest.mark.unit
class TestGenerateVideoSummary:
    def test_cleans_generated_video_summary_prefixes(self, structure_service):
        frames = [
            {"description": "The image shows a crowded plaza.\nPeople carry banners."},
            {"description": "La imagen muestra decorated storefronts."},
        ]
        summary = structure_service._generate_video_summary({}, frames)
        assert "The image shows" not in summary
        assert "La imagen muestra" not in summary
        assert "crowded plaza." in summary


# =============================================================================
# Structure Resolution
# =============================================================================


@pytest.mark.unit
class TestGetStructure:
    def test_prefers_graph_structure(self, structure_service):
        graph_result = {"structure": {"scenes": []}, "processing_method": "graph"}

        with (
            patch.object(
                structure_service,
                "get_structure_from_graph",
                return_value=graph_result,
            ) as graph_mock,
            patch.object(structure_service, "get_structure_from_legacy") as legacy_mock,
        ):
            result = structure_service.get_structure("vid-123", {"structure": {"scenes": []}})

        assert result == graph_result
        graph_mock.assert_called_once_with("vid-123")
        legacy_mock.assert_not_called()

    def test_falls_back_to_legacy_structure(self, structure_service):
        legacy_result = {"structure": {"chapters": []}, "processing_method": "legacy"}
        media_dict = {"structure": {"chapters": []}}

        with (
            patch.object(structure_service, "get_structure_from_graph", return_value=None) as graph_mock,
            patch.object(
                structure_service,
                "get_structure_from_legacy",
                return_value=legacy_result,
            ) as legacy_mock,
        ):
            result = structure_service.get_structure("vid-123", media_dict)

        assert result == legacy_result
        graph_mock.assert_called_once_with("vid-123")
        legacy_mock.assert_called_once_with(media_dict)

    def test_falls_back_to_legacy_when_graph_lookup_raises(self, structure_service):
        legacy_result = {"structure": {"chapters": []}, "processing_method": "legacy"}
        media_dict = {"structure": {"chapters": []}}

        with (
            patch.object(
                structure_service,
                "get_structure_from_graph",
                side_effect=RuntimeError("neo4j unavailable"),
            ) as graph_mock,
            patch.object(
                structure_service,
                "get_structure_from_legacy",
                return_value=legacy_result,
            ) as legacy_mock,
        ):
            result = structure_service.get_structure("vid-123", media_dict)

        assert result == legacy_result
        graph_mock.assert_called_once_with("vid-123")
        legacy_mock.assert_called_once_with(media_dict)

    def test_graph_structure_returns_none_without_graph_service(self):
        service = StructureService(graph_service=None, blob_service=None, storage_container="")
        assert service.get_structure_from_graph("vid-123") is None


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
