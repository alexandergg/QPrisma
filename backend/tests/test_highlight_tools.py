"""
Tests for agent/tools/highlight_tools.py
=========================================

Tests for the find_highlights tool.
"""

from unittest.mock import MagicMock, patch

import pytest


class TestFindHighlights:
    """Tests for find_highlights tool."""

    @pytest.mark.asyncio
    async def test_no_media_id_returns_error(self):
        from agent.tools.highlight_tools import find_highlights

        result = await find_highlights.ainvoke({"media_id": None})
        assert result["error"]["type"] == "no_context"

    @pytest.mark.asyncio
    async def test_success(self):
        from agent.tools.highlight_tools import find_highlights

        mock_kg = MagicMock()
        mock_detection_result = {
            "highlights": [
                {
                    "start_time": 10.0,
                    "end_time": 25.0,
                    "reason": "High engagement moment",
                    "score": 0.92,
                },
                {
                    "start_time": 60.0,
                    "end_time": 80.0,
                    "reason": "Key discussion topic",
                    "score": 0.87,
                },
            ],
            "total_analyzed_scenes": 15,
        }

        mock_service_instance = MagicMock()
        mock_service_instance.detect_highlights.return_value = mock_detection_result

        with (
            patch(
                "services.knowledge_graph.get_knowledge_graph_service",
                return_value=mock_kg,
            ),
            patch(
                "services.highlight_detection_service.HighlightDetectionService",
                return_value=mock_service_instance,
            ),
        ):
            result = await find_highlights.ainvoke({"media_id": "vid-1"})

        assert len(result["highlights"]) == 2
        assert result["_meta"]["result_count"] == 2

    @pytest.mark.asyncio
    async def test_custom_params_passed(self):
        from agent.tools.highlight_tools import find_highlights

        mock_kg = MagicMock()
        mock_service_instance = MagicMock()
        mock_service_instance.detect_highlights.return_value = {"highlights": []}

        with (
            patch(
                "services.knowledge_graph.get_knowledge_graph_service",
                return_value=mock_kg,
            ),
            patch(
                "services.highlight_detection_service.HighlightDetectionService",
                return_value=mock_service_instance,
            ),
        ):
            await find_highlights.ainvoke(
                {
                    "media_id": "vid-1",
                    "criteria": "action",
                    "max_clips": 3,
                    "min_duration": 15.0,
                    "max_duration": 45.0,
                }
            )

        call_kwargs = mock_service_instance.detect_highlights.call_args[1]
        assert call_kwargs["criteria"] == "action"
        assert call_kwargs["max_clips"] == 3
        assert call_kwargs["min_duration"] == 15.0
        assert call_kwargs["max_duration"] == 45.0

    @pytest.mark.asyncio
    async def test_target_video_id_overrides_media_id(self):
        from agent.tools.highlight_tools import find_highlights

        mock_kg = MagicMock()
        mock_service_instance = MagicMock()
        mock_service_instance.detect_highlights.return_value = {"highlights": []}

        with (
            patch(
                "services.knowledge_graph.get_knowledge_graph_service",
                return_value=mock_kg,
            ),
            patch(
                "services.highlight_detection_service.HighlightDetectionService",
                return_value=mock_service_instance,
            ),
        ):
            await find_highlights.ainvoke(
                {"media_id": "vid-primary", "target_video_id": "vid-target"}
            )

        call_kwargs = mock_service_instance.detect_highlights.call_args[1]
        assert call_kwargs["media_id"] == "vid-target"

    @pytest.mark.asyncio
    async def test_exception_returns_query_error(self):
        from agent.tools.highlight_tools import find_highlights

        with patch(
            "services.knowledge_graph.get_knowledge_graph_service",
            side_effect=RuntimeError("Service init failed"),
        ):
            result = await find_highlights.ainvoke({"media_id": "vid-1"})

        assert result["error"]["type"] == "query_error"

    @pytest.mark.asyncio
    async def test_empty_highlights(self):
        from agent.tools.highlight_tools import find_highlights

        mock_kg = MagicMock()
        mock_service_instance = MagicMock()
        mock_service_instance.detect_highlights.return_value = {"highlights": []}

        with (
            patch(
                "services.knowledge_graph.get_knowledge_graph_service",
                return_value=mock_kg,
            ),
            patch(
                "services.highlight_detection_service.HighlightDetectionService",
                return_value=mock_service_instance,
            ),
        ):
            result = await find_highlights.ainvoke({"media_id": "vid-1"})

        assert result["highlights"] == []
        assert result["_meta"]["result_count"] == 0

    @pytest.mark.asyncio
    async def test_service_receives_kg_instance(self):
        """Verify HighlightDetectionService is instantiated with the KG service."""
        from agent.tools.highlight_tools import find_highlights

        mock_kg = MagicMock()
        mock_cls = MagicMock()
        mock_cls.return_value.detect_highlights.return_value = {"highlights": []}

        with (
            patch(
                "services.knowledge_graph.get_knowledge_graph_service",
                return_value=mock_kg,
            ),
            patch(
                "services.highlight_detection_service.HighlightDetectionService",
                mock_cls,
            ),
        ):
            await find_highlights.ainvoke({"media_id": "vid-1"})

        mock_cls.assert_called_once_with(mock_kg)
