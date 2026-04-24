"""
Custom Evaluator Registration
================================

Registers QPrisma's custom evaluators with Azure AI Foundry.

Usage:
    python -m evaluation_foundry.register_evaluators

Environment variables:
    AZURE_AI_PROJECT_ENDPOINT — Foundry project endpoint URL

Evaluator definition types
--------------------------
``azure-ai-projects==2.0.1`` exposes two evaluator-definition shapes (verified
via ``azure.ai.projects.models._models``):

* ``PromptBasedEvaluatorDefinition(prompt_text=..., metrics={...})`` — the
  pattern used below for ``temporal_specificity`` and ``source_grounding``.
  Use this for any judge-style evaluator scored by an LLM rubric.
* ``CodeBasedEvaluatorDefinition(code_text=..., init_parameters=...,
  data_schema=..., metrics=...)`` — pure-Python evaluator whose ``code_text``
  runs server-side. Use this for **deterministic** evaluators where a regex /
  string compare is the right answer (e.g. ``qprisma.video_mme_mcq``: extract
  ``^[A-D]`` from the response and compare to ``ground_truth``). Falls back
  gracefully to a strict ``PromptBasedEvaluatorDefinition`` returning ``1.0``
  / ``0.0`` if a code-based path is unavailable in a given environment.

Both definition types are accepted by ``EvaluatorVersion(definition=...)`` and
registered via ``client.beta.evaluators.create_version(name, version)``.
"""

from __future__ import annotations

import logging
import os
import sys

from evaluation_foundry.evaluators import long_context_grounding as LONG_CONTEXT_GROUNDING
from evaluation_foundry.evaluators import video_mme_mcq as VIDEO_MME_MCQ
from evaluation_foundry.evaluators.source_grounding import (
    EVALUATOR_CONFIG as SOURCE_GROUNDING_CONFIG,
)
from evaluation_foundry.evaluators.temporal_specificity import (
    EVALUATOR_CONFIG as TEMPORAL_SPECIFICITY_CONFIG,
)

logger = logging.getLogger(__name__)

ALL_EVALUATORS = [TEMPORAL_SPECIFICITY_CONFIG, SOURCE_GROUNDING_CONFIG]

# Code/prompt-fallback evaluators registered after the prompt-only ones.
# Each entry has the shape (module) where ``module`` exposes ``EVALUATOR_NAME``,
# ``EVALUATOR_DISPLAY_NAME``, ``EVALUATOR_DESCRIPTION``, ``CODE_DEFINITION_KWARGS``
# and ``PROMPT_FALLBACK_CONFIG``. See ``video_mme_mcq.py`` for the canonical shape.
CODE_OR_PROMPT_EVALUATORS = [VIDEO_MME_MCQ, LONG_CONTEXT_GROUNDING]

FORBIDDEN_CODE_TEXT_TOKENS = ("compile(",)


def _validate_code_text_compatibility(name: str, code_text: str) -> None:
    """Reject grader sources that Foundry's python_grader is known to ban."""
    lowered = code_text.lower()
    for token in FORBIDDEN_CODE_TEXT_TOKENS:
        if token in lowered:
            raise ValueError(
                f"{name} code_text contains forbidden token {token!r}; "
                "Foundry rejects grader sources that reference compile()."
            )


def _register_code_or_prompt_evaluator(client, models_module, evaluator_module) -> bool:
    """Register a deterministic evaluator with code-based-then-prompt fallback.

    Tries ``CodeBasedEvaluatorDefinition`` first (preferred — runs server-side
    Python, zero judge cost). Falls back to a strict prompt-judge defined by the
    module's ``PROMPT_FALLBACK_CONFIG`` if the code-based path is unavailable in
    this SDK build.
    """
    name = evaluator_module.EVALUATOR_NAME
    EvaluatorMetric = models_module.EvaluatorMetric
    EvaluatorVersion = models_module.EvaluatorVersion

    metric_kwargs = evaluator_module.CODE_DEFINITION_KWARGS["metric"]
    metric = EvaluatorMetric(
        type=metric_kwargs["type"],
        desirable_direction=metric_kwargs["desirable_direction"],
        min_value=metric_kwargs["min_value"],
        max_value=metric_kwargs["max_value"],
        is_primary=metric_kwargs["is_primary"],
    )
    metric_name = evaluator_module.CODE_DEFINITION_KWARGS["metric_name"]
    # Each evaluator module may declare its own version string. Bumping it on a
    # source change is required because ``create_version`` returns "already
    # exists" for an existing version and Foundry then keeps serving the stale
    # ``code_text``/``prompt_text``. Default of "1" preserves prior behavior
    # for evaluators that have not yet adopted ``EVALUATOR_VERSION``.
    version = getattr(evaluator_module, "EVALUATOR_VERSION", "1")

    code_def_cls = getattr(models_module, "CodeBasedEvaluatorDefinition", None)
    if code_def_cls is not None:
        try:
            code_text = evaluator_module.CODE_DEFINITION_KWARGS["code_text"]
            _validate_code_text_compatibility(name, code_text)
            definition = code_def_cls(
                code_text=code_text,
                init_parameters=evaluator_module.CODE_DEFINITION_KWARGS["init_parameters"],
                data_schema=evaluator_module.CODE_DEFINITION_KWARGS["data_schema"],
                metrics={metric_name: metric},
            )
            client.beta.evaluators.create_version(
                name,
                EvaluatorVersion(
                    version=version,
                    display_name=evaluator_module.EVALUATOR_DISPLAY_NAME,
                    description=evaluator_module.EVALUATOR_DESCRIPTION,
                    definition=definition,
                ),
            )
            logger.info("  ✓ Registered (code-based): %s v%s", name, version)
            return True
        except Exception as exc:
            exc_str = str(exc).lower()
            if "already exists" in exc_str or "conflict" in exc_str:
                logger.info("  → Already exists: %s v%s (skipping)", name, version)
                return True
            logger.warning("  Code-based registration failed (%s); trying prompt fallback", exc)

    cfg = evaluator_module.PROMPT_FALLBACK_CONFIG
    PromptBasedEvaluatorDefinition = models_module.PromptBasedEvaluatorDefinition
    try:
        definition = PromptBasedEvaluatorDefinition(
            prompt_text=cfg["prompt"],
            metrics={metric_name: metric},
        )
        client.beta.evaluators.create_version(
            name,
            EvaluatorVersion(
                version=version,
                display_name=cfg["display_name"],
                description=cfg["description"],
                definition=definition,
            ),
        )
        logger.info("  ✓ Registered (prompt fallback): %s v%s", name, version)
        return True
    except Exception as exc:
        exc_str = str(exc).lower()
        if "already exists" in exc_str or "conflict" in exc_str:
            logger.info("  → Already exists: %s (skipping)", name)
            return True
        logger.error("  ✗ Failed to register %s: %s", name, exc)
        return False


