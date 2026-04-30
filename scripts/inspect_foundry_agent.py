"""Safely inspect a Foundry hosted agent without printing secrets.

The Foundry data-plane response can include the hosted definition and plaintext
environment variables. This helper only emits allowlisted diagnostics and
redacts secret-shaped fields before writing JSON to stdout or a file.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from azure.identity import DefaultAzureCredential


DEFAULT_METADATA_PATH = Path(".foundry") / "agent-metadata.yaml"
DEFAULT_API_VERSION = "v1"
TOKEN_SCOPE = "https://ai.azure.com/.default"
SENSITIVE_KEY_RE = re.compile(
    r"(password|secret|token|credential|connection[_-]?string|account[_-]?key|sas|environment_variables)",
    re.IGNORECASE,
)


def _load_metadata(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore[import-untyped]

        loaded = yaml.safe_load(text)
        return loaded if isinstance(loaded, dict) else {}
    except ModuleNotFoundError:
        return _load_minimal_metadata(text)


def _load_minimal_metadata(text: str) -> dict[str, Any]:
    """Parse only the metadata fields this script needs when PyYAML is absent."""
    result: dict[str, Any] = {"environments": {}}
    current_env: str | None = None
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if line.startswith("defaultEnvironment:"):
            result["defaultEnvironment"] = stripped.split(":", 1)[1].strip()
            continue
        env_match = re.match(r"^  ([A-Za-z0-9_-]+):\s*$", line)
        if env_match:
            current_env = env_match.group(1)
            result["environments"].setdefault(current_env, {})
            continue
        field_match = re.match(r"^    (projectEndpoint|agentName):\s*(.+?)\s*$", line)
        if current_env and field_match:
            result["environments"][current_env][field_match.group(1)] = field_match.group(2)
    return result


def _resolve_from_metadata(metadata: dict[str, Any], environment: str | None) -> tuple[str, str]:
    environments = metadata.get("environments")
    if not isinstance(environments, dict):
        return "", ""
    env_name = environment or str(metadata.get("defaultEnvironment") or "")
    selected = environments.get(env_name)
    if not isinstance(selected, dict):
        return "", ""
    endpoint = str(selected.get("projectEndpoint") or "")
    agent_name = str(selected.get("agentName") or "")
    return endpoint, agent_name


def _redact_scalar(value: Any) -> Any:
    if value is None or isinstance(value, bool | int | float):
        return value
    text = str(value)
    if not text:
        return text
    if len(text) <= 8:
        return "***"
    return f"{text[:4]}...{text[-4:]}"


def redact(value: Any, key: str = "") -> Any:
    """Recursively redact secret-shaped keys and values."""
    if SENSITIVE_KEY_RE.search(key):
        return _redact_scalar(value) if not isinstance(value, list | dict) else "***REDACTED***"
    if isinstance(value, dict):
        return {str(k): redact(v, str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(item, key) for item in value]
    return value


def _presence(value: Any) -> str:
    if value in (None, "", [], {}):
        return "absent"
    return "present"


def summarize_agent_payload(payload: dict[str, Any]) -> dict[str, Any]:
    versions = payload.get("versions")
    latest = versions.get("latest") if isinstance(versions, dict) else None
    if not isinstance(latest, dict):
        latest = {}
    instance_identity = payload.get("instance_identity") or latest.get("instance_identity")
    blueprint = (
        payload.get("blueprint")
        or payload.get("agent_blueprint")
        or latest.get("blueprint")
        or latest.get("agent_blueprint")
    )
    summary = {
        "id": payload.get("id"),
        "name": payload.get("name"),
        "object": payload.get("object"),
        "latest_version": {
            "id": latest.get("id"),
            "version": latest.get("version"),
            "status": latest.get("status"),
        },
        "identity": {
            "presence": _presence(instance_identity),
            "principal_id": (
                redact(instance_identity.get("principal_id"), "principal_id")
                if isinstance(instance_identity, dict)
                else None
            ),
        },
        "blueprint": {
            "presence": _presence(blueprint),
            "value": redact(blueprint, "blueprint"),
        },
    }
    return redact(summary)


def fetch_agent_payload(endpoint: str, agent_name: str, api_version: str) -> dict[str, Any]:
    credential = DefaultAzureCredential()
    token = credential.get_token(TOKEN_SCOPE).token
    url = f"{endpoint.rstrip('/')}/agents/{agent_name}?api-version={api_version}"
    request = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Foundry-Features": "HostedAgents=V1Preview",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        body = response.read().decode("utf-8")
    payload = json.loads(body)
    if not isinstance(payload, dict):
        raise RuntimeError("Foundry returned a non-object response")
    return payload


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Safely inspect a Foundry hosted agent")
    parser.add_argument("--metadata", type=Path, default=DEFAULT_METADATA_PATH)
    parser.add_argument("--environment", default=os.environ.get("QPRISMA_ENVIRONMENT"))
    parser.add_argument("--endpoint", default=os.environ.get("AZURE_AI_PROJECT_ENDPOINT", ""))
    parser.add_argument("--agent-name", default=os.environ.get("AGENT_NAME", ""))
    parser.add_argument("--api-version", default=os.environ.get("FOUNDRY_AGENT_API_VERSION", DEFAULT_API_VERSION))
    parser.add_argument("--output", type=Path, help="Optional JSON output path")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    metadata = _load_metadata(args.metadata)
    metadata_endpoint, metadata_agent = _resolve_from_metadata(metadata, args.environment)
    endpoint = args.endpoint or metadata_endpoint
    agent_name = args.agent_name or metadata_agent
    if not endpoint or not agent_name:
        print(
            "ERROR: provide --endpoint and --agent-name, or keep .foundry/agent-metadata.yaml current",
            file=sys.stderr,
        )
        return 2

    try:
        payload = fetch_agent_payload(endpoint, agent_name, args.api_version)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, RuntimeError) as exc:
        print(f"ERROR: could not inspect Foundry agent '{agent_name}': {exc}", file=sys.stderr)
        return 1

    result = {
        "endpoint": _redact_scalar(endpoint),
        "agent_name": agent_name,
        "api_version": args.api_version,
        "agent": summarize_agent_payload(payload),
    }
    text = json.dumps(result, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
