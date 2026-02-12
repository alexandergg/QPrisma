"""
Tests for services/chat_service.py

Covers chat with/without media context, context building, and error handling.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from services.chat_service import CHAT_SYSTEM_PROMPT, ChatService


@pytest.mark.unit
class TestChatService:
    @pytest.fixture
    def chat_service(self, mock_openai_client, mock_graph_search_service):
        return ChatService(
            openai_client=mock_openai_client,
            graph_search_service=mock_graph_search_service,
        )

    async def test_chat_without_media(self, chat_service, mock_openai_client):
        """Chat without media_id should not search for context."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content="General response"))]
        mock_openai_client.chat.completions.create = AsyncMock(return_value=mock_response)

        response, sources = await chat_service.chat(message="hello", media_id=None)

        assert response == "General response"
        assert sources == []

    async def test_chat_with_media_id(self, chat_service, mock_openai_client, mock_graph_search_service):
        """Chat with media_id should search for video context."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content="Video-specific answer"))]
        mock_openai_client.chat.completions.create = AsyncMock(return_value=mock_response)

        # Mock the graph search to return results
        mock_graph_search_service.hybrid_search = AsyncMock(
            return_value=MagicMock(results=[], total_results=0)
        )
        mock_graph_search_service.graph_service = MagicMock(is_connected=True)
        mock_session = MagicMock()
        mock_session.run.return_value = MagicMock(single=MagicMock(return_value=None))
        mock_graph_search_service.graph_service.get_session.return_value.__enter__ = MagicMock(
            return_value=mock_session
        )
        mock_graph_search_service.graph_service.get_session.return_value.__exit__ = MagicMock(
            return_value=False
        )

        response, sources = await chat_service.chat(message="what happens?", media_id="vid_123")

        assert response == "Video-specific answer"

    async def test_chat_error_handling(self, chat_service, mock_openai_client):
        """OpenAI errors should propagate."""
        mock_openai_client.chat.completions.create = AsyncMock(
            side_effect=Exception("API Error")
        )

        with pytest.raises(Exception, match="API Error"):
            await chat_service.chat(message="hello", media_id=None)


@pytest.mark.unit
class TestSystemPrompt:
    def test_system_prompt_exists(self):
        assert len(CHAT_SYSTEM_PROMPT) > 100

    def test_system_prompt_mentions_timestamps(self):
        assert "timestamp" in CHAT_SYSTEM_PROMPT.lower()


@pytest.mark.unit
class TestLoadVideoSummary:
    async def test_returns_empty_when_not_connected(self, mock_openai_client, mock_graph_search_service):
        mock_graph_search_service.graph_service.is_connected = False
        service = ChatService(mock_openai_client, mock_graph_search_service)
        summary, topics = await service._load_video_summary("vid_123")
        assert summary == ""
        assert topics == []

    async def test_returns_empty_on_exception(self, mock_openai_client, mock_graph_search_service):
        mock_graph_search_service.graph_service.is_connected = True
        mock_graph_search_service.graph_service.get_session.side_effect = Exception("Connection error")
        service = ChatService(mock_openai_client, mock_graph_search_service)
        summary, topics = await service._load_video_summary("vid_123")
        assert summary == ""
        assert topics == []
