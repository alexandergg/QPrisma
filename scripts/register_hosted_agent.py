#!/usr/bin/env python3
"""
Register or update the QPrisma Video Agent as a Hosted Agent in Azure AI Foundry.

Uses the Azure AI Projects SDK to create a new agent version pointing to
a container image in ACR.  Idempotent — safe to re-run on every deploy.

Usage:
    python scripts/register_hosted_agent.py \
        --project-endpoint "https://aif-qprisma-dev.services.ai.azure.com/api/projects/aif-qprisma-dev-project" \
        --image "acrqprismadev.azurecr.io/qprisma-video-agent:abc123" \
        [--agent-name qprisma-video-agent] \
        [--cpu 2] [--memory 4Gi]

Environment:
    Authenticates via DefaultAzureCredential (OIDC in CI, az login locally).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Register QPrisma hosted agent in Azure AI Foundry",
    )
    parser.add_argument(
        "--project-endpoint",
        required=True,
        help="Foundry project endpoint URL",
    )
    parser.add_argument(
        "--image",
        required=True,
        help="Full ACR image URI with tag (e.g. myacr.azurecr.io/agent:v1)",
    )
    parser.add_argument(
        "--agent-name",
        default="qprisma-video-agent",
        help="Agent name in Foundry (default: qprisma-video-agent)",
    )
    parser.add_argument("--cpu", default="2", help="CPU allocation (default: 2)")
    parser.add_argument("--memory", default="4Gi", help="Memory allocation (default: 4Gi)")
    parser.add_argument(
        "--env-vars",
        default=None,
        help="JSON string of additional environment variables",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    try:
        from azure.ai.projects import AIProjectClient
        from azure.ai.projects.models import (
            AgentProtocol,
            HostedAgentDefinition,
            ProtocolVersionRecord,
        )
        from azure.identity import DefaultAzureCredential
    except ImportError:
        logger.error(
            "Missing SDK packages. Install with:\n"
            "  pip install 'azure-ai-projects>=1.0.0b7' azure-identity"
        )
        return 1

    logger.info("Connecting to Foundry project: %s", args.project_endpoint)
    client = AIProjectClient(
        endpoint=args.project_endpoint,
        credential=DefaultAzureCredential(),
        allow_preview=True,
    )

    # Build environment variables dict
    env_vars: dict[str, str] = {
        "AZURE_AI_PROJECT_ENDPOINT": args.project_endpoint,
    }
    if args.env_vars:
        env_vars.update(json.loads(args.env_vars))

    logger.info("Creating agent version: %s (image: %s)", args.agent_name, args.image)
    agent = client.agents.create_version(
        agent_name=args.agent_name,
        definition=HostedAgentDefinition(
            container_protocol_versions=[
                ProtocolVersionRecord(
                    protocol=AgentProtocol.RESPONSES, version="v1"
                ),
            ],
            cpu=args.cpu,
            memory=args.memory,
            image=args.image,
            environment_variables=env_vars,
        ),
    )

    logger.info(
        "Agent registered successfully: name=%s, version=%s",
        agent.name,
        agent.version,
    )

    # Output for GitHub Actions (modern $GITHUB_OUTPUT format)
    github_output = os.environ.get("GITHUB_OUTPUT", "")
    if github_output:
        with open(github_output, "a") as f:
            f.write(f"agent_name={agent.name}\n")
            f.write(f"agent_version={agent.version}\n")
    else:
        print(f"agent_name={agent.name}")
        print(f"agent_version={agent.version}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
