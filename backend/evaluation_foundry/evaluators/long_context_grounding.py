"""Long-context grounding evaluator (``qprisma.long_context_grounding``) — E1.

Purpose
-------
For long-bucket video questions (and any RAG-style answer), a well-grounded
response **must cite when** the evidence appears in the source — i.e. drop a
``[mm:ss]``, ``(hh:mm:ss)``, ``frame 1234``, or ``t=12.5s`` anchor — not just
make confident claims. This evaluator turns that property into a deterministic
score so we can:

* track grounding regressions independently of the LLM-judge-based
  ``qprisma.source_grounding`` (which can drift with judge version),
* gate Video-MME long-bucket runs on a cheap, reproducible signal.

Score
-----
* **1.0** — response contains ≥ 1 precise time-anchored citation
  (timestamp or frame).
* **0.5** — response contains a soft temporal reference (``"near the end"``,
  ``"in the middle"``, etc.) but no precise anchor. Partial credit because
  the model gestured at grounding but didn't pin it.
* **0.0** — no citations and no soft temporal reference.

The 0.5 partial-credit rung is intentional: it lets us see model behavior
shifting from "no grounding awareness" → "vague grounding" → "precise
grounding" across releases without the all-or-nothing cliff that would mask
gradual improvement.

Two registration shapes mirror ``video_mme_mcq``:

* ``CODE_DEFINITION_KWARGS`` — preferred. Pure Python, no judge cost.
  ``code_text`` runs server-side in Foundry.
* ``PROMPT_FALLBACK_CONFIG`` — strict 0/0.5/1 prompt judge, used if the
  deployed SDK does not expose ``CodeBasedEvaluatorDefinition``.
"""

from __future__ import annotations

from evaluation_foundry.evaluators._citation_parsing import (
    has_soft_time_reference,
    parse_citations,
)

EVALUATOR_NAME = "qprisma.long_context_grounding"
EVALUATOR_DISPLAY_NAME = "Long-Context Grounding"
EVALUATOR_DESCRIPTION = (
    "Deterministic check that the agent cited time-anchored evidence (timestamps or "
    "frame indices). 1.0 = ≥1 precise citation; 0.5 = soft temporal reference only; "
    "0.0 = no grounding."
)


# ---------------------------------------------------------------------------
# Pure-Python scorer (also re-used by tests)
# ---------------------------------------------------------------------------


def score(response: str | None) -> float:
    """Score ``response`` for time-anchored grounding evidence."""
    citations = parse_citations(response)
    if citations:
        return 1.0
    if has_soft_time_reference(response):
        return 0.5
    return 0.0


# ---------------------------------------------------------------------------
# Server-side code text registered via CodeBasedEvaluatorDefinition
# ---------------------------------------------------------------------------

# Self-contained version of the regex set from _citation_parsing.py — the
# Foundry runtime that executes ``code_text`` does not have access to QPrisma's
# package layout, so we inline the patterns here.
CODE_TEXT = """
import re

_BRACKET_TS = re.compile(r"\\[\\s*(\\d{1,2}):(\\d{2})(?::(\\d{2}))?\\s*\\]")
_PAREN_TS = re.compile(r"\\(\\s*(\\d{1,2}):(\\d{2})(?::(\\d{2}))?\\s*\\)")
_BARE_TS = re.compile(r"(?<![\\d.])(\\d{1,2}):(\\d{2})(?::(\\d{2}))?(?!\\d)")
_FRAME_RE = re.compile(r"\\bframe\\s*#?\\s*(\\d{1,7})\\b", re.IGNORECASE)
_TEQ_RE = re.compile(r"\\bt\\s*=\\s*(\\d+(?:\\.\\d+)?)\\s*s\\b", re.IGNORECASE)
_AT_SEC_RE = re.compile(r"\\bat\\s+(\\d+(?:\\.\\d+)?)\\s*(?:s|sec|secs|seconds?)\\b", re.IGNORECASE)
_TIME_WORDS = re.compile(
    r"\\b(beginning|middle|end|opening|closing|earlier|later|after|before)\\b",
    re.IGNORECASE,
)


def _has_precise_citation(response):
    if not response:
        return False
    for pat in (_BRACKET_TS, _PAREN_TS, _BARE_TS, _FRAME_RE, _TEQ_RE, _AT_SEC_RE):
        if pat.search(response):
            return True
    return False


def evaluate(response, **kwargs):
    text = response or ""
    if _has_precise_citation(text):
        return {"long_context_grounding": 1.0}
    if _TIME_WORDS.search(text):
        return {"long_context_grounding": 0.5}
    return {"long_context_grounding": 0.0}
""".strip()


CODE_DEFINITION_KWARGS = {
    "code_text": CODE_TEXT,
    "init_parameters": {},
    "data_schema": {
        "response": {"type": "string"},
    },
    "metric_name": "long_context_grounding",
    "metric": {
        "type": "ordinal",
        "desirable_direction": "increase",
        "min_value": 0.0,
        "max_value": 1.0,
        "is_primary": True,
    },
}


PROMPT_FALLBACK_CONFIG = {
    "name": EVALUATOR_NAME,
    "display_name": EVALUATOR_DISPLAY_NAME,
    "description": EVALUATOR_DESCRIPTION,
    "prompt": (
        "You are a strict grader for whether a video-question RESPONSE is grounded "
        "in time.\n"
        "Output exactly one of these tokens:\n"
        "  `1`   if the response contains a precise timestamp like [mm:ss], (hh:mm:ss), "
        "         a frame index like 'frame 1234', or 't=12.5s'.\n"
        "  `0.5` if the response only refers to time vaguely (e.g. 'in the middle', "
        "         'near the end') but has no precise anchor.\n"
        "  `0`   if the response has no temporal grounding at all.\n"
        "Output nothing else.\n\n"
        "RESPONSE:\n{response}"
    ),
    "scale_min": 0.0,
    "scale_max": 1.0,
}
