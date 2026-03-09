"""
First evaluation run: QPrisma vs baseline on custom benchmark.

Runs QPrisma (full pipeline) and a naive baseline (no agent, single-shot)
on hand-crafted questions about the Microsoft Ignite Keynote video
that's already indexed in the Knowledge Graph.

Usage:
    cd backend
    python -m evaluation.scripts.run_first_eval              # 10-question quick run
    python -m evaluation.scripts.run_first_eval --expanded    # 30-question full run
"""

import argparse
import asyncio
import json
import logging
import os
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from evaluation.adapters.base import BaseMethodAdapter
from evaluation.metrics.accuracy import (
    compute_accuracy,
    compute_accuracy_by_group,
)
from evaluation.models.eval_schemas import BenchmarkEntry, EvalResult
from evaluation.runner import EvaluationRunner

logger = logging.getLogger(__name__)

# We can't easily run the full QPrisma agent in eval mode without the full
# server context, so we'll use the chat API endpoint as our adapter.

QUICK_QUESTION_IDS = {
    "ignite_q1",
    "ignite_q2",
    "ignite_q3",
    "ignite_q4",
    "ignite_q5",
    "ignite_q6",
    "ignite_q7",
    "ignite_q8",
    "ignite_q9",
    "ignite_q10",
}


class APIChatAdapter(BaseMethodAdapter):
    """Adapter that calls QPrisma's chat API endpoint.

    Uses the live /chat/agent API which invokes the full
    VideoAgentGraph pipeline (tools, KG search, re-ranking, etc.).
    """

    def __init__(
        self,
        api_url: str = "http://localhost:8000",
        token: str = "",
        method_name: str = "qprisma-full",
    ):
        self.api_url = api_url
        self.token = token
        self._method_name = method_name

    @property
    def name(self) -> str:
        return self._method_name

    @property
    def display_name(self) -> str:
        return f"QPrisma ({self._method_name})"

    async def setup(self) -> None:
        pass

    async def generate_answer(
        self,
        entry: BenchmarkEntry,
        video_path: str | None = None,
    ) -> EvalResult:
        import httpx

        start = time.perf_counter()
        answer_text = ""
        tool_calls = 0

        try:
            # Build query with MC choices
            query = entry.question
            if entry.choices:
                query += "\n\nChoices:\n"
                for i, c in enumerate(entry.choices):
                    letter = chr(ord("A") + i)
                    query += f"{letter}. {c}\n"
                query += (
                    "\nIMPORTANT: First use your search tools to find relevant visual and audio evidence "
                    "from the video before answering. Then answer with just the letter (A/B/C/D) "
                    "and a brief explanation based on the evidence you found."
                )

            headers = {"Authorization": f"Bearer {self.token}"}

            # Use unique session ID per question to avoid session contamination
            session_id = f"eval_{entry.question_id}_{uuid.uuid4().hex[:8]}"

            async with httpx.AsyncClient(
                base_url=self.api_url, timeout=180, headers=headers
            ) as client:
                # Use /chat/agent for full LangGraph agent pipeline
                resp = await client.post(
                    "/chat/agent",
                    json={
                        "message": query,
                        "media_id": entry.video_id,
                        "session_id": session_id,
                    },
                )

                if resp.status_code == 200:
                    data = resp.json()
                    answer_text = data.get("response", "")
                    tool_calls = data.get("tool_calls_made", 0)
                else:
                    answer_text = f"API Error {resp.status_code}: {resp.text[:200]}"

        except Exception as e:
            answer_text = f"Error: {e}"

        latency_ms = (time.perf_counter() - start) * 1000

        return EvalResult(
            question_id=entry.question_id,
            method=self.name,
            answer=answer_text,
            predicted_choice=self.extract_mc_choice(answer_text, entry.choices),
            predicted_timestamps=self.extract_timestamps(answer_text),
            latency_ms=latency_ms,
            tool_calls=tool_calls,
        )


