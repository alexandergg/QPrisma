"""Regression test for the hosted-agent deployment protocol version.

Guards against re-introducing the bug where ``scripts/deploy_agent.py``
registered the responses protocol with version ``"v1"`` instead of
``"1.0.0"``. The mismatch caused the Foundry hosted agent to reject all
requests from the Video-MME benchmark eval action with HTTP 400:

    Unsupported responses protocol version 'v1' for agent
    'qprisma-video-agent:N'. Please use version '1.0.0'.

The version string here must stay in sync with
``backend/agent/hosted/agent.yaml`` and with the ``responses`` protocol
served by ``azure-ai-agentserver-langgraph`` at runtime.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEPLOY_AGENT = REPO_ROOT / "scripts" / "deploy_agent.py"
AGENT_MANIFEST = REPO_ROOT / "backend" / "agent" / "hosted" / "agent.yaml"


def test_deploy_agent_uses_responses_protocol_version_1_0_0() -> None:
    source = DEPLOY_AGENT.read_text(encoding="utf-8")
    pattern = re.compile(
        r"ProtocolVersionRecord\(\s*protocol\s*=\s*AgentProtocol\.RESPONSES\s*,"
        r"\s*version\s*=\s*\"([^\"]+)\"\s*\)"
    )
    matches = pattern.findall(source)
    assert matches, (
        "Expected ProtocolVersionRecord(protocol=AgentProtocol.RESPONSES, "
        f"version=...) in {DEPLOY_AGENT}"
    )
    assert all(v == "1.0.0" for v in matches), (
        "Hosted agent must register the responses protocol with version "
        f"'1.0.0' to match agent.yaml and the runtime; got: {matches}"
    )


def test_agent_yaml_responses_version_matches_deploy_script() -> None:
    manifest = AGENT_MANIFEST.read_text(encoding="utf-8")
    # Match a YAML block of the form:
    #   - protocol: responses
    #     version: "1.0.0"
    pattern = re.compile(
        r"-\s*protocol:\s*responses\s*\n\s*version:\s*\"?([^\"\s]+)\"?",
        re.MULTILINE,
    )
    match = pattern.search(manifest)
    assert match, f"Could not find responses protocol version in {AGENT_MANIFEST}"
    assert match.group(1) == "1.0.0", (
        f"agent.yaml responses version must equal '1.0.0'; got: {match.group(1)}"
    )
