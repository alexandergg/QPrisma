"""Tests for retained legacy compatibility paths.

Validates that retained compatibility paths still work while new graph/A2A
paths remain preferred.
"""

from unittest.mock import MagicMock

import pytest

from services.structure_service import StructureService


@pytest.mark.unit
class TestLegacyStructureIntegration:
    """Tests for legacy structure fallback paths."""

    def test_old_media_uses_legacy_structure_data(self):
        """Verify pre-graph media uses PostgreSQL structure fallback.

        This validates the critical path for videos processed before
        Neo4j graph ingestion was available. The structure_service should
        gracefully degrade to returning the legacy processing_result when
        no graph data exists.
        """
        old_media_dict = {
            "id": "old-vid-123",
            "user_id": "user-456",
            "processing_method": "legacy_frame_batch",
            "upload_date": "2024-06-01T00:00:00Z",
            "processing_result": {
                "structure": {
                    "scenes": [
                        {
                            "scene_id": 0,
                            "title": "Opening Scene",
                            "start_time": 0.0,
                            "end_time": 30.0,
                            "summary": "Establishing shots of the location.",
                        }
                    ],
                    "chapters": [
                        {
                            "chapter_id": 0,
                            "title": "Introduction",
                            "start_time": 0.0,
                            "end_time": 30.0,
                        }
                    ],
                }
            },
        }

        graph_service = MagicMock()
        graph_service.get_video_node.return_value = None

        service = StructureService(graph_service=graph_service)
        result = service.get_structure("old-vid-123", old_media_dict)

        assert result is not None
        assert result["processing_method"] == "legacy_frame_batch"
        assert len(result["structure"]["scenes"]) == 1
        assert result["structure"]["scenes"][0]["title"] == "Opening Scene"
        assert result.get("_legacy_path") is True

    def test_graph_media_ignores_legacy_structure(self):
        """Verify graph data takes precedence over legacy structure.

        When a video has been ingested into the Neo4j graph, the structure
        service should prefer graph data and never fall back to the legacy
        PostgreSQL structure, even if it exists.
        """
        media_dict = {
            "id": "vid-123",
            "user_id": "user-456",
            "processing_result": {
                "structure": {
                    "scenes": [
                        {"scene_id": 0, "title": "Legacy Scene (Should Be Ignored)"}
                    ]
                }
            },
        }

        graph_service = MagicMock()
        graph_service.get_video_node.return_value = {
            "video_id": "vid-123",
            "title": "Graph Video Title",
            "summary": "Graph-computed summary",
        }
        graph_service.get_video_scenes.return_value = [
            {
                "scene_index": 0,
                "start_time": 0.0,
                "end_time": 30.0,
                "title": "Graph Scene",
                "description": "Graph-extracted description",
            }
        ]

        service = StructureService(graph_service=graph_service)
        result = service.get_structure("vid-123", media_dict)

        assert result is not None
        assert "Graph Scene" in str(result)
        assert result.get("_legacy_path") is not True

    def test_missing_graph_missing_legacy_returns_none(self):
        """Verify None is returned when neither graph nor legacy exists.

        Tests the case where a media record has no structure data from either
        source. This typically occurs for very new media or corrupted records.
        """
        media_dict = {
            "id": "vid-123",
            "user_id": "user-456",
            "processing_result": {},  # No structure
        }

        graph_service = MagicMock()
        graph_service.get_video_node.return_value = None

        service = StructureService(graph_service=graph_service)
        result = service.get_structure("vid-123", media_dict)

        assert result is None

    def test_graph_exception_triggers_legacy_fallback(self):
        """Verify legacy fallback is used when graph lookup raises.

        The structure service should gracefully handle graph service errors
        and fall back to legacy data. This ensures availability even when
        the Neo4j connection is temporarily unavailable.
        """
        media_dict = {
            "id": "vid-123",
            "user_id": "user-456",
            "processing_result": {
                "structure": {
                    "scenes": [{"scene_id": 0, "title": "Fallback Scene"}]
                }
            },
        }

        graph_service = MagicMock()
        graph_service.get_video_node.side_effect = RuntimeError("Neo4j connection lost")

        service = StructureService(graph_service=graph_service)
        result = service.get_structure("vid-123", media_dict)

        assert result is not None
        assert result["structure"]["scenes"][0]["title"] == "Fallback Scene"
        assert result.get("_legacy_path") is True

    def test_legacy_structure_from_nested_processing_result(self):
        """Verify legacy structure is extracted from nested processing_result.

        Some older media records may store structure inside the
        processing_result JSON column rather than at the top level.
        """
        media_dict = {
            "id": "vid-123",
            "user_id": "user-456",
            "processing_result": {
                "frames_analyzed": 100,
                "structure": {"scenes": [{"scene_id": 0, "title": "Nested Scene"}]},
            },
        }

        graph_service = MagicMock()
        graph_service.get_video_node.return_value = None

        service = StructureService(graph_service=graph_service)
        result = service.get_structure("vid-123", media_dict)

        assert result is not None
        assert result["structure"]["scenes"][0]["title"] == "Nested Scene"