class DirectSearchAdapter(BaseMethodAdapter):
    """Baseline adapter that does direct search + LLM, no agent loop.

    Uses POST /search for retrieval, then POST /chat for LLM answer.
    Simulates a naive RAG approach (no agent loop, no tool calling).
    """

    def __init__(
        self,
        api_url: str = "http://localhost:8000",
        token: str = "",
    ):
        self.api_url = api_url
        self.token = token

    @property
    def name(self) -> str:
        return "direct-search"

    @property
    def display_name(self) -> str:
        return "Direct Search (No Agent)"

    async def setup(self) -> None:
        pass

    async def generate_answer(
        self,
        entry: BenchmarkEntry,
        video_path: str | None = None,
    ) -> EvalResult:
        import httpx

        start = time.perf_counter()
        answer_text = ""

        try:
            headers = {"Authorization": f"Bearer {self.token}"}
            query = entry.question

            async with httpx.AsyncClient(
                base_url=self.api_url, timeout=90, headers=headers
            ) as client:
                # Step 1: Search via POST /search
                resp = await client.post(
                    "/search",
                    json={
                        "query": query,
                        "media_id": entry.video_id,
                        "limit": 5,
                    },
                )

                if resp.status_code == 200:
                    results = resp.json().get("results", [])
                    context_parts = []
                    for r in results[:5]:
                        ts = r.get("timestamp", 0)
                        content = str(r.get("content", ""))[:300]
                        context_parts.append(f"[{ts:.1f}s] {content}")
                    context = "\n".join(context_parts) if context_parts else "No results found."
                else:
                    context = f"Search failed (HTTP {resp.status_code})."

                # Step 2: Ask LLM via POST /chat (simple RAG, no agent)
                mc_query = query
                if entry.choices:
                    mc_query += "\n\nChoices:\n"
                    for i, c in enumerate(entry.choices):
                        letter = chr(ord("A") + i)
                        mc_query += f"{letter}. {c}\n"
                    mc_query += "\nAnswer with just the letter (A/B/C/D)."

                full_prompt = f"Based on this video context:\n{context}\n\n" f"Question: {mc_query}"

                resp2 = await client.post(
                    "/chat",
                    json={
                        "message": full_prompt,
                        "media_id": entry.video_id,
                    },
                )

                if resp2.status_code == 200:
                    data = resp2.json()
                    answer_text = data.get("response", "")
                else:
                    answer_text = f"API Error: {resp2.status_code}"

        except Exception as e:
            answer_text = f"Error: {e}"

        latency_ms = (time.perf_counter() - start) * 1000

        return EvalResult(
            question_id=entry.question_id,
            method=self.name,
            answer=answer_text,
            predicted_choice=self.extract_mc_choice(answer_text, entry.choices),
            predicted_timestamps=self.extract_timestamps(answer_text),
            latency_ms=latency_ms,
            tool_calls=1,
        )


def get_token(api_url: str, email: str, password: str) -> str:
    """Get JWT token from QPrisma API."""
    import httpx

    resp = httpx.post(
        f"{api_url}/auth/login",
        json={"email": email, "password": password},
    )
    if resp.status_code != 200:
        raise RuntimeError(f"Login failed: {resp.text}")
    return resp.json()["access_token"]


