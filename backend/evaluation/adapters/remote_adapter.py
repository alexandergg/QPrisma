"""
Remote HTTP adapters for QPrisma evaluation.

These adapters call the QPrisma API over HTTP, enabling evaluation
against remote deployments (e.g., Azure Container Apps).
"""

import asyncio
import logging
import time
import uuid

import httpx

from evaluation.adapters.base import BaseMethodAdapter
from evaluation.models.eval_schemas import BenchmarkEntry, EvalResult

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 180.0
MAX_RETRIES = 3
RETRY_BACKOFF = 2.0


async def get_auth_token(api_url: str, email: str, password: str) -> str:
    """Authenticate against QPrisma API and return a JWT token.

    Args:
        api_url: Base URL of the QPrisma API.
        email: User email.
        password: User password.

    Returns:
        JWT access token string.

    Raises:
        httpx.HTTPStatusError: If authentication fails.
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{api_url.rstrip('/')}/auth/login",
            json={"email": email, "password": password},
        )
        resp.raise_for_status()
        return resp.json()["access_token"]


class RemoteQPrismaAdapter(BaseMethodAdapter):
    """Calls POST /chat/agent on a remote QPrisma API.

    Triggers the full LangGraph video agent pipeline including
    tool selection, knowledge graph queries, and multi-hop reasoning.
    """

    def __init__(
        self,
        api_url: str,
        token: str,
        timeout: float = DEFAULT_TIMEOUT,
    ):
        self.api_url = api_url.rstrip("/")
        self.token = token
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None

    @property
    def name(self) -> str:
        return "qprisma-remote"

    @property
    def display_name(self) -> str:
        return "QPrisma Agent (Remote)"

    async def setup(self) -> None:
        self._client = httpx.AsyncClient(
            base_url=self.api_url,
            headers={"Authorization": f"Bearer {self.token}"},
            timeout=httpx.Timeout(self.timeout),
        )

    async def teardown(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def generate_answer(
        self,
        entry: BenchmarkEntry,
        video_path: str | None = None,
    ) -> EvalResult:
        query = self.build_mc_query(entry)
        session_id = str(uuid.uuid4())

        start = time.perf_counter()
        data = await self._call_agent(query, entry.video_id, session_id)
        latency_ms = (time.perf_counter() - start) * 1000

        answer = data.get("response", "")
        predicted_choice = self.extract_mc_choice(answer, entry.choices)
        timestamps = self.extract_timestamps(answer)

        token_usage = data.get("token_usage") or {}

        return EvalResult(
            question_id=entry.question_id,
            method=self.name,
            answer=answer,
            predicted_choice=predicted_choice,
            predicted_timestamps=timestamps or None,
            latency_ms=latency_ms,
            tool_calls=data.get("tool_calls_made"),
            tokens_used=token_usage.get("total_tokens"),
            error=data.get("error"),
            metadata={
                "sources_count": len(data.get("sources", [])),
                "session_id": session_id,
            },
        )

    async def _call_agent(
        self,
        query: str,
        video_id: str,
        session_id: str,
    ) -> dict:
        """Call POST /chat/agent with retry logic."""
        assert self._client is not None, "Call setup() first"

        payload = {
            "message": query,
            "media_id": video_id,
            "session_id": session_id,
        }

        for attempt in range(MAX_RETRIES):
            try:
                resp = await self._client.post("/chat/agent", json=payload)
                resp.raise_for_status()
                return resp.json()
            except httpx.TimeoutException:
                logger.warning(
                    "Timeout attempt %d/%d for question on video %s",
                    attempt + 1,
                    MAX_RETRIES,
                    video_id,
                )
                if attempt == MAX_RETRIES - 1:
                    return {"response": "", "error": "Timeout after all retries"}
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429:
                    wait = RETRY_BACKOFF ** (attempt + 1)
                    logger.warning("Rate limited, waiting %.1fs", wait)
                    await asyncio.sleep(wait)
                    continue
                logger.error(
                    "HTTP %d: %s",
                    e.response.status_code,
                    e.response.text[:200],
                )
                return {
                    "response": "",
                    "error": f"HTTP {e.response.status_code}",
                }
            except httpx.HTTPError as e:
                logger.error("HTTP error: %s", e)
                if attempt == MAX_RETRIES - 1:
                    return {"response": "", "error": str(e)}

            await asyncio.sleep(RETRY_BACKOFF**attempt)

        return {"response": "", "error": "Max retries exceeded"}


class RemoteDirectSearchAdapter(BaseMethodAdapter):
    """Calls POST /search on a remote QPrisma API.

    Baseline adapter that performs direct search retrieval without
    the full agent reasoning pipeline. Useful as a comparison point
    to measure the value added by the LangGraph agent.
    """

    def __init__(
        self,
        api_url: str,
        token: str,
        timeout: float = 60.0,
    ):
        self.api_url = api_url.rstrip("/")
        self.token = token
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None

    @property
    def name(self) -> str:
        return "direct-search-remote"

    @property
    def display_name(self) -> str:
        return "Direct Search (Remote)"

    async def setup(self) -> None:
        self._client = httpx.AsyncClient(
            base_url=self.api_url,
            headers={"Authorization": f"Bearer {self.token}"},
            timeout=httpx.Timeout(self.timeout),
        )

    async def teardown(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def generate_answer(
        self,
        entry: BenchmarkEntry,
        video_path: str | None = None,
    ) -> EvalResult:
        query = self.build_mc_query(entry)

        start = time.perf_counter()
        data = await self._search(query, entry.video_id)
        latency_ms = (time.perf_counter() - start) * 1000

        # Build answer from search results
        results = data.get("results", [])
        if results:
            context_parts = [
                f"[{r.get('type', 'unknown')} @ {r.get('timestamp', 0):.1f}s] {r.get('content', '')}"
                for r in results[:10]
            ]
            answer = self._pick_choice_from_context(query, "\n".join(context_parts), entry.choices)
        else:
            answer = ""

        predicted_choice = self.extract_mc_choice(answer, entry.choices)
        timestamps = self.extract_timestamps(answer)

        return EvalResult(
            question_id=entry.question_id,
            method=self.name,
            answer=answer,
            predicted_choice=predicted_choice,
            predicted_timestamps=timestamps or None,
            latency_ms=latency_ms,
            retrieved_context="\n".join(r.get("content", "") for r in results[:5]),
            error=data.get("error"),
            metadata={
                "search_results_count": len(results),
            },
        )

    def _pick_choice_from_context(
        self,
        query: str,
        context: str,
        choices: list[str] | None,
    ) -> str:
        """Select the best MC choice by keyword overlap with search context.

        This is intentionally simple — it's the naive baseline.
        """
        if not choices:
            return context[:500]

        context_lower = context.lower()
        best_letter = "A"
        best_score = -1

        for i, choice in enumerate(choices):
            clean = choice.strip()
            # Strip letter prefix
            for prefix in [f"{chr(65+i)}.", f"{chr(65+i)})"]:
                if clean.startswith(prefix):
                    clean = clean[len(prefix) :].strip()
                    break

            words = [w for w in clean.lower().split() if len(w) > 3]
            score = sum(1 for w in words if w in context_lower)
            if score > best_score:
                best_score = score
                best_letter = chr(65 + i)

        return best_letter

    async def _search(self, query: str, video_id: str) -> dict:
        """Call POST /search with retry logic."""
        assert self._client is not None, "Call setup() first"

        payload = {
            "query": query,
            "media_id": video_id,
            "limit": 20,
        }

        for attempt in range(MAX_RETRIES):
            try:
                resp = await self._client.post("/search", json=payload)
                resp.raise_for_status()
                return resp.json()
            except httpx.TimeoutException:
                logger.warning(
                    "Search timeout attempt %d/%d for video %s",
                    attempt + 1,
                    MAX_RETRIES,
                    video_id,
                )
                if attempt == MAX_RETRIES - 1:
                    return {"results": [], "error": "Search timeout"}
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429:
                    wait = RETRY_BACKOFF ** (attempt + 1)
                    logger.warning("Rate limited, waiting %.1fs", wait)
                    await asyncio.sleep(wait)
                    continue
                return {
                    "results": [],
                    "error": f"HTTP {e.response.status_code}",
                }
            except httpx.HTTPError as e:
                logger.error("Search error: %s", e)
                if attempt == MAX_RETRIES - 1:
                    return {"results": [], "error": str(e)}

            await asyncio.sleep(RETRY_BACKOFF**attempt)

        return {"results": [], "error": "Max retries exceeded"}
