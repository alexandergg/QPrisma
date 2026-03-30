"""Deploy QPrisma hosted agent to Microsoft Foundry.

Registers (or updates) the hosted agent version in Foundry Agent Service,
then starts the agent deployment so it transitions to 'Started' automatically.

Usage:
    az login
    export AZURE_AI_PROJECT_ENDPOINT="https://<account>.services.ai.azure.com/api/projects/<project>"
    export CONTAINER_IMAGE="<acr>.azurecr.io/qprisma-video-agent:latest"
    python scripts/deploy_agent.py

Reference:
    https://learn.microsoft.com/azure/foundry/agents/how-to/deploy-hosted-agent
    https://learn.microsoft.com/azure/foundry/agents/how-to/manage-hosted-agent
"""

import os
import subprocess
import sys

from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import (
    AgentProtocol,
    ImageBasedHostedAgentDefinition,
    ProtocolVersionRecord,
)
from azure.identity import DefaultAzureCredential

AGENT_NAME = "qprisma-video-agent"
ACCOUNT_NAME = "aif-qprisma-dev"
PROJECT_NAME = "aif-qprisma-dev-project"


def start_agent(version: str) -> bool:
    """Start the agent deployment using az cli."""
    cmd = [
        "az", "cognitiveservices", "agent", "start",
        "--account-name", ACCOUNT_NAME,
        "--project-name", PROJECT_NAME,
        "--name", AGENT_NAME,
        "--agent-version", str(version),
    ]
    print(f"Starting agent with: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode == 0:
        print("Agent start command succeeded")
        return True

    print(f"az cognitiveservices agent start failed (rc={result.returncode})")
    if result.stderr:
        print(f"  stderr: {result.stderr.strip()}")
    return False


def main() -> None:
    project_endpoint = os.environ.get("AZURE_AI_PROJECT_ENDPOINT", "")
    container_image = os.environ.get("CONTAINER_IMAGE", "")

    if not project_endpoint or not container_image:
        print("ERROR: AZURE_AI_PROJECT_ENDPOINT and CONTAINER_IMAGE are required")
        sys.exit(1)

    print(f"Deploying agent '{AGENT_NAME}'")
    print(f"  Project: {project_endpoint}")
    print(f"  Image:   {container_image}")

    client = AIProjectClient(
        endpoint=project_endpoint,
        credential=DefaultAzureCredential(),
    )

    agent = client.agents.create_version(
        agent_name=AGENT_NAME,
        description=(
            "QPrisma Video Agent — intelligent video analysis powered by LangGraph. "
            "Searches visual content, audio transcriptions, and knowledge graphs "
            "to answer questions with timestamped citations."
        ),
        definition=ImageBasedHostedAgentDefinition(
            container_protocol_versions=[
                ProtocolVersionRecord(protocol=AgentProtocol.RESPONSES, version="v1"),
            ],
            cpu="4",
            memory="8Gi",
            image=container_image,
            environment_variables={
                "ENVIRONMENT": os.environ.get("ENVIRONMENT", "production"),
                "LOG_LEVEL": "INFO",
            },
        ),
    )

    print(f"Agent registered: {agent.name} (id: {agent.id}, version: {agent.version})")

    # Auto-start the agent deployment
    started = start_agent(agent.version)
    if not started:
        print("WARNING: Agent registered but auto-start failed. Start manually in Foundry portal.")

    # Write version to GITHUB_OUTPUT for downstream steps
    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a") as f:
            f.write(f"agent_version={agent.version}\n")


if __name__ == "__main__":
    main()
