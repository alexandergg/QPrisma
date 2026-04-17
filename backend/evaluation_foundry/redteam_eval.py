"""
AI Red Teaming Agent runner for the QPrisma video agent
=======================================================

Wraps :class:`azure.ai.evaluation.red_team.RedTeam` to run adversarial
scans against the deployed Foundry agent.  Provides coverage for
**direct-attack / jailbreak** scenarios, which are not a single runtime
evaluator — they require the PyRIT-based Red Teaming Agent.

Usage::

    python -m evaluation_foundry.redteam_eval \\
        --agent-id <AGENT_ID> \\
        --endpoint https://<foundry>.services.ai.azure.com/api/projects/<project> \\
        --strategies base64,flip,morse \\
        --risk-categories violence,hate_unfairness,sexual,self_harm \\
        --output redteam-results.json

Environment variables:
    AZURE_AI_PROJECT_ENDPOINT — Foundry project endpoint URL (fallback for --endpoint)
    QPRISMA_REDTEAM_NUM_OBJECTIVES — per-category objective count (default: 5)

Authentication uses :class:`DefaultAzureCredential`.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_STRATEGIES: list[str] = ["base64", "flip", "morse"]
DEFAULT_RISK_CATEGORIES: list[str] = [
    "violence",
    "hate_unfairness",
    "sexual",
    "self_harm",
]


async def run_redteam_scan(
    *,
    endpoint: str,
    agent_id: str,
    strategies: list[str],
    risk_categories: list[str],
    num_objectives: int,
    output_path: Path,
    scan_name: str,
) -> dict[str, Any]:
    """Execute a Red Team scan against the hosted agent.

    Returns the scan summary dict (also written to ``output_path``).
    """
    try:
        from azure.ai.evaluation.red_team import (
            AttackStrategy,
            RedTeam,
            RiskCategory,
        )
        from azure.identity.aio import DefaultAzureCredential
    except ImportError as exc:
        raise RuntimeError(
            "azure-ai-evaluation[redteam] is required. Install with "
            "`pip install azure-ai-evaluation[redteam]`."
        ) from exc

    # Map string inputs to SDK enums, failing loud on unknown values so
    # typos in CI configuration are caught early.
    def _map_enum(cls: Any, name: str) -> Any:
        try:
            return cls[name.upper()]
        except KeyError as exc:
            valid = ", ".join(m.name.lower() for m in cls)
            raise ValueError(f"Unknown {cls.__name__} '{name}'. Valid values: {valid}") from exc

    mapped_strategies = [_map_enum(AttackStrategy, s) for s in strategies]
    mapped_risks = [_map_enum(RiskCategory, r) for r in risk_categories]

    # Foundry project config dict expected by the SDK
    project_config = {"azure_ai_project": endpoint}

    async with DefaultAzureCredential() as credential:
        red_team = RedTeam(
            azure_ai_project=project_config,
            credential=credential,
            risk_categories=mapped_risks,
            num_objectives=num_objectives,
        )

        # The SDK supports either a model config (model-only scans) or an
        # agent_id (agent scan).  For QPrisma we always target the agent.
        target = {"agent_id": agent_id}

        logger.info(
            "Starting RedTeam scan (agent_id=%s, strategies=%s, risks=%s, " "num_objectives=%d)",
            agent_id,
            [s.name for s in mapped_strategies],
            [r.name for r in mapped_risks],
            num_objectives,
        )

        result = await red_team.scan(
            target=target,
            scan_name=scan_name,
            attack_strategies=mapped_strategies,
            output_path=str(output_path),
        )

    summary = result if isinstance(result, dict) else {"raw": repr(result)}
    logger.info("RedTeam scan complete. Summary keys: %s", list(summary.keys()))
    return summary


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run AI Red Teaming scan against QPrisma agent")
    parser.add_argument("--agent-id", required=True, help="Foundry agent ID to target")
    parser.add_argument(
        "--endpoint",
        default=os.environ.get("AZURE_AI_PROJECT_ENDPOINT"),
        help="Foundry project endpoint URL (env: AZURE_AI_PROJECT_ENDPOINT)",
    )
    parser.add_argument(
        "--strategies",
        default=",".join(DEFAULT_STRATEGIES),
        help=f"Comma-separated attack strategies (default: {','.join(DEFAULT_STRATEGIES)})",
    )
    parser.add_argument(
        "--risk-categories",
        default=",".join(DEFAULT_RISK_CATEGORIES),
        help=("Comma-separated risk categories (default: " f"{','.join(DEFAULT_RISK_CATEGORIES)})"),
    )
    parser.add_argument(
        "--num-objectives",
        type=int,
        default=int(os.environ.get("QPRISMA_REDTEAM_NUM_OBJECTIVES", "5")),
        help="Number of attack objectives per risk category (default: 5)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("redteam-results.json"),
        help="Output JSON path for scan results",
    )
    parser.add_argument(
        "--scan-name",
        default="qprisma-direct-attack-scan",
        help="Scan display name registered in Foundry",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = _parse_args(argv)
    if not args.endpoint:
        logger.error("Missing --endpoint (or AZURE_AI_PROJECT_ENDPOINT env var)")
        return 2

    strategies = [s.strip() for s in args.strategies.split(",") if s.strip()]
    risks = [r.strip() for r in args.risk_categories.split(",") if r.strip()]

    try:
        summary = asyncio.run(
            run_redteam_scan(
                endpoint=args.endpoint,
                agent_id=args.agent_id,
                strategies=strategies,
                risk_categories=risks,
                num_objectives=args.num_objectives,
                output_path=args.output,
                scan_name=args.scan_name,
            )
        )
    except Exception:
        logger.exception("RedTeam scan failed")
        return 1

    # The SDK writes full results to `output_path`; here we print a short
    # summary for CI log visibility.
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if not args.output.exists():
        args.output.write_text(json.dumps(summary, default=str, indent=2), encoding="utf-8")
    logger.info("RedTeam results written to %s", args.output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
