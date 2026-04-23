"""Video-MME MCQ evaluator (``qprisma.video_mme_mcq``).

Deterministic letter exact-match evaluator (V3 in the plan).

The agent is instructed by the verbatim Video-MME prompt template to respond
**only** with the letter A/B/C/D. We extract the first such letter from the
response with a strict regex (``^[A-D]`` after stripping whitespace and common
prefixes like ``Answer:``) and compare to ``ground_truth``.

Two registration shapes are exposed for ``register_evaluators.py``:

1. ``CODE_DEFINITION_KWARGS`` — for ``CodeBasedEvaluatorDefinition`` (preferred,
   pure Python, no judge cost). The ``code_text`` runs server-side in Foundry.
2. ``PROMPT_FALLBACK_CONFIG`` — strict prompt-based evaluator that returns
   exactly ``1.0`` or ``0.0``. Used when a code-based evaluator path is not
   available in the deployed SDK / runtime.

Stratification (``accuracy_short`` / ``medium`` / ``long`` / ``overall``) is
performed at the Foundry aggregation layer using the ``duration_bucket`` field
emitted in each row's ``metadata`` block — no per-row work needed here.
"""

from __future__ import annotations

import re

EVALUATOR_NAME = "qprisma.video_mme_mcq"
EVALUATOR_DISPLAY_NAME = "Video-MME MCQ Accuracy"
EVALUATOR_DESCRIPTION = (
    "Deterministic letter exact-match for Video-MME multiple-choice questions. "
    "Returns 1.0 if the first A/B/C/D in the response matches ground_truth, else 0.0."
)
# Bump this string whenever ``CODE_TEXT`` (or any registered field) changes —
# Foundry's ``create_version`` is a no-op when the version already exists, so a
# stale version will keep serving the previous ``code_text`` forever.
# v1: original ``evaluate()`` entry point — REJECTED by Foundry's PythonGrader
#     ("top-level grade() function not found in source").
# v2: rename to ``grade()`` to match Foundry's required entry point name.
EVALUATOR_VERSION = "2"

# ---------------------------------------------------------------------------
# Pure-Python scorer (also re-used by tests)
# ---------------------------------------------------------------------------

# Allow optional leading prefixes like "Answer:", "The best answer is:", "(",
# whitespace, markdown, etc. Match the first standalone A-D letter.
_LETTER_RE = re.compile(r"\b([A-D])\b")


def extract_letter(response: str | None) -> str | None:
    """Return the first A/B/C/D letter in ``response``, or ``None``.

    Examples
    --------
    >>> extract_letter("C")
    'C'
    >>> extract_letter("Answer: B")
    'B'
    >>> extract_letter("The best answer is: D.")
    'D'
    >>> extract_letter("I think the answer is A or maybe B")
    'A'
    >>> extract_letter("ABCD") is None  # no word boundary -> reject
    True
    >>> extract_letter("") is None
    True
    """
    if not response:
        return None
    m = _LETTER_RE.search(response.strip())
    return m.group(1) if m else None


def score(response: str | None, ground_truth: str | None) -> float:
    """Return ``1.0`` if the extracted letter matches ``ground_truth`` exactly, else ``0.0``."""
    if not ground_truth:
        return 0.0
    extracted = extract_letter(response)
    return 1.0 if extracted == ground_truth.strip().upper() else 0.0


# ---------------------------------------------------------------------------
# Foundry registration payloads
# ---------------------------------------------------------------------------

# `code_text` is what Foundry executes server-side per row. It must be
# self-contained — no project imports.
CODE_TEXT = '''
import re

_LETTER_RE = re.compile(r"\\b([A-D])\\b")


def grade(response: str = "", ground_truth: str = "", **_):
    """Return {"accuracy": 1.0 | 0.0} for Video-MME letter exact-match.

    Foundry's Azure OpenAI ``python_grader`` requires the entry point to be a
    top-level function literally named ``grade``.
    """
    if not ground_truth:
        return {"accuracy": 0.0}
    if not response:
        return {"accuracy": 0.0}
    m = _LETTER_RE.search(response.strip())
    extracted = m.group(1) if m else None
    return {"accuracy": 1.0 if extracted == ground_truth.strip().upper() else 0.0}
'''

CODE_DEFINITION_KWARGS = {
    "code_text": CODE_TEXT,
    "init_parameters": {},
    "data_schema": {
        "response": {"type": "string"},
        "ground_truth": {"type": "string"},
    },
    "metric_name": "accuracy",
    "metric": {
        "type": "ordinal",
        "desirable_direction": "increase",
        "min_value": 0.0,
        "max_value": 1.0,
        "is_primary": True,
    },
}

# Strict fallback prompt: returns 1 or 0 only. Used if CodeBasedEvaluatorDefinition
# is not available in the runtime SDK.
PROMPT_FALLBACK_CONFIG = {
    "name": EVALUATOR_NAME,
    "display_name": EVALUATOR_DISPLAY_NAME,
    "description": EVALUATOR_DESCRIPTION,
    "prompt": (
        "You are a strict grader for a multiple-choice video question.\n"
        "You will receive RESPONSE and GROUND_TRUTH. GROUND_TRUTH is a single letter "
        "(A, B, C, or D).\n"
        "Extract the first letter A, B, C, or D that appears in RESPONSE (ignoring "
        "any prefix like 'Answer:'). If that letter equals GROUND_TRUTH, output the "
        "single token `1`. Otherwise output the single token `0`. Output nothing else.\n\n"
        "RESPONSE:\n{response}\n\n"
        "GROUND_TRUTH:\n{ground_truth}"
    ),
    "scale_min": 0.0,
    "scale_max": 1.0,
}
