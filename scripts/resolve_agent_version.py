"""
Agent Version Resolver
=======================

Resolves the latest deployed version of the QPrisma Foundry Hosted Agent.

Usage:
    python scripts/resolve_agent_version.py [--strict] [--agent-version latest|<version>]

Outputs (to GITHUB_OUTPUT if running in GitHub Actions):
    agent_id=qprisma-video-agent:<version>
"""

from __future__ import annotations

import argparse
import os
import sys


LATEST_VERSION_ALIASES = {"", "latest", "current", "auto"}


class AgentVersionResolutionError(RuntimeError):
    """Raised when the hosted agent version cannot be resolved safely."""


def _requested_agent_id(agent_name: str, requested_version: str | None) -> str | None:
    """Return a concrete agent id when the caller supplied an explicit version."""
    raw_version = (
        requested_version
        if requested_version is not None
        else os.environ.get("AGENT_VERSION_OVERRIDE", "")
    )
    version = raw_version.strip()
    if version.lower() in LATEST_VERSION_ALIASES:
        return None
    if ":" in version:
        requested_name, requested_version_number = version.split(":", 1)
        if not requested_name or not requested_version_number:
            raise AgentVersionResolutionError(
                f"Invalid agent version override '{version}'. Expected '<version>' or '{agent_name}:<version>'."
            )
        if requested_name != agent_name:
            raise AgentVersionResolutionError(
                f"Agent version override '{version}' does not match AGENT_NAME '{agent_name}'."
            )
        return version
    return f"{agent_name}:{version}"


def resolve_agent_version(
    *,
    strict: bool = False,
    requested_version: str | None = None,
) -> str:
    """Resolve the latest agent version from Foundry.

    Args:
        strict: Fail instead of falling back to ``<agent>:1`` when resolution
            cannot be completed. Evaluation and red-team jobs should always use
            this mode so they measure the deployed revision they intend to test.
        requested_version: Optional version override. Values ``latest``,
            ``current``, ``auto``, and an empty value resolve the concrete latest
            version from Foundry; any other value is treated as an explicit
            version and returned as ``<agent>:<version>``.

    Returns:
        Agent identifier in the format ``name:version``.
    """
    agent_name = os.environ.get("AGENT_NAME", "qprisma-video-agent")
    explicit_agent_id = _requested_agent_id(agent_name, requested_version)
    if explicit_agent_id:
        print(f"Using explicit agent version: {explicit_agent_id}")
        return explicit_agent_id

    endpoint = os.environ.get("AZURE_AI_PROJECT_ENDPOINT", "")

    if not endpoint:
        message = "AZURE_AI_PROJECT_ENDPOINT not set"
        if strict:
            raise AgentVersionResolutionError(message)
        print(f"WARNING: {message} - using fallback version")
        return f"{agent_name}:1"

    try:
        from azure.ai.projects import AIProjectClient
        from azure.identity import DefaultAzureCredential

        client = AIProjectClient(
            endpoint=endpoint,
            credential=DefaultAzureCredential(),
        )
        agent = client.agents.get(agent_name=agent_name)
        version = str(getattr(agent, "version", "") or "").strip()
        if not version:
            raise AgentVersionResolutionError(
                f"Foundry returned no version for agent '{agent_name}'"
            )
        agent_id = f"{agent_name}:{version}"
        print(f"Resolved agent: {agent_id}")
        return agent_id
    except Exception as exc:
        if strict:
            if isinstance(exc, AgentVersionResolutionError):
                raise
            raise AgentVersionResolutionError(
                f"Could not resolve agent version for '{agent_name}' at '{endpoint}': {exc}"
            ) from exc
        print(f"WARNING: Could not resolve agent version: {exc}")
        fallback = f"{agent_name}:1"
        print(f"Using fallback: {fallback}")
        return fallback


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Resolve the deployed Foundry agent version")
    parser.add_argument(
        "--strict",
        action="store_true",
        default=os.environ.get("QPRISMA_RESOLVE_AGENT_STRICT", "").lower()
        in {"1", "true", "yes"},
        help="Fail if the agent version cannot be resolved instead of falling back to :1",
    )
    parser.add_argument(
        "--agent-version",
        default=os.environ.get("AGENT_VERSION_OVERRIDE"),
        help=(
            "Agent version override. Use 'latest' or leave empty to resolve the "
            "concrete latest Foundry version."
        ),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        agent_id = resolve_agent_version(
            strict=args.strict,
            requested_version=args.agent_version,
        )
    except AgentVersionResolutionError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    # Write to GITHUB_OUTPUT if in CI
    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a", encoding="utf-8") as f:
            f.write(f"agent_id={agent_id}\n")
        print(f"Set GITHUB_OUTPUT: agent_id={agent_id}")
    else:
        print(f"agent_id={agent_id}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
