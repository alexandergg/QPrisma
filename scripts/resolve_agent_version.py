"""
Agent Version Resolver
=======================

Resolves the latest deployed version of the QPrisma Foundry Hosted Agent.

Usage:
    python scripts/resolve_agent_version.py

Outputs (to GITHUB_OUTPUT if running in GitHub Actions):
    agent_id=qprisma-video-agent:<version>
"""

from __future__ import annotations

import os
import sys


def resolve_agent_version() -> str:
    """Resolve the latest agent version from Foundry.

    Returns:
        Agent identifier in the format ``name:version``.
    """
    agent_name = os.environ.get("AGENT_NAME", "qprisma-video-agent")
    endpoint = os.environ.get("AZURE_AI_PROJECT_ENDPOINT", "")

    if not endpoint:
        print("WARNING: AZURE_AI_PROJECT_ENDPOINT not set — using fallback version")
        return f"{agent_name}:1"

    try:
        from azure.ai.projects import AIProjectClient
        from azure.identity import DefaultAzureCredential

        client = AIProjectClient(
            endpoint=endpoint,
            credential=DefaultAzureCredential(),
        )
        agent = client.agents.get(agent_name=agent_name)
        version = getattr(agent, "version", None) or 1
        agent_id = f"{agent_name}:{version}"
        print(f"Resolved agent: {agent_id}")
        return agent_id
    except Exception as exc:
        print(f"WARNING: Could not resolve agent version: {exc}")
        fallback = f"{agent_name}:1"
        print(f"Using fallback: {fallback}")
        return fallback


def main() -> int:
    agent_id = resolve_agent_version()

    # Write to GITHUB_OUTPUT if in CI
    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a") as f:
            f.write(f"agent_id={agent_id}\n")
        print(f"Set GITHUB_OUTPUT: agent_id={agent_id}")
    else:
        print(f"agent_id={agent_id}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