@pytest.mark.unit
class TestLegacyEnvelopeExtraction:
    """Test envelope extraction and backward compatibility."""

    def test_extract_legacy_context_from_old_evaluation(self):
        """Verify old Video-MME evaluation format still parses.

        The legacy QPRISMA_CONTEXT envelope format was used by the Video-MME
        evaluation pipeline. This test ensures backward compatibility with
        existing evaluation data and offline evaluation re-runs.
        """
        from agent.hosted.context_envelope import extract_qprisma_context

        old_eval_message = (
            '[QPRISMA_CONTEXT:{"media_ids":["vid-1","vid-2"],"user_id":"user-x"}]\n'
            "Question: Summarize both videos."
        )

        metadata, cleaned = extract_qprisma_context(old_eval_message)

        assert metadata["media_ids"] == ["vid-1", "vid-2"]
        assert metadata["user_id"] == "user-x"
        assert cleaned == "Question: Summarize both videos."

    def test_extract_new_base64_context_preferred(self):
        """Verify new base64 format is produced by generator.

        The format_qprisma_context() function should always emit the new
        base64-encoded format, which is more robust against JSON edge cases.
        """
        from agent.hosted.context_envelope import (
            extract_qprisma_context,
            format_qprisma_context,
        )

        metadata = {
            "media_id": "vid-1",
            "user_id": "user-x",
        }

        formatted = format_qprisma_context(metadata, "Test message")

        assert "[QPRISMA_CONTEXT_B64:" in formatted

        extracted, cleaned = extract_qprisma_context(formatted)
        assert extracted == metadata
        assert cleaned == "Test message"

    def test_malformed_legacy_graceful_fallback(self):
        """Verify malformed legacy envelope is handled gracefully.

        If a legacy envelope has malformed JSON, the parser should return
        empty metadata and the original text, allowing the message to still
        be processed (though without context).
        """
        from agent.hosted.context_envelope import extract_qprisma_context

        malformed = "[QPRISMA_CONTEXT:{bad json}]\nQuestion"

        metadata, cleaned = extract_qprisma_context(malformed)

        assert metadata == {}
        assert cleaned == malformed

    def test_legacy_array_payloads_supported(self):
        """Verify legacy format supports array payloads.

        Multi-video queries use media_ids arrays. Legacy envelope extraction
        must preserve these arrays correctly.
        """
        from agent.hosted.context_envelope import extract_qprisma_context

        message = (
            '[QPRISMA_CONTEXT:{"media_ids":["v1","v2","v3"],"user_id":"u1"}]\n'
            "Compare these videos"
        )

        metadata, cleaned = extract_qprisma_context(message)

        assert metadata["media_ids"] == ["v1", "v2", "v3"]
        assert metadata["user_id"] == "u1"
        assert cleaned == "Compare these videos"

    def test_legacy_context_with_adjacent_benchmark_envelope(self):
        """Verify legacy QPRISMA_CONTEXT coexists with QPRISMA_BENCH.

        Video-MME evaluation embeds both context and benchmark envelopes.
        The context envelope extraction should work even with benchmark
        envelope present (benchmark is handled separately).
        """
        from agent.hosted.context_envelope import extract_qprisma_context

        combined = (
            '[QPRISMA_CONTEXT:{"media_ids":["vid-1"],"user_id":"user-x"}]\n'
            '[QPRISMA_BENCH:{"eval_mode":"mcq","format":"letter_only"}]\n'
            "Question"
        )

        metadata, cleaned = extract_qprisma_context(combined)

        assert metadata["media_ids"] == ["vid-1"]
        assert metadata["user_id"] == "user-x"
        assert "[QPRISMA_BENCH:" in cleaned

    def test_new_base64_format_edge_cases(self):
        """Verify base64 format handles JSON edge cases gracefully."""
        from agent.hosted.context_envelope import (
            extract_qprisma_context,
            format_qprisma_context,
        )

        metadata = {
            "media_id": 'vid-"special-chars"',
            "user_id": "user-{with}[brackets]",
            "custom_field": "value\nwith\nnewlines",
        }

        formatted = format_qprisma_context(metadata, "Test")

        extracted, _ = extract_qprisma_context(formatted)

        assert extracted["media_id"] == metadata["media_id"]
        assert extracted["user_id"] == metadata["user_id"]
        assert extracted["custom_field"] == metadata["custom_field"]


@pytest.mark.unit
class TestLegacyDeprecationMarkers:
    """Test that legacy paths are properly marked for deprecation."""

    def test_legacy_structure_result_includes_marker(self):
        """Verify legacy structure results include deprecation marker.

        Clients and monitoring systems should be able to detect when
        legacy paths are being used via the _legacy_path marker.
        """
        media_dict = {
            "id": "vid-123",
            "user_id": "user-456",
            "processing_result": {
                "structure": {"scenes": [], "chapters": []}
            },
        }

        graph_service = MagicMock()
        graph_service.get_video_node.return_value = None

        service = StructureService(graph_service=graph_service)
        result = service.get_structure("vid-123", media_dict)

        assert result.get("_legacy_path") is True

    def test_graph_structure_does_not_include_legacy_marker(self):
        """Verify graph structure results do NOT include legacy marker."""
        graph_service = MagicMock()
        graph_service.get_video_node.return_value = {
            "video_id": "vid-123",
            "title": "Video",
        }
        graph_service.get_video_scenes.return_value = [
            {
                "scene_index": 0,
                "start_time": 0.0,
                "end_time": 30.0,
                "title": "Scene 1",
            }
        ]

        service = StructureService(graph_service=graph_service)
        result = service.get_structure("vid-123", {})

        assert result is not None
        assert result.get("_legacy_path") is not True
        assert result.get("_legacy_path") is None
