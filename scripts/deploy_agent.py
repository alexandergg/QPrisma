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

import json
import os
import subprocess
import sys
import time
from collections.abc import Mapping

from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import (
    AgentProtocol,
    ImageBasedHostedAgentDefinition,
    ProtocolVersionRecord,
)
from azure.core.exceptions import HttpResponseError
from azure.identity import DefaultAzureCredential

AGENT_NAME = "qprisma-video-agent"
ACCOUNT_NAME = "aif-qprisma-dev"
PROJECT_NAME = "aif-qprisma-dev-project"

MAX_RETRIES = 3
RETRY_WAIT_SECONDS = [120, 240]  # 2min, 4min between retries

# Polling: check agent status every 30s for up to 10 min
POLL_INTERVAL_SECONDS = 30
POLL_TIMEOUT_SECONDS = 600


def _optional_env(key: str, *, env: Mapping[str, str] | None = None) -> dict[str, str]:
    """Return {key: value} if the env var is set, otherwise empty dict."""
    source = os.environ if env is None else env
    value = source.get(key, "")
    return {key: value} if value else {}


def build_environment_variables(
    *, account_name: str = ACCOUNT_NAME, env: Mapping[str, str] | None = None
) -> dict[str, str]:
    """Build the hosted agent container environment contract."""
    source = os.environ if env is None else env

    return {
        # --- Core ---
        "ENVIRONMENT": source.get("ENVIRONMENT", "hosted"),
        "LOG_LEVEL": source.get("LOG_LEVEL", "INFO"),
        # --- Azure OpenAI ---
        "AZURE_OPENAI_ENDPOINT": source.get(
            "AZURE_OPENAI_ENDPOINT",
            f"https://{account_name}.openai.azure.com/",
        ),
        "AZURE_OPENAI_API_VERSION": source.get("AZURE_OPENAI_API_VERSION", "2024-08-01-preview"),
        "AZURE_OPENAI_DEPLOYMENT_GPT": source.get("AZURE_OPENAI_DEPLOYMENT_GPT", "gpt-4o"),
        "AZURE_OPENAI_DEPLOYMENT_EMBEDDING": source.get(
            "AZURE_OPENAI_DEPLOYMENT_EMBEDDING",
            "text-embedding-3-large",
        ),
        "AZURE_USE_MANAGED_IDENTITY": source.get("AZURE_USE_MANAGED_IDENTITY", "true"),
        "AZURE_EXPERIMENTAL_ENABLE_GENAI_TRACING": "true",
        # --- Telemetry ---
        # NOTE: APPLICATIONINSIGHTS_CONNECTION_STRING is reserved by the Foundry
        # hosted-agent platform and auto-injected; do not set it here.
        **_optional_env("AZURE_TRACING_GEN_AI_CONTENT_RECORDING_ENABLED", env=source),
        **_optional_env("OTEL_SERVICE_NAME", env=source),
        # --- Neo4j Knowledge Graph ---
        **_optional_env("NEO4J_URI", env=source),
        **_optional_env("NEO4J_USER", env=source),
        **_optional_env("NEO4J_PASSWORD", env=source),
        **_optional_env("NEO4J_DATABASE", env=source),
        # --- PostgreSQL ---
        **_optional_env("DATABASE_URL", env=source),
        # --- Redis ---
        **_optional_env("REDIS_URL", env=source),
        # --- Azure Blob Storage ---
        **_optional_env("AZURE_STORAGE_CONNECTION_STRING", env=source),
        # --- Foundry Memory Store ---
        # NOTE: FOUNDRY_* and AGENT_* prefixes are reserved by the hosted-agent
        # platform; we use the MEMORY_* names which the backend FoundrySettings
        # accepts via AliasChoices.
        **_optional_env("MEMORY_STORE_NAME", env=source),
        **_optional_env("MEMORY_CHAT_MODEL", env=source),
        **_optional_env("MEMORY_EMBEDDING_MODEL", env=source),
        # --- Response mode (eval-friendly output) ---
        **_optional_env("QPRISMA_RESPONSE_MODE", env=source),
    }


def _run_az(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        ["az", *args],  # noqa: S607
        capture_output=True,
        text=True,
    )


def start_agent(version: str) -> bool:
    """Start the agent deployment using az cli."""
    cmd = [
        "cognitiveservices",
        "agent",
        "start",
        "--account-name",
        ACCOUNT_NAME,
        "--project-name",
        PROJECT_NAME,
        "--name",
        AGENT_NAME,
        "--agent-version",
        str(version),
    ]
    print(f"Starting agent with: az {' '.join(cmd)}")
    result = _run_az(*cmd)
    if result.returncode == 0:
        print("Agent start command succeeded")
        return True

    print(f"az cognitiveservices agent start failed (rc={result.returncode})")
    if result.stderr:
        print(f"  stderr: {result.stderr.strip()}")
    return False