async def run_first_eval(expanded: bool = False, fresh: bool = False):
    """Run the first evaluation end-to-end.

    Args:
        expanded: If True, run all 30 questions. If False, run only the
                  original 10 easy questions.
        fresh: If True, create a new timestamped run directory instead of
               resuming from existing results.
    """
    api_url = "http://localhost:8000"

    # Create timestamped output directory for fresh runs
    base_output = Path("evaluation/results/first_eval")
    if fresh:
        run_id = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        output_dir = base_output / f"run_{run_id}"
        logger.info("Fresh run: %s", output_dir)
    else:
        output_dir = base_output
    output_dir.mkdir(parents=True, exist_ok=True)

    # 1. Auth
    logger.info("Authenticating...")
    email = os.environ.get("QPRISMA_EVAL_EMAIL", "")
    password = os.environ.get("QPRISMA_EVAL_PASSWORD", "")
    if not email or not password:
        raise RuntimeError("Set QPRISMA_EVAL_EMAIL and QPRISMA_EVAL_PASSWORD environment variables")
    token = get_token(api_url, email, password)
    logger.info("  Token obtained.")

    # 2. Load benchmark
    bench_path = Path("data/benchmarks/qprisma_first_eval/benchmark.json")
    all_entries = [
        BenchmarkEntry.model_validate(e) for e in json.loads(bench_path.read_text(encoding="utf-8"))
    ]

    if expanded:
        entries = all_entries
    else:
        entries = [e for e in all_entries if e.question_id in QUICK_QUESTION_IDS]

    logger.info("  Loaded %d benchmark questions (expanded=%s).", len(entries), expanded)

    # 3. Create adapters
    qprisma = APIChatAdapter(api_url=api_url, token=token, method_name="qprisma-full")
    baseline = DirectSearchAdapter(api_url=api_url, token=token)

    # 4. Run evaluation with per-question progress
    runner = EvaluationRunner(
        output_dir=str(output_dir / "answers"),
        max_concurrent=1,  # Sequential to avoid API overload
        resume=not fresh,
    )

    logger.info("\n" + "=" * 60)
    logger.info("RUNNING QPRISMA (Full Agent Pipeline)")
    logger.info("=" * 60)

    for i, entry in enumerate(entries, 1):
        logger.info("  [%d/%d] %s: %s...", i, len(entries), entry.question_id, entry.question[:60])

    qprisma_results = await runner.run_method(qprisma, entries, benchmark_name="first_eval")

    logger.info("\n" + "=" * 60)
    logger.info("RUNNING BASELINE (Direct Search)")
    logger.info("=" * 60)

    for i, entry in enumerate(entries, 1):
        logger.info("  [%d/%d] %s: %s...", i, len(entries), entry.question_id, entry.question[:60])

    baseline_results = await runner.run_method(baseline, entries, benchmark_name="first_eval")

    # 5. Compute metrics
    logger.info("\n" + "=" * 60)
    logger.info("COMPUTING METRICS")
    logger.info("=" * 60)

    qp_accuracy = compute_accuracy(qprisma_results, entries)
    bl_accuracy = compute_accuracy(baseline_results, entries)

    qp_by_cat = compute_accuracy_by_group(qprisma_results, entries, "category")
    bl_by_cat = compute_accuracy_by_group(baseline_results, entries, "category")

    qp_efficiency = runner.tracker.summarize("qprisma-full")
    bl_efficiency = runner.tracker.summarize("direct-search")

    # 6. Generate report
    logger.info("\n" + "=" * 60)
    logger.info("EVALUATION RESULTS")
    logger.info("=" * 60)

    logger.info("\n%-25s %10s %15s %15s", "Method", "Accuracy", "Avg Latency", "Avg Tool Calls")
    logger.info("-" * 65)
    logger.info(
        "%-25s %9.1f%% %13,.0fms %13.1f",
        "QPrisma (Full Agent)",
        qp_accuracy * 100,
        qp_efficiency.get("latency_mean_ms", 0),
        qp_efficiency.get("tool_calls_mean", 0),
    )
    logger.info(
        "%-25s %9.1f%% %13,.0fms %13.1f",
        "Direct Search (No Agent)",
        bl_accuracy * 100,
        bl_efficiency.get("latency_mean_ms", 0),
        bl_efficiency.get("tool_calls_mean", 0),
    )

    # By category
    all_cats = sorted(set(list(qp_by_cat.keys()) + list(bl_by_cat.keys())))
    if all_cats:
        logger.info("\n%-25s %10s %10s", "Category", "QPrisma", "Baseline")
        logger.info("-" * 45)
        for cat in all_cats:
            logger.info(
                "%-25s %9.1f%% %9.1f%%",
                cat,
                qp_by_cat.get(cat, 0) * 100,
                bl_by_cat.get(cat, 0) * 100,
            )

    # Per-question details
    logger.info("\n%-15s %10s %10s %10s", "QID", "QPrisma", "Baseline", "Correct")
    logger.info("-" * 50)
    entry_map = {e.question_id: e for e in entries}
    for qr, br in zip(
        sorted(qprisma_results, key=lambda r: r.question_id),
        sorted(baseline_results, key=lambda r: r.question_id),
    ):
        correct = entry_map[qr.question_id].correct_answer
        qp_mark = (
            "OK" if qr.predicted_choice and qr.predicted_choice.upper() == correct.upper() else "X"
        )
        bl_mark = (
            "OK" if br.predicted_choice and br.predicted_choice.upper() == correct.upper() else "X"
        )
        logger.info(
            "%-15s %5s %4s %5s %4s %5s",
            qr.question_id,
            qr.predicted_choice or "?",
            qp_mark,
            br.predicted_choice or "?",
            bl_mark,
            correct,
        )

    # Save report
    report = {
        "benchmark": "qprisma_first_eval",
        "mode": "expanded" if expanded else "quick",
        "total_questions": len(entries),
        "methods": {
            "qprisma-full": {
                "accuracy": qp_accuracy,
                "accuracy_by_category": qp_by_cat,
                "efficiency": qp_efficiency,
                "answers": [r.model_dump() for r in qprisma_results],
            },
            "direct-search": {
                "accuracy": bl_accuracy,
                "accuracy_by_category": bl_by_cat,
                "efficiency": bl_efficiency,
                "answers": [r.model_dump() for r in baseline_results],
            },
        },
    }

    report_path = output_dir / "first_eval_report.json"
    report_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    logger.info("\nFull report saved to: %s", report_path)

    return report


def main():
    parser = argparse.ArgumentParser(description="QPrisma First Evaluation")
    parser.add_argument(
        "--expanded",
        action="store_true",
        help="Run expanded 30-question benchmark instead of 10-question quick run",
    )
    parser.add_argument(
        "--fresh",
        action="store_true",
        help="Force a fresh run with timestamped output (ignore cached results)",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    # Reduce noise from httpx/httpcore
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    question_count = "30" if args.expanded else "10"
    logger.info("QPrisma First Evaluation")
    logger.info("========================")
    logger.info("Benchmark: %s MC questions about Microsoft Ignite Keynote", question_count)
    logger.info("Methods: QPrisma (Full Agent) vs Direct Search (No Agent)")

    asyncio.run(run_first_eval(expanded=args.expanded, fresh=args.fresh))


if __name__ == "__main__":
    main()
