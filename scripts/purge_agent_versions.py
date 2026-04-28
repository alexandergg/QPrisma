"""Purge a hosted agent and ALL its versions from Microsoft Foundry.

Used to clean up the legacy ``qprisma-video-agent`` (and its accumulated
versions registered with the deprecated
``azure-ai-agentserver-langgraph`` runtime) before re-deploying with the
refreshed public preview (``azure-ai-agentserver-responses``).

The script is **idempotent**: missing agents/versions are reported and
ignored. Use ``--dry-run`` to preview without deleting.

Usage:
    az login
    export AZURE_AI_PROJECT_ENDPOINT="https://<account>.services.ai.azure.com/api/projects/<project>"
    python scripts/purge_agent_versions.py [--dry-run] [--agent-name qprisma-video-agent]

Reference:
    https://learn.microsoft.com/azure/foundry/agents/how-to/manage-hosted-agent
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from collections.abc import Iterable
from typing import Any

from azure.ai.projects import AIProjectClient
from azure.core.exceptions import HttpResponseError, ResourceNotFoundError
from azure.identity import DefaultAzureCredential

DEFAULT_AGENT_NAME = "qprisma-video-agent"


def _extract_version(item: Any) -> str | None:
    """Return the ``version`` attribute or mapping key from an SDK model."""
    if item is None:
        return None
    if isinstance(item, dict):
        version = item.get("version")
    else:
        version = getattr(item, "version", None)
    return version if isinstance(version, str) and version else None


def list_versions(client: AIProjectClient, agent_name: str) -> list[str]:
    """List every version of ``agent_name``. Returns ``[]`` if missing."""
    try:
        items: Iterable[Any] = client.agents.list_versions(agent_name=agent_name)
    except ResourceNotFoundError:
        return []
    except HttpResponseError as exc:
        if exc.status_code == 404:
            return []
        raise

    versions: list[str] = []
    for item in items:
        version = _extract_version(item)
        if version:
            versions.append(version)
    return versions


def delete_version(
    client: AIProjectClient, agent_name: str, version: str, *, dry_run: bool
) -> bool:
    """Delete a single agent version. Returns ``True`` if a delete was issued."""
    if dry_run:
        print(f"  [dry-run] would delete version: {version}")
        return False
    try:
        client.agents.delete_version(agent_name=agent_name, agent_version=version)
        print(f"  deleted version: {version}")
        return True
    except ResourceNotFoundError:
        print(f"  version already gone: {version}")
        return False
    except HttpResponseError as exc:
        if exc.status_code == 404:
            print(f"  version already gone: {version}")
            return False
        print(f"  WARNING: failed to delete version {version}: {exc}")
        return False


def delete_agent(
    client: AIProjectClient,
    agent_name: str,
    *,
    dry_run: bool,
    project_endpoint: str | None = None,
) -> bool:
    """Delete the agent envelope itself. Returns ``True`` if a delete was issued."""
    if dry_run:
        print(f"[dry-run] would delete agent: {agent_name}")
        return False
    try:
        client.agents.delete(agent_name=agent_name)
        print(f"deleted agent: {agent_name}")
        return True
    except ResourceNotFoundError:
        print(f"agent already gone: {agent_name}")
        return False
    except HttpResponseError as exc:
        if exc.status_code == 404:
            print(f"agent already gone: {agent_name}")
            return False
        print(f"WARNING: SDK delete failed for agent {agent_name}: {exc}")
        if project_endpoint:
            print(f"Trying REST fallback for {agent_name}...")
            return _rest_delete_assistant(project_endpoint, agent_name)
        return False


def _rest_delete_assistant(project_endpoint: str, assistant_id: str) -> bool:
    """Diagnostic REST fallback: ``DELETE /assistants/{id}`` via ``az rest``.

    Used only if the SDK paths above fail. Returns ``True`` if the call
    succeeded (or the resource was already gone).
    """
    az_path = shutil.which("az")
    if not az_path:
        print("REST fallback skipped: 'az' CLI not found on PATH.")
        return False

    base = project_endpoint.rstrip("/")
    url = f"{base}/assistants/{assistant_id}?api-version=v1"

    try:
        proc = subprocess.run(
            [
                az_path,
                "rest",
                "--method",
                "DELETE",
                "--url",
                url,
                "--resource",
                "https://ai.azure.com",
            ],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        print(f"REST fallback failed to invoke 'az rest': {exc}")
        return False

    if proc.returncode == 0:
        print(f"  REST fallback deleted assistant {assistant_id}")
        return True

    stderr = (proc.stderr or proc.stdout or "").strip()
    if "404" in stderr or "NotFound" in stderr:
        print(f"  REST fallback: assistant {assistant_id} already gone")
        return True

    print(
        f"  REST fallback returned non-zero exit ({proc.returncode}): "
        f"{stderr[:500]}"
    )
    return False


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--agent-name",
        default=os.environ.get("AGENT_NAME", DEFAULT_AGENT_NAME),
        help=f"Hosted agent name to purge (default: {DEFAULT_AGENT_NAME}).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List what would be deleted without making any changes.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    project_endpoint = os.environ.get("AZURE_AI_PROJECT_ENDPOINT", "").strip()
    if not project_endpoint:
        print("ERROR: AZURE_AI_PROJECT_ENDPOINT is required.")
        return 1

    print(f"Project: {project_endpoint}")
    print(f"Agent:   {args.agent_name}")
    if args.dry_run:
        print("Mode:    dry-run (no deletes will be issued)")
    print()

    client = AIProjectClient(
        endpoint=project_endpoint,
        credential=DefaultAzureCredential(),
        allow_preview=True,
    )

    versions = list_versions(client, args.agent_name)
    if versions:
        print(f"Found {len(versions)} version(s):")
        for v in versions:
            print(f"  - {v}")
    else:
        print("No versions found (agent may already be absent).")

    print()
    print("Deleting versions...")
    for version in versions:
        delete_version(client, args.agent_name, version, dry_run=args.dry_run)

    print()
    print("Deleting agent envelope...")
    delete_agent(
        client,
        args.agent_name,
        dry_run=args.dry_run,
        project_endpoint=project_endpoint,
    )

    print()
    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
