"""
Video-MME Subset Evaluation Runner
===================================
Runs Video-MME subset evaluation against the QPrisma agent API.
Uses the same approach as run_first_eval.py but with Video-MME benchmark data.
"""

import asyncio
import json
import logging
import os
import re
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

API_URL = os.environ.get("QPRISMA_API_URL", "http://localhost:8000")
EMAIL = os.environ.get("QPRISMA_EVAL_EMAIL", "")
PASSWORD = os.environ.get("QPRISMA_EVAL_PASSWORD", "")

CATEGORY_TOOL_HINTS = {
    "Information Synopsis": (
        "STRATEGY: Use get_summary or list_chapters first for an overview, "
        "then search_video only if needed. Focus on the overall theme."
    ),
    "Object Reasoning": (
        "STRATEGY: Use describe_scene at multiple timestamps to observe objects, "
        "then reason about symbolism or meaning based on visual evidence."
    ),
    "Action Recognition": (
        "STRATEGY: Use search_video to find key actions, then describe_scene "
        "to confirm what specific actions are being performed."
    ),
    "Action Reasoning": (
        "STRATEGY: Use describe_scene at key moments and get_scene_context "
        "to understand the purpose or intention behind actions."
    ),
    "Attribute Perception": (
        "STRATEGY: Use describe_scene at specific timestamps to observe "
        "visual attributes like colors, clothing, appearance details."
    ),
    "Spatial Perception": (
        "STRATEGY: Use describe_scene to carefully observe spatial "
        "relationships, positions, and arrangements of objects."
    ),
}

SUBSET_PATH = (
    Path(__file__).parent.parent.parent
    / "data"
    / "benchmarks"
    / "video_mme"
    / "video_mme_subset.json"
)
OUTPUT_BASE = Path(__file__).parent.parent / "results" / "video_mme_subset"


def extract_mc_choice(text: str, choices: list[str] | None = None) -> str:
    """Extract A/B/C/D from response text.

    Searches before any '---SUGGESTED_QUESTIONS---' marker to avoid
    matching letters in follow-up suggestions. Falls back to matching
    the full choice text against the response.
    """
    if not text:
        return "?"
    # Strip suggested questions block to avoid false matches
    answer_text = text.split("---SUGGESTED_QUESTIONS---")[0].strip()
    if not answer_text:
        answer_text = text

    # Phase 1: Direct letter extraction
    patterns = [
        r"\*\*(?:Answer:\s*)?([A-D])[\.\*]",  # **A** or **Answer: A**
        r"(?:Answer|answer|ANSWER)[:\s]+\**([A-D])\b",  # Answer: A, answer: **A**
        r"(?:^|\n)\s*\**([A-D])\**[\.\)\:\s]",  # A. or **A.** at line start
        r"^([A-D])$",  # Standalone letter
        r"\b([A-D])\b\s*[\.\):]",  # A. or A) anywhere
    ]
    for p in patterns:
        m = re.search(p, answer_text, re.MULTILINE)
        if m:
            return m.group(1)

    # Phase 2: Match choice text in the response (e.g., agent says "Black" → match to choice "D. Black")
    if choices:
        answer_lower = answer_text.lower()
        # Check if the agent wrote "Answer: <choice text>" instead of a letter
        for i, choice in enumerate(choices):
            letter = chr(ord("A") + i)
            # Strip letter prefix from choice (e.g., "A. Eating." → "Eating")
            choice_text = re.sub(r"^[A-D][\.\)]\s*", "", choice).strip().rstrip(".")
            if len(choice_text) >= 5 and choice_text.lower() in answer_lower:
                return letter

    # Phase 3: Fallback — first standalone A-D letter in text
    m = re.search(r"\b([A-D])\b", answer_text)
    return m.group(1) if m else "?"


