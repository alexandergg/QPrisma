"""Deploy QPrisma hosted agent to Microsoft Foundry.

Registers (or updates) the hosted agent version in Foundry Agent Service.
The container image must already be built and pushed to ACR before running this.

Usage:
    az login
    export AZURE_AI_PROJECT_ENDPOINT="https://<account>.services.ai.azure.com/api/projects/<project>"
    export CONTAINER_IMAGE="<acr>.azurecr.io/qprisma-video-agent:latest"
    python scripts/deploy_agent.py

Reference: https://github.com/leyredelacalzada/hr-hosted-agent/blob/main/deploy.py
"""

import os
import sys

from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import (
    AgentProtocol,
    ImageBasedHostedAgentDefinition,
    ProtocolVersionRecord,
)
from azure.identity import DefaultAzureCredential

AGENT_NAME = "qprisma-video-agent"


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
            cpu="2",
            memory="4Gi",
            image=container_image,
            environment_variables={
                "ENVIRONMENT": os.environ.get("ENVIRONMENT", "production"),
                "LOG_LEVEL": "INFO",
            },
        ),
    )

    print(f"Agent registered: {agent.name} (id: {agent.id}, version: {agent.version})")


if __name__ == "__main__":
    main()
