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

    # Start the agent container (lifecycle: Create → Start)
    logger.info("Starting agent container for %s version %s ...", agent.name, agent.version)
    try:
        import time

        from azure.core.rest import HttpRequest

        # Use the REST API to start the container
        # POST /agents/{name}/versions/{version}/containers/default:start
        start_url = (
            f"{args.project_endpoint}/agents/{agent.name}"
            f"/versions/{agent.version}/containers/default:start"
        )

        start_request = HttpRequest(
            method="POST",
            url=start_url,
            params={"api-version": "2025-05-15-preview"},
            json={"min_replicas": 1, "max_replicas": 1},
        )
        start_response = client._client.send_request(start_request)

        if start_response.status_code in (200, 202):
            logger.info("Agent container start initiated (status=%d)", start_response.status_code)
            # Poll for running state (up to 5 minutes)
            for attempt in range(30):
                time.sleep(10)
                status_url = (
                    f"{args.project_endpoint}/agents/{agent.name}"
                    f"/versions/{agent.version}/containers/default"
                )
                status_request = HttpRequest(
                    method="GET",
                    url=status_url,
                    params={"api-version": "2025-05-15-preview"},
                )
                status_response = client._client.send_request(status_request)
                if status_response.status_code == 200:
                    body = status_response.json()
                    state = body.get("status", body.get("provisioningState", "unknown"))
                    logger.info("Container state: %s (attempt %d/30)", state, attempt + 1)
                    if state.lower() in ("running", "started", "succeeded"):
                        logger.info("Agent container is running!")
                        break
                else:
                    logger.warning("Status check returned %d", status_response.status_code)
            else:
                logger.warning("Agent did not reach running state within 5 minutes — check portal")
        else:
            logger.warning(
                "Start request returned %d: %s",
                start_response.status_code,
                start_response.text(),
            )
    except Exception as e:
        logger.warning("Could not start agent container: %s (start manually from portal)", e)

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
