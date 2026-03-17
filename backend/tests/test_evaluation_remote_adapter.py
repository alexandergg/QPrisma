"""Tests for remote evaluation adapters."""

import httpx
import pytest
import respx

from evaluation.adapters.remote_adapter import (
    RemoteDirectSearchAdapter,
    RemoteQPrismaAdapter,
    get_auth_token,
)
from evaluation.models.eval_schemas import BenchmarkEntry


@pytest.fixture
def sample_entry():
    return BenchmarkEntry(
        question_id="001-1",
        video_id="test-uuid-123",
        question="What color is the car?",
        choices=["A. Red", "B. Blue", "C. Green", "D. Yellow"],
        correct_answer="B",
        category="Attribute Perception",
        domain="Knowledge",
        benchmark="video-mme",
    )


@pytest.fixture
def api_url():
    return "https://test-api.example.com"


class TestGetAuthToken:
    @respx.mock
    @pytest.mark.asyncio
    async def test_successful_login(self, api_url):
        respx.post(f"{api_url}/auth/login").mock(
            return_value=httpx.Response(
                200,
                json={
                    "access_token": "test-jwt-token",
                    "token_type": "bearer",
                    "expires_in": 86400,
                },
            )
        )

        token = await get_auth_token(api_url, "user@test.com", "password")
        assert token == "test-jwt-token"

    @respx.mock
    @pytest.mark.asyncio
    async def test_failed_login(self, api_url):
        respx.post(f"{api_url}/auth/login").mock(
            return_value=httpx.Response(401, json={"detail": "Invalid credentials"})
        )

        with pytest.raises(httpx.HTTPStatusError):
            await get_auth_token(api_url, "bad@test.com", "wrong")


class TestRemoteQPrismaAdapter:
    @pytest.fixture
    def adapter(self, api_url):
        return RemoteQPrismaAdapter(
            api_url=api_url,
            token="test-token",
            timeout=30.0,
        )

    def test_name_and_display_name(self, adapter):
        assert adapter.name == "qprisma-remote"
        assert adapter.display_name == "QPrisma Agent (Remote)"

    @respx.mock
    @pytest.mark.asyncio
    async def test_generate_answer_success(self, adapter, sample_entry, api_url):
        respx.post(f"{api_url}/chat/agent").mock(
            return_value=httpx.Response(
                200,
                json={
                    "response": "The answer is B. The car is blue.",
                    "sources": [{"timestamp": 10.0, "content": "blue car"}],
                    "tool_calls_made": 3,
                    "token_usage": {"total_tokens": 500},
                },
            )
        )

        await adapter.setup()
        try:
            result = await adapter.generate_answer(sample_entry)

            assert result.question_id == "001-1"
            assert result.method == "qprisma-remote"
            assert "blue" in result.answer.lower()
            assert result.predicted_choice == "B"
            assert result.tool_calls == 3
            assert result.tokens_used == 500
            assert result.error is None
            assert result.latency_ms > 0
        finally:
            await adapter.teardown()

    @respx.mock
    @pytest.mark.asyncio
    async def test_generate_answer_timeout(self, adapter, sample_entry, api_url):
        respx.post(f"{api_url}/chat/agent").mock(side_effect=httpx.ReadTimeout("timeout"))

        await adapter.setup()
        try:
            result = await adapter.generate_answer(sample_entry)
            assert result.error is not None
            assert "Timeout" in result.error
        finally:
            await adapter.teardown()

    @respx.mock
    @pytest.mark.asyncio
    async def test_generate_answer_http_error(self, adapter, sample_entry, api_url):
        respx.post(f"{api_url}/chat/agent").mock(
            return_value=httpx.Response(500, text="Internal Server Error")
        )

        await adapter.setup()
        try:
            result = await adapter.generate_answer(sample_entry)
            assert result.error is not None
            assert "500" in result.error
        finally:
            await adapter.teardown()


class TestRemoteDirectSearchAdapter:
    @pytest.fixture
    def adapter(self, api_url):
        return RemoteDirectSearchAdapter(
            api_url=api_url,
            token="test-token",
            timeout=30.0,
        )

    def test_name_and_display_name(self, adapter):
        assert adapter.name == "direct-search-remote"
        assert adapter.display_name == "Direct Search (Remote)"

    @respx.mock
    @pytest.mark.asyncio
    async def test_generate_answer_with_results(self, adapter, sample_entry, api_url):
        respx.post(f"{api_url}/search").mock(
            return_value=httpx.Response(
                200,
                json={
                    "query": "test",
                    "results": [
                        {
                            "timestamp": 5.0,
                            "content": "A blue car is driving on the road",
                            "score": 0.95,
                            "type": "visual",
                        },
                        {
                            "timestamp": 12.0,
                            "content": "The blue vehicle turns left",
                            "score": 0.88,
                            "type": "visual",
                        },
                    ],
                    "total": 2,
                },
            )
        )

        await adapter.setup()
        try:
            result = await adapter.generate_answer(sample_entry)

            assert result.question_id == "001-1"
            assert result.method == "direct-search-remote"
            assert result.predicted_choice is not None
            assert result.error is None
            assert result.retrieved_context is not None
        finally:
            await adapter.teardown()

    @respx.mock
    @pytest.mark.asyncio
    async def test_generate_answer_empty_results(self, adapter, sample_entry, api_url):
        respx.post(f"{api_url}/search").mock(
            return_value=httpx.Response(
                200,
                json={"query": "test", "results": [], "total": 0},
            )
        )

        await adapter.setup()
        try:
            result = await adapter.generate_answer(sample_entry)
            assert result.question_id == "001-1"
            assert result.error is None
        finally:
            await adapter.teardown()


class TestMCChoiceExtraction:
    """Test MC choice extraction through the adapter."""

    @pytest.fixture
    def adapter(self, api_url):
        return RemoteQPrismaAdapter(api_url=api_url, token="t")

    @pytest.mark.parametrize(
        "answer,expected",
        [
            ("B", "B"),
            ("(C)", "C"),
            ("The answer is A", "A"),
            ("Answer: D", "D"),
            ("B. Blue", "B"),
            ("**A**", "A"),
        ],
    )
    def test_extract_mc_choice(self, adapter, answer, expected):
        choices = ["A. Red", "B. Blue", "C. Green", "D. Yellow"]
        assert adapter.extract_mc_choice(answer, choices) == expected
