"""
QPrisma evaluation adapter.

Connects QPrisma's VideoAgentGraph to the evaluation harness.
Supports all ablation configurations by patching search behavior at runtime:
- qprisma-full: Complete pipeline (no overrides)
- qprisma-noagent: Single-shot RAG (no ReAct loop)
- qprisma-flat: Flat embeddings (vector-only scoring, no graph/temporal)
- qprisma-vectoronly: Vector-only, no reranking, no expansion
- qprisma-norerank: No LLM re-ranking
- qprisma-visualonly: Visual frames only (no audio)
- qprisma-audioonly: Transcript only (no visual)
- qprisma-fixedtokens: Fixed token budget per frame
"""

import logging
import time
from contextlib import contextmanager

from evaluation.ablation import AblationConfig, get_ablation_config
from evaluation.adapters.base import BaseMethodAdapter
from evaluation.models.eval_schemas import BenchmarkEntry, EvalResult

logger = logging.getLogger(__name__)


class QPrismaAdapter(BaseMethodAdapter):
    """Adapter for QPrisma's VideoAgentGraph with ablation support.

    Applies ablation configs by monkey-patching search service parameters
    during answer generation and restoring them afterwards.
    """

    def __init__(
        self,
        config_name: str = "full",
        model_deployment: str | None = None,
    ):
        """Initialize QPrisma adapter.

        Args:
            config_name: Ablation config name (see evaluation.ablation).
            model_deployment: Azure OpenAI deployment name.
        """
        self.config_name = config_name
        self.model_deployment = model_deployment
        self.ablation = get_ablation_config(config_name)
        self._agent = None

    @property
    def name(self) -> str:
        return f"qprisma-{self.config_name}"

    @property
    def display_name(self) -> str:
        names = {
            "full": "QPrisma (Full Pipeline)",
            "noagent": "QPrisma (Single-Shot RAG)",
            "flat": "QPrisma (Flat Embeddings)",
            "vectoronly": "QPrisma (Vector Only)",
            "norerank": "QPrisma (No Re-ranking)",
            "visualonly": "QPrisma (Visual Only)",
            "audioonly": "QPrisma (Audio Only)",
            "fixedtokens": "QPrisma (Fixed Token Budget)",
        }
        return names.get(self.config_name, f"QPrisma ({self.config_name})")

    async def setup(self) -> None:
        """Initialize the VideoAgentGraph."""
        from agent import VideoAgentGraph

        self._agent = VideoAgentGraph(
            model_deployment=self.model_deployment,
        )
        logger.info(
            "QPrisma adapter initialized: %s (ablation: %s)",
            self.name,
            self.ablation.name,
        )

    async def generate_answer(
        self,
        entry: BenchmarkEntry,
        video_path: str | None = None,
    ) -> EvalResult:
        """Run QPrisma agent on a benchmark question with ablation config."""
        if self._agent is None:
            await self.setup()

        start_time = time.perf_counter()
        query = self._build_query(entry)

        with self._apply_ablation():
            if self.ablation.bypass_agent:
                result = await self._run_single_shot(query, entry)
            else:
                result = await self._run_agent(query, entry)

        latency_ms = (time.perf_counter() - start_time) * 1000
        answer_text = result.get("response", "")

        return EvalResult(
            question_id=entry.question_id,
            method=self.name,
            answer=answer_text,
            predicted_choice=self.extract_mc_choice(answer_text, entry.choices),
            predicted_timestamps=self.extract_timestamps(answer_text),
            latency_ms=latency_ms,
            tool_calls=result.get("tool_calls_made", 0),
            metadata={
                "sources": result.get("sources", []),
                "config": self.config_name,
                "ablation": self.ablation.name,
            },
        )

    @contextmanager
    def _apply_ablation(self):
        """Context manager that applies ablation overrides to the search layer.

        Patches GraphSearchService parameters for the duration of the call,
        then restores them to defaults.
        """
        patches = []

        try:
            from services.graph_search_service import GraphSearchService
        except ImportError:
            logger.warning("GraphSearchService not available, skipping ablation patches")
            yield
            return

        saved_weights = GraphSearchService.DEFAULT_WEIGHTS.copy()
        saved_state = {}

        try:
            # 1. Override search weights
            if self.ablation.search_weights is not None:
                saved_state["weights"] = GraphSearchService.DEFAULT_WEIGHTS.copy()
                GraphSearchService.DEFAULT_WEIGHTS = self.ablation.search_weights.copy()

            # 2. Patch hybrid_search to override expansion_hops, use_reranking, node_types
            original_hybrid = getattr(GraphSearchService, "hybrid_search", None)
            if original_hybrid and self._needs_search_patch():
                ablation = self.ablation

                async def patched_hybrid_search(
                    self_svc, query_text, node_types=None, **kwargs
                ):
                    # Override expansion_hops
                    if ablation.expansion_hops is not None:
                        kwargs["expansion_hops"] = ablation.expansion_hops

                    # Override use_reranking
                    if ablation.use_reranking is not None:
                        kwargs["use_reranking"] = ablation.use_reranking

                    # Override search_limit
                    if ablation.search_limit is not None:
                        kwargs["limit"] = ablation.search_limit

                    # Filter node types by modality
                    if node_types is not None:
                        node_types = self._filter_node_types(node_types)

                    return await original_hybrid(
                        self_svc, query_text, node_types=node_types, **kwargs
                    )

                saved_state["hybrid_search"] = original_hybrid
                GraphSearchService.hybrid_search = patched_hybrid_search

            yield

        finally:
            # Restore original state
            if "weights" in saved_state:
                GraphSearchService.DEFAULT_WEIGHTS = saved_state["weights"]
            if "hybrid_search" in saved_state:
                GraphSearchService.hybrid_search = saved_state["hybrid_search"]

    def _needs_search_patch(self) -> bool:
        """Check if any search parameters need patching."""
        return (
            self.ablation.expansion_hops is not None
            or self.ablation.use_reranking is not None
            or self.ablation.search_limit is not None
            or not self.ablation.include_visual
            or not self.ablation.include_audio
            or not self.ablation.include_entities
        )

    def _filter_node_types(self, node_types: list) -> list:
        """Filter node types based on ablation modality config."""
        try:
            from models.graph_models import NodeType
        except ImportError:
            return node_types

        filtered = []
        for nt in node_types:
            if nt in (NodeType.FRAME, NodeType.SCENE) and not self.ablation.include_visual:
                continue
            if nt == NodeType.AUDIO_SEGMENT and not self.ablation.include_audio:
                continue
            if nt == NodeType.ENTITY and not self.ablation.include_entities:
                continue
            filtered.append(nt)

        # Ensure at least one node type remains
        if not filtered:
            logger.warning(
                "Ablation %s filtered all node types, falling back to original",
                self.ablation.name,
            )
            return node_types

        return filtered

    async def _run_agent(self, query: str, entry: BenchmarkEntry) -> dict:
        """Run the full ReAct agent."""
        try:
            return await self._agent.run(
                message=query,
                media_id=entry.video_id,
                session_id=f"eval_{entry.question_id}",
            )
        except Exception as e:
            logger.error("Agent error on %s: %s", entry.question_id, e)
            return {"response": f"Error: {e}", "sources": [], "tool_calls_made": 0}

    async def _run_single_shot(self, query: str, entry: BenchmarkEntry) -> dict:
        """Run single-shot RAG (bypass agent loop).

        Performs one retrieval pass and one LLM call without tool iteration.
        """
        try:
            from api.dependencies import get_graph_search_service
            from models.graph_models import NodeType

            search_service = get_graph_search_service()

            # Determine node types based on ablation
            node_types = []
            if self.ablation.include_visual:
                node_types.extend([NodeType.FRAME, NodeType.SCENE])
            if self.ablation.include_audio:
                node_types.append(NodeType.AUDIO_SEGMENT)
            if self.ablation.include_entities:
                node_types.append(NodeType.ENTITY)
            if not node_types:
                node_types = [NodeType.FRAME, NodeType.AUDIO_SEGMENT, NodeType.ENTITY]

            # Single retrieval pass
            search_response = await search_service.hybrid_search(
                query_text=query,
                node_types=node_types,
                video_id=entry.video_id,
                limit=10,
                expansion_hops=self.ablation.expansion_hops or 1,
                use_reranking=self.ablation.use_reranking
                if self.ablation.use_reranking is not None
                else True,
            )

            # Format context
            context = self._format_search_response(search_response)

            # Generate answer with LLM
            from agent.nodes.base import create_model
            from langchain_core.messages import HumanMessage, SystemMessage

            model = create_model()
            messages = [
                SystemMessage(
                    content="Answer the question using ONLY the provided video context. "
                    "Include timestamps. For multiple choice, state the letter."
                ),
                HumanMessage(content=f"Context:\n{context}\n\nQuestion: {query}"),
            ]

            response = await model.ainvoke(messages)

            sources = []
            for r in search_response.results[:10]:
                sources.append({
                    "timestamp": getattr(r, "timestamp", 0),
                    "type": str(getattr(r, "node_type", "")),
                    "content": getattr(r, "content", "")[:200] if isinstance(getattr(r, "content", ""), str) else "",
                })

            return {
                "response": response.content,
                "sources": sources,
                "tool_calls_made": 1,
            }

        except Exception as e:
            logger.error("Single-shot error on %s: %s", entry.question_id, e)
            return {"response": f"Error: {e}", "sources": [], "tool_calls_made": 0}

    def _build_query(self, entry: BenchmarkEntry) -> str:
        """Build the query string from a benchmark entry."""
        query = entry.question

        if entry.choices:
            query += "\n\nChoices:\n"
            for i, choice in enumerate(entry.choices):
                letter = chr(ord("A") + i)
                if choice.strip().startswith(f"{letter}.") or choice.strip().startswith(
                    f"{letter})"
                ):
                    query += f"{choice}\n"
                else:
                    query += f"{letter}. {choice}\n"
            query += "\nProvide the answer letter (A/B/C/D) and a brief explanation."

        return query

    def _format_search_response(self, search_response) -> str:
        """Format GraphSearchResponse as text context for the LLM."""
        parts = []
        for r in search_response.results[:10]:
            ts = getattr(r, "timestamp_formatted", "") or ""
            content = getattr(r, "content", "")
            if isinstance(content, dict):
                content = content.get("description", str(content))
            node_type = str(getattr(r, "node_type", ""))
            parts.append(f"[{ts}] ({node_type}) {content}")
        return "\n".join(parts) if parts else "No relevant context found."

    def _format_search_context(self, search_result: dict) -> str:
        """Format search results as text context for the LLM."""
        parts = []
        for r in search_result.get("results", [])[:10]:
            if isinstance(r, dict):
                ts = r.get("timestamp_formatted", "")
                content = r.get("content", r.get("description", ""))
                rtype = r.get("type", "")
                parts.append(f"[{ts}] ({rtype}) {content}")
        return "\n".join(parts) if parts else "No relevant context found."