def register_evaluators(endpoint: str, *, dry_run: bool = False) -> int:
    """Register all custom evaluators with the Foundry project.

    Returns:
        Number of evaluators successfully registered.
    """
    if dry_run:
        for cfg in ALL_EVALUATORS:
            logger.info("[DRY RUN] Would register: %s", cfg["name"])
        for module in CODE_OR_PROMPT_EVALUATORS:
            logger.info("[DRY RUN] Would register: %s", module.EVALUATOR_NAME)
        return len(ALL_EVALUATORS) + len(CODE_OR_PROMPT_EVALUATORS)

    try:
        from azure.ai.projects import AIProjectClient
        from azure.ai.projects import models as projects_models
        from azure.ai.projects.models import (
            EvaluatorMetric,
            EvaluatorVersion,
            PromptBasedEvaluatorDefinition,
        )
        from azure.identity import DefaultAzureCredential
    except ImportError:
        logger.error(
            "azure-ai-projects or azure-identity not installed. "
            "Install with: pip install azure-ai-projects azure-identity"
        )
        return 0

    client = AIProjectClient(
        endpoint=endpoint,
        credential=DefaultAzureCredential(),
    )

    registered = 0
    for cfg in ALL_EVALUATORS:
        name = cfg["name"]
        # Pull version from config (default "1" for back-compat). Foundry treats
        # "already exists" as a no-op, so prompt edits without a version bump
        # silently fail to propagate — same trap as the code-based evaluators.
        version = cfg.get("version", "1")
        try:
            logger.info("Registering evaluator: %s (version %s)", name, version)
            metric_name = name.split(".")[-1]  # e.g. "temporal_specificity"
            definition = PromptBasedEvaluatorDefinition(
                prompt_text=cfg["prompt"],
                metrics={
                    metric_name: EvaluatorMetric(
                        type="ordinal",
                        desirable_direction="increase",
                        min_value=1.0,
                        max_value=5.0,
                        is_primary=True,
                    )
                },
            )
            evaluator_version = EvaluatorVersion(
                version=version,
                display_name=cfg["display_name"],
                description=cfg["description"],
                definition=definition,
            )
            client.beta.evaluators.create_version(name, evaluator_version)
            logger.info("  ✓ Registered: %s v%s", name, version)
            registered += 1
        except Exception as exc:
            # Check if it's an "already exists" error
            exc_str = str(exc).lower()
            if "already exists" in exc_str or "conflict" in exc_str:
                logger.info("  → Already exists: %s v%s (skipping)", name, version)
                registered += 1
            else:
                logger.error("  ✗ Failed to register %s v%s: %s", name, version, exc)

    # Register deterministic / code-or-prompt-fallback evaluators.
    for module in CODE_OR_PROMPT_EVALUATORS:
        logger.info("Registering evaluator: %s", module.EVALUATOR_NAME)
        if _register_code_or_prompt_evaluator(client, projects_models, module):
            registered += 1

    return registered


def main() -> int:
    """Entry point for evaluator registration."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    endpoint = os.environ.get("AZURE_AI_PROJECT_ENDPOINT", "")
    dry_run = "--dry-run" in sys.argv

    if not endpoint and not dry_run:
        logger.error(
            "AZURE_AI_PROJECT_ENDPOINT must be set. " "Use --dry-run to test without a connection."
        )
        return 1

    total = len(ALL_EVALUATORS) + len(CODE_OR_PROMPT_EVALUATORS)
    registered = register_evaluators(endpoint, dry_run=dry_run)
    logger.info("Registered %d/%d evaluators", registered, total)

    return 0 if registered == total else 1


if __name__ == "__main__":
    sys.exit(main())
