"""
Enhanced Search Service
=======================
Advanced search with re-ranking, context expansion, and intelligent result grouping.

Features:
- Hybrid search (vector + BM25 text)
- LLM-based re-ranking for better relevance
- Scene-aware context expansion
- Temporal result clustering
- Cross-video search capability
- Query understanding and expansion
"""

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any

from openai import AzureOpenAI

from core.config import create_azure_openai_client, get_settings
from models.graph_models import NodeType
from services.graph_search_service import get_graph_search_service

logger = logging.getLogger(__name__)


@dataclass
class SearchResult:
    """Enhanced search result with context."""

    id: str
    media_id: str
    score: float
    rerank_score: float | None

    # Content
    content: str
    summary: str | None
    title: str | None

    # Temporal info
    timestamp: float
    start_time: float | None
    end_time: float | None
    scene_id: int | None

    # Context
    context_before: str | None = None
    context_after: str | None = None

    # Metadata
    detected_objects: list[str] = None
    transcript_segment: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "media_id": self.media_id,
            "score": self.score,
            "rerank_score": self.rerank_score,
            "content": self.content,
            "summary": self.summary,
            "title": self.title,
            "timestamp": self.timestamp,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "scene_id": self.scene_id,
            "context_before": self.context_before,
            "context_after": self.context_after,
            "detected_objects": self.detected_objects or [],
            "transcript_segment": self.transcript_segment,
        }


@dataclass
class SearchResponse:
    """Complete search response with metadata."""

    query: str
    query_intent: str | None
    total_results: int
    results: list[SearchResult]

    # Grouping
    temporal_clusters: list[dict[str, Any]]
    scene_groups: list[dict[str, Any]]

    # Metadata
    search_time_ms: float
    used_reranking: bool
    search_type: str  # 'hybrid', 'vector', 'text'

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "query_intent": self.query_intent,
            "total_results": self.total_results,
            "results": [r.to_dict() for r in self.results],
            "temporal_clusters": self.temporal_clusters,
            "scene_groups": self.scene_groups,
            "search_time_ms": self.search_time_ms,
            "used_reranking": self.used_reranking,
            "search_type": self.search_type,
        }


class QueryUnderstanding:
    """Understands and expands user queries for better search."""

    def __init__(self, openai_client: AzureOpenAI | None = None):
        self.client = openai_client or create_azure_openai_client()
        self.deployment = get_settings().azure.openai_deployment_gpt

    async def analyze_query(self, query: str) -> dict[str, Any]:
        """
        Analyze query to understand intent and extract key concepts.
        """
        prompt = f"""Analyze this video search query and provide:
1. Intent: What is the user looking for? (object, action, scene, event, person, text, time-based)
2. Key concepts: Main searchable terms
3. Expanded terms: Synonyms and related terms
4. Temporal hints: Any time-related aspects (beginning, end, after X, etc.)

Query: "{query}"

Respond in JSON:
{{
    "intent": "...",
    "key_concepts": ["...", "..."],
    "expanded_terms": ["...", "..."],
    "temporal_hint": "...",
    "is_specific": true/false
}}"""

        try:
            response = self.client.chat.completions.create(
                model=self.deployment,
                messages=[
                    {
                        "role": "system",
                        "content": "You are a search query analyzer for video content.",
                    },
                    {"role": "user", "content": prompt},
                ],
                max_tokens=200,
                temperature=0.1,
                response_format={"type": "json_object"},
            )

            return json.loads(response.choices[0].message.content)

        except Exception as e:
            logger.error(f"Query analysis error: {e}")
            return {
                "intent": "general",
                "key_concepts": [query],
                "expanded_terms": [],
                "temporal_hint": None,
                "is_specific": False,
            }

    def expand_query(self, query: str, analysis: dict[str, Any]) -> str:
        """
        Expand query with additional terms for better recall.
        """
        parts = [query]

        # Add key concepts
        for concept in analysis.get("key_concepts", [])[:3]:
            if concept.lower() not in query.lower():
                parts.append(concept)

        # Add expanded terms
        for term in analysis.get("expanded_terms", [])[:2]:
            if term.lower() not in query.lower():
                parts.append(term)

        return " ".join(parts)