async def run_evaluation():
    """Run the Video-MME subset evaluation."""
    # Create timestamped output directory
    run_id = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    output_dir = OUTPUT_BASE / f"run_{run_id}"
    output_dir.mkdir(parents=True, exist_ok=True)
    logger.info("Output: %s", output_dir)

    # Load benchmark
    subset = json.loads(SUBSET_PATH.read_text(encoding="utf-8"))
    logger.info("Loaded %d questions from Video-MME subset", len(subset))

    # Login
    if not EMAIL or not PASSWORD:
        raise RuntimeError("Set QPRISMA_EVAL_EMAIL and QPRISMA_EVAL_PASSWORD environment variables")
    async with httpx.AsyncClient(base_url=API_URL, timeout=60) as c:
        r = await c.post("/auth/login", json={"email": EMAIL, "password": PASSWORD})
        r.raise_for_status()
        token = r.json()["access_token"]
    logger.info("Authenticated successfully")

    results = []
    correct = 0

    for i, entry in enumerate(subset):
        qid = entry["question_id"]
        media_id = entry["video_id"]
        question = entry["question"]
        choices = entry["choices"]
        correct_answer = entry["correct_answer"]
        category = entry.get("category", "unknown")
        original_vid = entry.get("original_video_id", "?")

        # Build query with MC-optimized prompt
        query = question + "\n\nChoices:\n"
        for choice in choices:
            query += f"{choice}\n"

        # Add category-aware tool hints
        tool_hint = CATEGORY_TOOL_HINTS.get(category, "")
        if tool_hint:
            query += f"\n{tool_hint}\n"

        query += (
            "\nThis is a multiple-choice question. Use your tools efficiently to gather "
            "evidence, then respond with your answer in this exact format:\n"
            "**Answer: X** (where X is A, B, C, or D)\n"
            "followed by a one-sentence explanation.\n"
            "IMPORTANT: You MUST answer with the LETTER (A/B/C/D), not the text of the choice. "
            "Be concise. Do NOT include suggested questions."
        )

        session_id = f"vmme_v2_{qid}_{uuid.uuid4().hex[:8]}"
        start = time.perf_counter()

        try:
            async with httpx.AsyncClient(
                base_url=API_URL, timeout=180, headers={"Authorization": f"Bearer {token}"}
            ) as c:
                resp = await c.post(
                    "/chat/agent",
                    json={
                        "message": query,
                        "media_id": media_id,
                        "session_id": session_id,
                    },
                )

                if resp.status_code == 200:
                    data = resp.json()
                    answer_text = data.get("response", "")
                    tool_calls = data.get("tool_calls_made", 0)
                    sources = len(data.get("sources", []))
                else:
                    answer_text = f"API Error {resp.status_code}"
                    tool_calls = 0
                    sources = 0
        except Exception as e:
            answer_text = f"Error: {e}"
            tool_calls = 0
            sources = 0

        latency_ms = (time.perf_counter() - start) * 1000
        predicted = extract_mc_choice(answer_text, choices)
        is_correct = predicted == correct_answer

        if is_correct:
            correct += 1

        result = {
            "question_id": qid,
            "original_video_id": original_vid,
            "category": category,
            "predicted": predicted,
            "correct": correct_answer,
            "is_correct": is_correct,
            "latency_ms": latency_ms,
            "tool_calls": tool_calls,
            "sources": sources,
        }
        results.append(result)

        status = "✓" if is_correct else "✗"
        logger.info(
            "  [%d/%d] %s %s pred=%s correct=%s tools=%d sources=%d cat=%s (%.0fms)",
            i + 1,
            len(subset),
            status,
            qid,
            predicted,
            correct_answer,
            tool_calls,
            sources,
            category,
            latency_ms,
        )

    # Compute stats
    total = len(results)
    accuracy = correct / total if total else 0

    # Per-category stats
    cats = {}
    for r in results:
        c = r["category"]
        cats.setdefault(c, {"correct": 0, "total": 0, "tools": 0, "sources": 0})
        cats[c]["total"] += 1
        cats[c]["tools"] += r["tool_calls"]
        cats[c]["sources"] += r["sources"]
        if r["is_correct"]:
            cats[c]["correct"] += 1

    logger.info("\n%s", "=" * 70)
    logger.info("Video-MME Subset Results (v2 - with improvements)")
    logger.info("=" * 70)
    logger.info("Overall: %d/%d = %.1f%%", correct, total, accuracy * 100)
    logger.info("Avg latency: %.0fms", sum(r["latency_ms"] for r in results) / total)
    logger.info("Avg tool calls: %.1f", sum(r["tool_calls"] for r in results) / total)
    logger.info("Avg sources: %.1f", sum(r["sources"] for r in results) / total)

    logger.info("\n%-30s %10s %10s %12s", "Category", "Accuracy", "Avg Tools", "Avg Sources")
    logger.info("-" * 65)
    for cat, v in sorted(cats.items(), key=lambda x: x[1]["correct"] / x[1]["total"], reverse=True):
        acc = 100 * v["correct"] / v["total"]
        avg_t = v["tools"] / v["total"]
        avg_s = v["sources"] / v["total"]
        logger.info(
            "%-30s %d/%d = %5.1f%% %8.1f %10.1f",
            cat,
            v["correct"],
            v["total"],
            acc,
            avg_t,
            avg_s,
        )

    # Save report
    report = {
        "benchmark": "video_mme_subset_v2",
        "total_questions": total,
        "total_videos": len({r["original_video_id"] for r in results}),
        "accuracy": accuracy,
        "accuracy_by_category": {
            cat: {
                "correct": v["correct"],
                "total": v["total"],
                "accuracy": v["correct"] / v["total"],
                "avg_tool_calls": v["tools"] / v["total"],
                "avg_sources": v["sources"] / v["total"],
            }
            for cat, v in cats.items()
        },
        "avg_latency_ms": sum(r["latency_ms"] for r in results) / total,
        "avg_tool_calls": sum(r["tool_calls"] for r in results) / total,
        "qprisma": results,
    }

    report_path = output_dir / "report.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("\nReport saved to %s", report_path)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    asyncio.run(run_evaluation())
