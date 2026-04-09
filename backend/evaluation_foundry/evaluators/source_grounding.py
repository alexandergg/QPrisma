"""
Source Grounding Evaluator
============================

Prompt-based (LLM judge) custom evaluator for Azure AI Foundry.

Evaluates whether the agent's response cites actual video content
(frame descriptions, transcript quotes, scene references) rather
than hallucinating or providing generic answers.

Distinct from ``builtin.groundedness`` — this specifically checks for
video-specific evidence like transcript quotes, visual descriptions,
and scene-level references.

Scoring: Ordinal 1–5 scale
  1 = Pure hallucination / generic response with no video evidence
  2 = Claims about video content but no specific citations
  3 = Some video references but mixed with ungrounded claims
  4 = Most claims grounded in specific video evidence
  5 = Every claim backed by transcript quotes, frame descriptions, or scene data
"""

from __future__ import annotations

EVALUATOR_NAME = "qprisma.source_grounding"
EVALUATOR_DISPLAY_NAME = "Source Grounding"
EVALUATOR_DESCRIPTION = (
    "Evaluates whether the agent response cites actual video content "
    "(transcripts, frames, scenes) rather than hallucinating."
)

EVALUATOR_PROMPT = """You are an expert evaluator for a video analysis AI assistant called QPrisma.

Your task is to evaluate the **source grounding** of the assistant's response.

Source grounding measures how well the response is anchored in actual video content
rather than being generic, hallucinated, or fabricated.

## Scoring Rubric (1–5)

**1 — No grounding / hallucination**
The response makes claims about video content that appear fabricated. It contains no
verifiable references to actual video data (no quotes, no frame descriptions, no scene
references). The response could be about any topic.

**2 — Claims without evidence**
The response discusses video content in general terms but provides no specific evidence
like transcript excerpts, frame descriptions, or entity names that would come from
actual analysis. For example: "The video discusses several topics" without naming them.

**3 — Partial grounding**
The response mixes grounded and ungrounded claims. Some information appears to come
from actual video analysis (specific entities, topics, or content), but other claims
lack supporting evidence.

**4 — Well-grounded**
Most claims in the response are supported by specific video evidence: named entities,
described visual elements, quoted speech, or referenced scenes/chapters. Minor claims
may lack explicit citations but are consistent with the grounded content.

**5 — Fully grounded with citations**
Every significant claim is backed by explicit video evidence: direct transcript quotes
(in quotation marks), specific frame/scene descriptions, named entities from the
knowledge graph, or referenced chapter/segment data. The response clearly distinguishes
between what was found in the video and any interpretation.

## Important Notes

- If the query does not relate to video content (e.g., "What can you do?"), source
  grounding is not applicable. Score **3** (neutral) for such queries.
- If the response correctly states there is no video context, score **3**.
- Direct transcript quotes in quotation marks are the strongest form of grounding.
- References to specific frame numbers, timestamps with descriptions, or entity names
  from the knowledge graph are strong evidence of grounding.

## Input

**User query**: {{query}}

**Assistant response**: {{response}}

## Output

Provide your score as a single integer from 1 to 5.
"""

EVALUATOR_CONFIG = {
    "name": EVALUATOR_NAME,
    "display_name": EVALUATOR_DISPLAY_NAME,
    "description": EVALUATOR_DESCRIPTION,
    "prompt": EVALUATOR_PROMPT,
    "scoring_type": "ordinal",
    "scale_min": 1,
    "scale_max": 5,
    "template_variables": ["query", "response"],
}
