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
    "builtin.response_completeness",
]

RAG_EVALUATORS: list[str] = [
    "builtin.groundedness",
    "builtin.relevance",
]

AGENT_EVALUATORS: list[str] = [
    "builtin.task_completion",
    "builtin.tool_call_accuracy",
    "builtin.tool_call_success",
]

SAFETY_EVALUATORS: list[str] = [
    "builtin.violence",
    "builtin.hate_unfairness",
    "builtin.sexual",
    "builtin.self_harm",
    "builtin.indirect_attack",
]

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

# General quality evaluation (no video context needed for some queries)
GENERAL_EVAL_EVALUATORS: list[str] = (
    QUALITY_EVALUATORS + RAG_EVALUATORS + AGENT_EVALUATORS + CUSTOM_EVALUATORS
)

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
GENERAL_EVAL_FILE = "general-eval.json"
SAFETY_EVAL_FILE = "safety-eval.json"