class ReRanker:
    """
    Re-ranks search results using LLM for better relevance.

    Uses GPT-4o to score relevance of each result to the query,
    improving precision over pure vector/text similarity.
    """

    def __init__(self, openai_client: AzureOpenAI | None = None):
        self.client = openai_client or create_azure_openai_client()
        self.deployment = get_settings().azure.openai_deployment_gpt

    async def rerank(
        self, query: str, results: list[dict[str, Any]], top_k: int = 10
    ) -> list[dict[str, Any]]:
        """
        Re-rank results using LLM relevance scoring.
        """
        if not results:
            return []

        # Prepare candidates (limit to avoid token limits)
        candidates = results[: min(20, len(results))]

        # Format for LLM
        candidate_texts = []
        for i, r in enumerate(candidates):
            content = r.get("content", r.get("summary", ""))[:300]
            candidate_texts.append(f"{i}. {content}")

        candidates_str = "\n".join(candidate_texts)

        prompt = f"""Given this search query about video content:
Query: "{query}"

Rank these video segments by relevance (most relevant first).
Return ONLY the indices of the top {top_k} most relevant results, in order.

Candidates:
{candidates_str}

Respond with JSON array of indices:
{{"rankings": [index1, index2, ...]}}"""

        try:
            response = self.client.chat.completions.create(
                model=self.deployment,
                messages=[
                    {
                        "role": "system",
                        "content": "You are a relevance ranking system. Return only the requested JSON.",
                    },
                    {"role": "user", "content": prompt},
                ],
                max_tokens=100,
                temperature=0.1,
                response_format={"type": "json_object"},
            )

            result = json.loads(response.choices[0].message.content)
            rankings = result.get("rankings", list(range(top_k)))

            # Reorder results based on rankings
            reranked = []
            for rank, idx in enumerate(rankings[:top_k]):
                if 0 <= idx < len(candidates):
                    item = candidates[idx].copy()
                    item["rerank_score"] = 1.0 - (rank / top_k)  # Higher score for higher rank
                    item["original_rank"] = idx
                    reranked.append(item)

            return reranked

        except Exception as e:
            logger.error(f"Re-ranking error: {e}")
            # Return original order
            return candidates[:top_k]


