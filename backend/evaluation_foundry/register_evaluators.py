"""
Custom Evaluator Registration
================================

Registers QPrisma's custom evaluators with Azure AI Foundry.

Usage:
    python -m evaluation_foundry.register_evaluators

Environment variables:
    AZURE_AI_PROJECT_ENDPOINT — Foundry project endpoint URL
"""

from __future__ import annotations

import logging
import os
import sys

from evaluation_foundry.evaluators.source_grounding import (
    EVALUATOR_CONFIG as SOURCE_GROUNDING_CONFIG,
)
from evaluation_foundry.evaluators.temporal_specificity import (
    EVALUATOR_CONFIG as TEMPORAL_SPECIFICITY_CONFIG,
)

logger = logging.getLogger(__name__)

ALL_EVALUATORS = [TEMPORAL_SPECIFICITY_CONFIG, SOURCE_GROUNDING_CONFIG]


def register_evaluators(endpoint: str, *, dry_run: bool = False) -> int:
    """Register all custom evaluators with the Foundry project.

    Returns:
        Number of evaluators successfully registered.
    """
    if dry_run:
        for cfg in ALL_EVALUATORS:
            logger.info("[DRY RUN] Would register: %s", cfg["name"])
        return len(ALL_EVALUATORS)

    try:
        from azure.ai.projects import AIProjectClient
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
        try:
            logger.info("Registering evaluator: %s", name)
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
                version="1",
                display_name=cfg["display_name"],
                description=cfg["description"],
                definition=definition,
            )
            client.beta.evaluators.create_version(name, evaluator_version)
            logger.info("  ✓ Registered: %s", name)
            registered += 1
        except Exception as exc:
            # Check if it's an "already exists" error
            exc_str = str(exc).lower()
            if "already exists" in exc_str or "conflict" in exc_str:
                logger.info("  → Already exists: %s (skipping)", name)
                registered += 1
            else:
                logger.error("  ✗ Failed to register %s: %s", name, exc)

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

    total = len(ALL_EVALUATORS)
    registered = register_evaluators(endpoint, dry_run=dry_run)
    logger.info("Registered %d/%d evaluators", registered, total)

    return 0 if registered == total else 1


if __name__ == "__main__":
    sys.exit(main())