def get_agent_status() -> str | None:
    """Get the current agent deployment status via az cli."""
    result = _run_az(
        "cognitiveservices",
        "agent",
        "show",
        "--account-name",
        ACCOUNT_NAME,
        "--project-name",
        PROJECT_NAME,
        "--name",
        AGENT_NAME,
        "--output",
        "json",
    )
    if result.returncode != 0:
        return None
    try:
        data = json.loads(result.stdout)
        return data.get("properties", {}).get("provisioningState") or data.get("status")
    except (json.JSONDecodeError, KeyError):
        return None


def wait_for_agent_running() -> bool:
    """Poll agent status until it reaches a terminal state or times out."""
    start = time.time()
    last_status = None

    while time.time() - start < POLL_TIMEOUT_SECONDS:
        status = get_agent_status()
        if status != last_status:
            elapsed = int(time.time() - start)
            print(f"  [{elapsed}s] Agent status: {status or 'unknown'}")
            last_status = status

        if status and status.lower() in ("running", "succeeded", "started"):
            print(f"Agent is running! (status: {status})")
            return True
        if status and status.lower() in ("failed", "error"):
            print(f"Agent deployment failed (status: {status})")
            return False

        time.sleep(POLL_INTERVAL_SECONDS)

    elapsed = int(time.time() - start)
    print(f"Timed out after {elapsed}s waiting for agent (last status: {last_status})")
    print("The agent may still be provisioning. Check Azure AI Foundry portal.")
    return False


def main() -> None:
    # Silence the azure.ai.projects GenAI tracing warning during this script's
    # execution (the SDK checks this env var at instantiation time).
    os.environ.setdefault("AZURE_EXPERIMENTAL_ENABLE_GENAI_TRACING", "true")

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

    environment_variables = build_environment_variables()

    # Warn if critical backend service vars are missing
    _CRITICAL_VARS = ["NEO4J_URI", "NEO4J_PASSWORD", "DATABASE_URL", "REDIS_URL"]
    missing = [v for v in _CRITICAL_VARS if v not in environment_variables]
    if missing:
        print(f"WARNING: Missing critical env vars " f"for backend services: {missing}")
        print("  The hosted agent will fall back to " "localhost defaults and fail to connect.")
        print("  Ensure the deploy workflow resolves " "these from Azure infrastructure.")

    definition = ImageBasedHostedAgentDefinition(
        container_protocol_versions=[
            ProtocolVersionRecord(protocol=AgentProtocol.RESPONSES, version="1.0.0"),
            ProtocolVersionRecord(protocol="a2a", version="v0.2.1"),
        ],
        # Foundry hosted-agent valid sandbox tiers:
        # (0.25, 0.5Gi), (0.5, 1Gi), (1, 2Gi), (2, 4Gi). 2 / 4Gi is the max.
        cpu="2",
        memory="4Gi",
        image=container_image,
        environment_variables=environment_variables,
    )

    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            print(f"\nAttempt {attempt}/{MAX_RETRIES}: creating agent version...")
            agent = client.agents.create_version(
                agent_name=AGENT_NAME,
                description=(
                    "QPrisma Video Agent — intelligent video "
                    "analysis powered by LangGraph. "
                    "Searches visual content, audio "
                    "transcriptions, and knowledge graphs "
                    "to answer questions with "
                    "timestamped citations."
                ),
                definition=definition,
            )
            print(f"Agent registered: {agent.name} " f"(id: {agent.id}, version: {agent.version})")
            break
        except HttpResponseError as e:
            last_error = e
            error_msg = str(e).lower()
            is_retryable = any(
                keyword in error_msg
                for keyword in ["timed out", "timeout", "provisioning", "503", "429"]
            )
            if is_retryable and attempt < MAX_RETRIES:
                wait = RETRY_WAIT_SECONDS[attempt - 1]
                print(f"Retryable error: {e}")
                print(f"Waiting {wait}s before retry...")
                time.sleep(wait)
            else:
                raise
    else:
        print(f"ERROR: All {MAX_RETRIES} attempts failed.")
        raise last_error  # type: ignore[misc]

    # Auto-start the agent deployment
    started = start_agent(agent.version)
    if not started:
        print(
            "WARNING: Agent registered but auto-start failed. " "Start manually in Foundry portal."
        )
        sys.exit(1)

    # Poll until the agent reaches Running state
    print("Waiting for agent to reach 'Running' state...")
    running = wait_for_agent_running()

    # Write version to GITHUB_OUTPUT for downstream steps
    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a") as f:
            f.write(f"agent_version={agent.version}\n")
            f.write(f"agent_running={'true' if running else 'false'}\n")

    if not running:
        print("WARNING: Agent may still be provisioning " "— check Foundry portal.")
        # Exit 0 to not fail the pipeline
        # — provisioning is async and may exceed our timeout
        sys.exit(0)


if __name__ == "__main__":
    main()
