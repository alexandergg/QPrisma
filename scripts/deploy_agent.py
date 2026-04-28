"""Deploy QPrisma hosted agent to Microsoft Foundry.

Registers (or updates) the hosted agent version in Foundry Agent Service and
waits for the version to reach the documented `active` state.

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
import sys
import time
from collections.abc import Mapping

from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import (
    AgentProtocol,
    HostedAgentDefinition,
    ProtocolVersionRecord,
)
from azure.core.exceptions import HttpResponseError
from azure.identity import DefaultAzureCredential

AGENT_NAME = "qprisma-video-agent"
ACCOUNT_NAME = "aif-qprisma-dev"

MAX_RETRIES = 3
RETRY_WAIT_SECONDS = [120, 240]  # 2min, 4min between retries

# Polling: check agent status every 30s for up to 10 min
POLL_INTERVAL_SECONDS = 30
POLL_TIMEOUT_SECONDS = 600

AGENT_IDENTITY_LOOKUP_ATTEMPTS = 20
AGENT_IDENTITY_LOOKUP_WAIT_SECONDS = 15


def _optional_env(key: str, *, env: Mapping[str, str] | None = None) -> dict[str, str]:
    """Return {key: value} if the env var is set, otherwise empty dict."""
    source = os.environ if env is None else env
    value = source.get(key, "")
    return {key: value} if value else {}


def _optional_env_aliased(
    target: str, *sources: str, env: Mapping[str, str] | None = None
) -> dict[str, str]:
    """Return ``{target: value}`` reading from the first source key that is set.

    Used to accept legacy env names (e.g. ``FOUNDRY_MEMORY_*``) while emitting
    under the payload-safe key (``MEMORY_*``) since ``FOUNDRY_*`` / ``AGENT_*``
    are reserved by the hosted-agent platform.
    """
    source = os.environ if env is None else env
    for key in (target, *sources):
        value = source.get(key, "")
        if value:
            return {target: value}
    return {}


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
        "AZURE_OPENAI_API_VERSION": source.get(
            "AZURE_OPENAI_API_VERSION", "2024-08-01-preview"
        ),
        "AZURE_OPENAI_DEPLOYMENT_GPT": source.get(
            "AZURE_OPENAI_DEPLOYMENT_GPT", "gpt-5.4-pro"
        ),
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
        # platform; we emit under MEMORY_* (which the backend FoundrySettings
        # accepts via AliasChoices) but also accept the legacy FOUNDRY_MEMORY_*
        # names as input so exporters using those env vars still work.
        **_optional_env_aliased(
            "MEMORY_STORE_NAME", "FOUNDRY_MEMORY_STORE_NAME", env=source
        ),
        **_optional_env_aliased(
            "MEMORY_CHAT_MODEL", "FOUNDRY_MEMORY_CHAT_MODEL", env=source
        ),
        **_optional_env_aliased(
            "MEMORY_EMBEDDING_MODEL", "FOUNDRY_MEMORY_EMBEDDING_MODEL", env=source
        ),
        # --- Response mode (eval-friendly output) ---
        **_optional_env("QPRISMA_RESPONSE_MODE", env=source),
    }


def _extract_agent_identity_principal_id(agent: object) -> str | None:
    """Extract the hosted agent instance identity principal ID from SDK models."""
    instance_identity = getattr(agent, "instance_identity", None)
    if instance_identity is None:
        return None

    if isinstance(instance_identity, Mapping):
        principal_id = instance_identity.get("principal_id")
        return principal_id if isinstance(principal_id, str) and principal_id else None

    principal_id = getattr(instance_identity, "principal_id", None)
    return principal_id if isinstance(principal_id, str) and principal_id else None


def resolve_agent_identity_principal_id(
    client: AIProjectClient,
    *,
    attempts: int = AGENT_IDENTITY_LOOKUP_ATTEMPTS,
    wait_seconds: int = AGENT_IDENTITY_LOOKUP_WAIT_SECONDS,
) -> str | None:
    """Resolve the hosted agent instance identity principal ID via Foundry APIs."""
    for attempt in range(1, attempts + 1):
        try:
            agent = client.agents.get(agent_name=AGENT_NAME)
        except HttpResponseError as exc:
            if attempt == attempts:
                print(
                    f"WARNING: Failed to fetch agent identity after {attempts} attempts: {exc}"
                )
                return None
            print(
                f"Agent identity not available yet (attempt {attempt}/{attempts}): {exc}"
            )
        else:
            principal_id = _extract_agent_identity_principal_id(agent)
            if principal_id:
                print(
                    f"Resolved hosted agent instance identity principal ID: {principal_id}"
                )
                return principal_id
            if attempt == attempts:
                print(
                    "WARNING: Hosted agent instance identity principal ID was not returned."
                )
                return None
            print(
                f"Hosted agent instance identity not ready yet (attempt {attempt}/{attempts})."
            )

        time.sleep(wait_seconds)

    return None


def _extract_agent_version_status(agent_version: object) -> str | None:
    """Extract the hosted agent version status from SDK models or dicts."""
    if isinstance(agent_version, Mapping):
        status = agent_version.get("status")
        return status if isinstance(status, str) and status else None

    status = getattr(agent_version, "status", None)
    return status if isinstance(status, str) and status else None


def _extract_agent_version_error(agent_version: object) -> str | None:
    """Extract a readable provisioning error from SDK models or dicts."""
    if isinstance(agent_version, Mapping):
        error = agent_version.get("error")
    else:
        error = getattr(agent_version, "error", None)

    if error is None:
        return None
    if isinstance(error, str):
        return error or None
    if isinstance(error, Mapping):
        code = error.get("code")
        message = error.get("message")
    else:
        code = getattr(error, "code", None)
        message = getattr(error, "message", None)

    parts = [part for part in (code, message) if isinstance(part, str) and part]
    return ": ".join(parts) if parts else str(error)


def wait_for_agent_active(client: AIProjectClient, version: str) -> str:
    """Poll the hosted agent version until it reaches a terminal state.

    Returns one of:
        ``"active"``  — version reached the SDK's active state.
        ``"failed"``  — Foundry reported a terminal provisioning failure.
        ``"timeout"`` — the poll loop exceeded ``POLL_TIMEOUT_SECONDS``.
    """
    start = time.time()
    last_status = None

    while time.time() - start < POLL_TIMEOUT_SECONDS:
        try:
            agent_version = client.agents.get_version(
                agent_name=AGENT_NAME,
                agent_version=version,
            )
        except HttpResponseError as exc:
            elapsed = int(time.time() - start)
            print(f"  [{elapsed}s] Failed to fetch version status: {exc}")
            time.sleep(POLL_INTERVAL_SECONDS)
            continue

        status = _extract_agent_version_status(agent_version)
        if status != last_status:
            elapsed = int(time.time() - start)
            print(f"  [{elapsed}s] Agent status: {status or 'unknown'}")
            last_status = status

        if status and status.lower() == "active":
            print(f"Agent is active! (status: {status})")
            return "active"
        if status and status.lower() == "failed":
            print(f"Agent deployment failed (status: {status})")
            error = _extract_agent_version_error(agent_version)
            if error:
                print(f"Provisioning error: {error}")
            return "failed"

        time.sleep(POLL_INTERVAL_SECONDS)

    elapsed = int(time.time() - start)
    print(f"Timed out after {elapsed}s waiting for agent (last status: {last_status})")
    print("The agent may still be provisioning. Check Azure AI Foundry portal.")
    return "timeout"


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
        allow_preview=True,
    )

    environment_variables = build_environment_variables()

    # Warn if critical backend service vars are missing
    _CRITICAL_VARS = ["NEO4J_URI", "NEO4J_PASSWORD", "DATABASE_URL", "REDIS_URL"]
    missing = [v for v in _CRITICAL_VARS if v not in environment_variables]
    if missing:
        print(f"WARNING: Missing critical env vars " f"for backend services: {missing}")
        print(
            "  The hosted agent will fall back to "
            "localhost defaults and fail to connect."
        )
        print(
            "  Ensure the deploy workflow resolves " "these from Azure infrastructure."
        )

    definition = HostedAgentDefinition(
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
            print(
                f"Agent registered: {agent.name} "
                f"(id: {agent.id}, version: {agent.version})"
            )
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

    # Poll until the agent reaches the current SDK's active state. The
    # instance_identity is only populated by Foundry once the version is
    # active, so we must wait for active *before* resolving the identity.
    print("Waiting for agent version to reach 'active' state...")
    wait_result = wait_for_agent_active(client, str(agent.version))
    active = wait_result == "active"

    agent_identity_principal_id: str | None = None
    if active:
        agent_identity_principal_id = resolve_agent_identity_principal_id(client)

    # Write version to GITHUB_OUTPUT for downstream steps
    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a") as f:
            f.write(f"agent_version={agent.version}\n")
            f.write(f"agent_active={'true' if active else 'false'}\n")
            f.write(
                f"agent_identity_principal_id={agent_identity_principal_id or ''}\n"
            )

    if wait_result == "failed":
        print(
            "ERROR: Hosted agent provisioning reported a terminal failure. "
            "Inspect the Foundry portal logs above for the root cause."
        )
        sys.exit(1)

    if wait_result == "timeout":
        print("WARNING: Agent may still be provisioning " "— check Foundry portal.")
        # Exit 0 to not fail the pipeline
        # — provisioning is async and may exceed our timeout
        sys.exit(0)

    if not agent_identity_principal_id:
        print(
            "ERROR: Agent version is active but instance_identity.principal_id "
            "was not returned by Foundry after "
            f"{AGENT_IDENTITY_LOOKUP_ATTEMPTS} attempts "
            f"({max(AGENT_IDENTITY_LOOKUP_ATTEMPTS - 1, 0) * AGENT_IDENTITY_LOOKUP_WAIT_SECONDS}s)."
        )
        print(
            "Re-run this workflow to retry, or inspect the agent in the "
            "Foundry portal to confirm the identity has been provisioned."
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
