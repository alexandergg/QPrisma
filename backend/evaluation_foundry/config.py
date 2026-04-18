"""
Foundry Evaluation Configuration
=================================

Centralized configuration for Azure AI Foundry evaluation runs.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Agent identity
# ---------------------------------------------------------------------------
AGENT_NAME = "qprisma-video-agent"

# ---------------------------------------------------------------------------
# Built-in evaluator catalog
# ---------------------------------------------------------------------------

QUALITY_EVALUATORS: list[str] = [
    "builtin.coherence",
    "builtin.fluency",
    "builtin.task_adherence",
    "builtin.relevance",
]

AGENT_EVALUATORS: list[str] = [
    "builtin.task_completion",
    "builtin.intent_resolution",
    "builtin.tool_call_accuracy",
    "builtin.tool_call_success",
    "builtin.tool_selection",
    "builtin.tool_output_utilization",
]

SAFETY_EVALUATORS: list[str] = [
    "builtin.violence",
    "builtin.hate_unfairness",
    "builtin.sexual",
    "builtin.self_harm",
    # Indirect prompt-injection (XPIA).  Documented as Model-only but the
    # dataset generates `safety-indirect` queries targeting this metric, so
    # we keep it registered — if Foundry no-ops it for the agent target the
    # score simply won't appear in results.
    "builtin.indirect_attack",
    # Additional GA risk-and-safety evaluators that the dataset exercises:
    # `safety-protected` queries target protected_material, and
    # code_vulnerability catches broader safety risks even though it is not
    # currently prompted explicitly.
    #
    # Note: builtin.ungrounded_attributes also targets agent runs, but the
    # current safety dataset does not provide the evaluator `context` field it
    # requires. Keep it out of the default safety batch until the dataset is
    # redesigned with the required schema.
    "builtin.protected_material",
    "builtin.code_vulnerability",
]

# Direct-attack / jailbreak scenarios are NOT a single runtime evaluator.
# Coverage for them is provided by the cloud Foundry AI Red Teaming workflow
# (see `evaluation_foundry/redteam_eval.py` and the `redteam-eval` job in
# `.github/workflows/evaluate-agent.yml`).

# ---------------------------------------------------------------------------
# Custom evaluator names (registered via register_evaluators.py)
# ---------------------------------------------------------------------------
CUSTOM_TEMPORAL_SPECIFICITY = "qprisma.temporal_specificity"
CUSTOM_SOURCE_GROUNDING = "qprisma.source_grounding"

CUSTOM_EVALUATORS: list[str] = [
    CUSTOM_TEMPORAL_SPECIFICITY,
    CUSTOM_SOURCE_GROUNDING,
]

# ---------------------------------------------------------------------------
# Evaluator groups used in data file generation
# ---------------------------------------------------------------------------

# Text-quality evaluation — conversational quality evaluators that only need
# query + response.  No tool_definitions required.
QUALITY_EVAL_EVALUATORS: list[str] = QUALITY_EVALUATORS

# Agent/tool evaluation — evaluators that assess tool selection & execution.
# These require tool_definitions in the data file.
AGENT_EVAL_EVALUATORS: list[str] = AGENT_EVALUATORS

# Safety evaluation
SAFETY_EVAL_EVALUATORS: list[str] = SAFETY_EVALUATORS

# ---------------------------------------------------------------------------
# Environment variable names for test media
# ---------------------------------------------------------------------------
ENV_MEDIA_ID_PREFIX = "EVAL_MEDIA_ID_"  # EVAL_MEDIA_ID_1, EVAL_MEDIA_ID_2, ...
ENV_USER_ID = "EVAL_USER_ID"

# ---------------------------------------------------------------------------
# Output file names
# ---------------------------------------------------------------------------
QUALITY_EVAL_FILE = "quality-eval.json"
AGENT_EVAL_FILE = "agent-eval.json"
SAFETY_EVAL_FILE = "safety-eval.json"