class EnhancedSearchService:
    """
    Main enhanced search service combining all components.
    """

    def __init__(
        self,
        search_endpoint: str | None = None,
        search_key: str | None = None,
        index_name: str | None = None,
        openai_client: AzureOpenAI | None = None,
    ):
        # Retrieval is handled by Neo4j Knowledge Graph.
        self.openai_client = openai_client or create_azure_openai_client()

        self.query_understanding = QueryUnderstanding(self.openai_client)
        self.reranker = ReRanker(self.openai_client)

        self.graph_search = get_graph_search_service()

    async def search(
        self,
        query: str,
        media_id: str | None = None,
        top_k: int = 20,
        use_reranking: bool = True,
        expand_query: bool = True,
        include_context: bool = True,
    ) -> SearchResponse:
        """
        Perform enhanced search with all optimizations.

        Args:
            query: Search query
            media_id: Optional media ID to filter to specific video
            top_k: Number of results to return
            use_reranking: Whether to use LLM re-ranking
            expand_query: Whether to expand query with synonyms
            include_context: Whether to include surrounding context
        """
        import time

        start_time = time.time()

        # Step 1: Query understanding
        query_analysis = await self.query_understanding.analyze_query(query)

        # Step 2: Expand query if enabled
        search_query = query
        if expand_query:
            search_query = self.query_understanding.expand_query(query, query_analysis)

        # Step 3: Graph hybrid search (Neo4j)
        raw_results = await self._hybrid_search(
            query=search_query,
            media_id=media_id,
            top_k=top_k * 2 if use_reranking else top_k,  # Get more for reranking
        )

        # Step 5: Re-rank if enabled
        if use_reranking and raw_results:
            raw_results = await self.reranker.rerank(query, raw_results, top_k)

        # Step 6: Add context if enabled
        if include_context:
            raw_results = await self._add_context(raw_results)

        # Step 7: Build search results
        results = [self._build_search_result(r) for r in raw_results[:top_k]]

        # Step 8: Group results
        temporal_clusters = self._cluster_by_time(results)
        scene_groups = self._group_by_scene(results)

        search_time = (time.time() - start_time) * 1000

        return SearchResponse(
            query=query,
            query_intent=query_analysis.get("intent"),
            total_results=len(results),
            results=results,
            temporal_clusters=temporal_clusters,
            scene_groups=scene_groups,
            search_time_ms=search_time,
            used_reranking=use_reranking,
            search_type="hybrid",
        )

    async def _hybrid_search(
        self, query: str, media_id: str | None, top_k: int
    ) -> list[dict[str, Any]]:
        """Hybrid search using Neo4j Knowledge Graph (vector + fulltext + graph)."""
        try:
            resp = self.graph_search.hybrid_search(
                query_text=query,
                node_types=[NodeType.FRAME],
                video_id=media_id,
                limit=top_k,
                use_reranking=False,
            )

            raw = []
            for r in resp.results:
                c = r.content or {}
                raw.append(
                    {
                        "id": r.node_id,
                        "media_id": c.get("video_id") or media_id or "",
                        "content": c.get("description") or "",
                        "timestamp": float(c.get("timestamp", 0.0) or 0.0),
                        "start_time": None,
                        "end_time": None,
                        "scene_id": c.get("scene_id"),
                        "detected_objects": c.get("detected_objects") or [],
                        "transcript_text": c.get("transcript_text"),
                        "score": float(r.combined_score or r.vector_score or 0.0),
                    }
                )

            return raw

        except Exception as e:
            logger.error(f"Graph hybrid search error: {e}")
            return []

    async def _add_context(self, results: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """
        Add surrounding context to each result.
        """
        # For now, return as-is; context would require additional queries
        # In production, we'd query for adjacent scenes/frames
        return results

    def _build_search_result(self, raw: dict[str, Any]) -> SearchResult:
        """Build SearchResult from raw search result."""
        return SearchResult(
            id=raw.get("id", ""),
            media_id=raw.get("media_id", ""),
            score=raw.get("score", 0.0),
            rerank_score=raw.get("rerank_score"),
            content=raw.get("content", ""),
            summary=raw.get("summary"),
            title=raw.get("title"),
            timestamp=raw.get("timestamp", 0.0),
            start_time=raw.get("start_time"),
            end_time=raw.get("end_time"),
            scene_id=raw.get("scene_id"),
            detected_objects=raw.get("detected_objects", []),
            transcript_segment=raw.get("transcript_text"),
        )

    def _cluster_by_time(
        self, results: list[SearchResult], cluster_gap: float = 10.0
    ) -> list[dict[str, Any]]:
        """
        Cluster results that are close in time.

        This helps users see related moments together.
        """
        if not results:
            return []

        # Sort by timestamp
        sorted_results = sorted(results, key=lambda r: r.timestamp)

        clusters = []
        current_cluster = {
            "start_time": sorted_results[0].timestamp,
            "end_time": sorted_results[0].timestamp,
            "result_ids": [sorted_results[0].id],
            "avg_score": sorted_results[0].score,
        }

        for result in sorted_results[1:]:
            if result.timestamp - current_cluster["end_time"] <= cluster_gap:
                # Add to current cluster
                current_cluster["end_time"] = result.timestamp
                current_cluster["result_ids"].append(result.id)
                # Update average score
                n = len(current_cluster["result_ids"])
                current_cluster["avg_score"] = (
                    current_cluster["avg_score"] * (n - 1) + result.score
                ) / n
            else:
                # Start new cluster
                clusters.append(current_cluster)
                current_cluster = {
                    "start_time": result.timestamp,
                    "end_time": result.timestamp,
                    "result_ids": [result.id],
                    "avg_score": result.score,
                }

        # Don't forget the last cluster
        clusters.append(current_cluster)

        return clusters

    def _group_by_scene(self, results: list[SearchResult]) -> list[dict[str, Any]]:
        """
        Group results by scene.
        """
        scene_map = {}

        for result in results:
            scene_id = result.scene_id
            if scene_id is None:
                continue

            if scene_id not in scene_map:
                scene_map[scene_id] = {
                    "scene_id": scene_id,
                    "title": result.title,
                    "start_time": result.start_time,
                    "end_time": result.end_time,
                    "result_ids": [],
                    "best_score": 0.0,
                }

            scene_map[scene_id]["result_ids"].append(result.id)
            scene_map[scene_id]["best_score"] = max(
                scene_map[scene_id]["best_score"], result.rerank_score or result.score
            )

        # Sort by best score
        return sorted(scene_map.values(), key=lambda x: x["best_score"], reverse=True)

    async def search_multiple_videos(
        self, query: str, media_ids: list[str], top_k_per_video: int = 5
    ) -> dict[str, SearchResponse]:
        """
        Search across multiple videos and return grouped results.
        """
        tasks = [self.search(query, media_id=mid, top_k=top_k_per_video) for mid in media_ids]

        responses = await asyncio.gather(*tasks, return_exceptions=True)

        result = {}
        for mid, response in zip(media_ids, responses):
            if isinstance(response, Exception):
                logger.error(f"Search error for {mid}: {response}")
                continue
            result[mid] = response

        return result


# Utility function for RAG context building
async def build_rag_context(search_response: SearchResponse, max_context_length: int = 4000) -> str:
    """
    Build optimized context for RAG from search results.

    Prioritizes high-scoring, diverse results within token limits.
    """
    context_parts = []
    current_length = 0

    for result in search_response.results:
        # Build result context
        parts = []

        if result.title:
            parts.append(f"[{result.title}]")

        if result.summary:
            parts.append(result.summary)
        elif result.content:
            parts.append(result.content[:300])

        if result.transcript_segment:
            parts.append(f"Speech: {result.transcript_segment[:200]}")

        parts.append(f"(at {result.timestamp:.1f}s)")

        result_text = " ".join(parts)

        # Check length
        if current_length + len(result_text) > max_context_length:
            break

        context_parts.append(result_text)
        current_length += len(result_text)

    return "\n\n".join(context_parts)
