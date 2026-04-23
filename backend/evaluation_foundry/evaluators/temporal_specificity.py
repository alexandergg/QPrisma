"""
Temporal Specificity Evaluator
================================

Prompt-based (LLM judge) custom evaluator for Azure AI Foundry.

Evaluates whether the agent's response references specific timestamps,
scenes, or temporal markers from the video content.

Scoring: Ordinal 1–5 scale
  1 = No temporal references at all
  2 = Vague time references ("early in the video")
  3 = Some timestamps or time ranges mentioned
  4 = Multiple precise timestamps with context
  5 = Comprehensive temporal anchoring with [MM:SS] format throughout
"""

from __future__ import annotations

EVALUATOR_NAME = "qprisma.temporal_specificity"
EVALUATOR_DISPLAY_NAME = "Temporal Specificity"
EVALUATOR_DESCRIPTION = (
    "Evaluates whether the agent response references specific timestamps, "
    "scenes, or temporal markers from video content."
)

EVALUATOR_PROMPT = """You are an expert evaluator for a video analysis AI assistant called QPrisma.

Your task is to evaluate the **temporal specificity** of the assistant's response.

Temporal specificity measures how well the response anchors its claims to specific
moments in the video using timestamps, scene references, or time ranges.

## Scoring Rubric (1–5)

**1 — No temporal references**
The response contains no timestamps, time ranges, or temporal markers. It could
describe any video or no video at all.

**2 — Vague time references**
The response uses imprecise language like "early in the video", "at one point",
or "towards the end" without specific timestamps.

**3 — Some timestamps mentioned**
The response includes a few specific timestamps (e.g., [1:23]) or time ranges,
but not consistently throughout.

**4 — Multiple precise timestamps with context**
The response consistently uses specific timestamps and connects them to described
events. Most claims are temporally anchored.

**5 — Comprehensive temporal anchoring**
The response uses [MM:SS] or [H:MM:SS] format throughout. Every significant claim
is anchored to a specific timestamp or time range. Temporal flow is clear and precise.

## Important Notes

- If the query does not relate to video content (e.g., "What are your capabilities?"),
  temporal specificity is not applicable. Score **3** (neutral) for such queries.
- If the response correctly states there is no video context available, score **3**.
- The format [MM:SS] or [H:MM:SS] is preferred over raw seconds.

## Input

**User query**: {{query}}

**Assistant response**: {{response}}

## Output

Provide your score as a single integer from 1 to 5.
"""

EVALUATOR_CONFIG = {
    "name": EVALUATOR_NAME,
    # Bump on any change to ``prompt`` / ``display_name`` / ``description`` /
    # metric range. ``register_evaluators`` treats Foundry's "already exists"
    # response as success, so without a fresh version Foundry keeps serving
    # the previous prompt revision forever. See the parallel
    # ``EVALUATOR_VERSION`` constant on the code-based evaluators for full
    # rationale (``video_mme_mcq.EVALUATOR_VERSION``).
    "version": "1",
    "display_name": EVALUATOR_DISPLAY_NAME,
    "description": EVALUATOR_DESCRIPTION,
    "prompt": EVALUATOR_PROMPT,
    "scoring_type": "ordinal",
    "scale_min": 1,
    "scale_max": 5,
    "template_variables": ["query", "response"],
}
