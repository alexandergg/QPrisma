"""Deploy QPrisma hosted agent to Microsoft Foundry.

Registers (or updates) the hosted agent version in Foundry Agent Service,
waits for the version to reach the documented ``active`` state, and assigns
the runtime identity the RBAC roles required to call the project Responses
API and the account-scoped Azure OpenAI subdomain.

Usage:
    az login
    export AZURE_AI_PROJECT_ENDPOINT="https://<account>.services.ai.azure.com/api/projects/<project>"
    export CONTAINER_IMAGE="<acr>.azurecr.io/qprisma-video-agent:latest"
    export AZURE_SUBSCRIPTION_ID="<sub-id>"           # required for RBAC scope
    export AZURE_RESOURCE_GROUP="rg-qprisma-dev"      # optional, default shown
    python scripts/deploy_agent.py [--purge-before-deploy]

Environment toggles:
    PURGE_BEFORE_DEPLOY=1   purge the agent + all versions before re-deploy
    AGENT_IDENTITY_LOOKUP_ATTEMPTS, AGENT_IDENTITY_LOOKUP_WAIT_SECONDS:
                            override default identity polling (80 x 15s).

Reference:
    https://learn.microsoft.com/azure/ai-foundry/agents/how-to/deploy-hosted-agent
    https://learn.microsoft.com/azure/ai-foundry/agents/how-to/manage-hosted-agent
    https://learn.microsoft.com/azure/ai-foundry/agents/how-to/hosted-agent-permissions
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from collections.abc import Mapping
from urllib.parse import urlparse

from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import (
    AgentProtocol,
    HostedAgentDefinition,
    ProtocolVersionRecord,
)
from azure.core.exceptions import HttpResponseError
from azure.identity import DefaultAzureCredential

AGENT_NAME = "qprisma-video-agent"
DEFAULT_ACCOUNT_NAME = "aif-qprisma-dev"
DEFAULT_RESOURCE_GROUP = "rg-qprisma-dev"

MAX_RETRIES = 3
RETRY_WAIT_SECONDS = [120, 240]  # 2min, 4min between retries

# Polling: check agent status every 30s for up to 10 min
POLL_INTERVAL_SECONDS = 30
POLL_TIMEOUT_SECONDS = 600

# Identity polling: refreshed-preview Foundry can take longer than the
# legacy 10-min window to materialise instance_identity.principal_id.
# 80 x 15s ≈ 20 min upper bound; override via env vars when needed.
AGENT_IDENTITY_LOOKUP_ATTEMPTS = int(
    os.environ.get("AGENT_IDENTITY_LOOKUP_ATTEMPTS", "80")
)
AGENT_IDENTITY_LOOKUP_WAIT_SECONDS = int(
    os.environ.get("AGENT_IDENTITY_LOOKUP_WAIT_SECONDS", "15")
)

# Built-in RBAC role definition IDs (verified from Azure docs).
# Cognitive Services OpenAI User — covers account-scoped *.openai.azure.com.
ROLE_OPENAI_USER = "5e0bd9bd-7b93-4f28-af87-19fc36ad61bd"
# Azure AI User — covers project-scoped Responses API path used by hosted agent.
ROLE_AZURE_AI_USER_NAME = "Azure AI User"
RBAC_PROPAGATION_WAIT_SECONDS = 120

DEFAULT_ENV_VARS = {
    "ENVIRONMENT": "hosted",
    "LOG_LEVEL": "INFO",
    "AZURE_OPENAI_API_VERSION": "2025-04-01-preview",
    "AZURE_OPENAI_DEPLOYMENT_GPT": "gpt-5.5",
    "AZURE_OPENAI_DEPLOYMENT_EMBEDDING": "text-embedding-3-large",
    "AZURE_USE_MANAGED_IDENTITY": "true",
    "AZURE_EXPERIMENTAL_ENABLE_GENAI_TRACING": "true",
}

OPTIONAL_ENV_VARS = (
    "AZURE_AI_PROJECT_ENDPOINT",
    "AZURE_TRACING_GEN_AI_CONTENT_RECORDING_ENABLED",
    "OTEL_SERVICE_NAME",
    "NEO4J_URI",
    "NEO4J_USER",
    "NEO4J_PASSWORD",
    "NEO4J_DATABASE",
    "DATABASE_URL",
    "REDIS_URL",
    "AZURE_STORAGE_CONNECTION_STRING",
    "MEMORY_STORE_NAME",
    "MEMORY_CHAT_MODEL",
    "MEMORY_EMBEDDING_MODEL",
)

LEGACY_SECRET_REFERENCE_ENV_KEYS = (
    "NEO4J_PASSWORD_KEY_VAULT_URI",
    "NEO4J_PASSWORD_KV_URI",
    "DATABASE_URL_KEY_VAULT_URI",
    "DATABASE_URL_KV_URI",
    "REDIS_URL_KEY_VAULT_URI",
    "REDIS_URL_KV_URI",
    "AZURE_STORAGE_ACCOUNT_URL",
    "AZURE_STORAGE_CONNECTION_STRING_KEY_VAULT_URI",
    "STORAGE_CONNECTION_KV_URI",
)

CRITICAL_ENV_VARS = (
    "AZURE_OPENAI_DEPLOYMENT_GPT",
    "NEO4J_URI",
    "NEO4J_PASSWORD",
    "DATABASE_URL",
    "REDIS_URL",
    "AZURE_STORAGE_CONNECTION_STRING",
)

HOSTED_AGENT_ENV_CONTRACT = frozenset(
    {
        "AZURE_OPENAI_ENDPOINT",
        *DEFAULT_ENV_VARS,
        *OPTIONAL_ENV_VARS,
    }
)


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


def _reject_legacy_secret_reference_keys(source: Mapping[str, str]) -> None:
    """Fail fast when the old Key Vault URI contract is present."""
    legacy_keys = [key for key in LEGACY_SECRET_REFERENCE_ENV_KEYS if source.get(key)]
    if not legacy_keys:
        return

    formatted = ", ".join(sorted(legacy_keys))
    raise ValueError(
        "Hosted Agent deployment no longer accepts Key Vault URI/managed-identity "
        "secret references in the agent environment. Resolve these values before "
        f"registration and pass the plain runtime env vars instead. Offending keys: {formatted}"
    )


def build_environment_variables(
    *,
    account_name: str = DEFAULT_ACCOUNT_NAME,
    env: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Build the hosted agent container environment contract."""
    source = os.environ if env is None else env
    _reject_legacy_secret_reference_keys(source)

    environment_variables = {
        **{key: source.get(key, default) for key, default in DEFAULT_ENV_VARS.items()},
        "AZURE_OPENAI_ENDPOINT": source.get(
            "AZURE_OPENAI_ENDPOINT",
            f"https://{account_name}.openai.azure.com/",
        ),
    }

    for key in OPTIONAL_ENV_VARS:
        environment_variables.update(_optional_env(key, env=source))

    # FOUNDRY_* and AGENT_* prefixes are reserved by the hosted-agent platform.
    # Accept legacy input aliases but emit the backend-safe MEMORY_* names.
    environment_variables.update(
        _optional_env_aliased("MEMORY_STORE_NAME", "FOUNDRY_MEMORY_STORE_NAME", env=source)
    )
    environment_variables.update(
        _optional_env_aliased("MEMORY_CHAT_MODEL", "FOUNDRY_MEMORY_CHAT_MODEL", env=source)
    )
    environment_variables.update(
        _optional_env_aliased(
            "MEMORY_EMBEDDING_MODEL",
            "FOUNDRY_MEMORY_EMBEDDING_MODEL",
            env=source,
        )
    )

    return environment_variables


def parse_account_and_project(project_endpoint: str) -> tuple[str, str]:
    """Parse the Foundry project endpoint into (account_name, project_name).

    Endpoints must look like
    ``https://<account>.services.ai.azure.com/api/projects/<project>``.
    Returns ``(account_name, project_name)`` and raises ``ValueError`` if the
    endpoint does not match the expected shape.
    """
    expected_shape = "https://<account>.services.ai.azure.com/api/projects/<project>"
    parsed = urlparse(project_endpoint.strip())
    host = parsed.netloc or ""
    if not host:
        raise ValueError(
            "Invalid AZURE_AI_PROJECT_ENDPOINT: missing host. "
            f"Expected format: {expected_shape}"
        )

    account = host.split(".", 1)[0]
    if not account:
        raise ValueError(
            "Invalid AZURE_AI_PROJECT_ENDPOINT: could not determine account name from host. "
            f"Expected format: {expected_shape}"
        )

    parts = [segment for segment in parsed.path.split("/") if segment]
    if "projects" not in parts:
        raise ValueError(
            "Invalid AZURE_AI_PROJECT_ENDPOINT: missing '/api/projects/<project>' path. "
            f"Expected format: {expected_shape}"
        )

    idx = parts.index("projects")
    if idx + 1 >= len(parts) or not parts[idx + 1]:
        raise ValueError(
            "Invalid AZURE_AI_PROJECT_ENDPOINT: missing project name after '/api/projects/'. "
            f"Expected format: {expected_shape}"
        )

    project = parts[idx + 1]
    return account, project


def _run_az(args: list[str], *, capture: bool = True) -> subprocess.CompletedProcess:
    """Invoke ``az`` and return the completed process. Raises if ``az`` is missing."""
    az_path = shutil.which("az")
    if not az_path:
        raise RuntimeError("'az' CLI not found on PATH; cannot perform RBAC operations.")
    return subprocess.run(  # noqa: S603 - az path is resolved with shutil.which and args are a list.
        [az_path, *args],
        capture_output=capture,
        text=True,
        timeout=120,
        check=False,
    )


def _assign_role_idempotent(
    *,
    principal_id: str,
    role: str,
    scope: str,
    label: str,
) -> bool:
    """Assign ``role`` (name or definition GUID) to ``principal_id`` at ``scope``.

    Returns ``True`` when a NEW assignment was created, ``False`` when it was
    already present. Raises ``RuntimeError`` on any other failure so the caller
    can decide whether to fail the deployment.
    """
    proc = _run_az(
        [
            "role",
            "assignment",
            "create",
            "--assignee-object-id",
            principal_id,
            "--assignee-principal-type",
            "ServicePrincipal",
            "--role",
            role,
            "--scope",
            scope,
            "--output",
            "json",
        ]
    )

    combined = ((proc.stdout or "") + (proc.stderr or "")).strip()
    if proc.returncode == 0:
        print(f"  {label}: newly assigned")
        return True
    if "already exists" in combined or "RoleAssignmentExists" in combined:
        print(f"  {label}: already assigned")
        return False
    raise RuntimeError(
        f"Failed to assign {label} to principal {principal_id[:8]}…: "
        f"exit={proc.returncode} {combined[:500]}"
    )


def assign_agent_identity_rbac(
    *,
    principal_id: str,
    subscription_id: str,
    resource_group: str,
    account_name: str,
    project_name: str,
) -> None:
    """Grant the hosted agent runtime identity the RBAC roles it needs.

    Per the Foundry hosted-agent-permissions docs the runtime principal needs:

    1. ``Azure AI User`` at PROJECT scope — covers the project-routed
       Responses API path (``Microsoft.CognitiveServices/accounts/AIServices/responses/*``).
    2. ``Cognitive Services OpenAI User`` at ACCOUNT scope (defensive) — covers
       any code path still hitting the account-level ``*.openai.azure.com``
       subdomain.

    Both are idempotent: existing assignments are reported and skipped.
    """
    print(f"\nAssigning RBAC to agent identity {principal_id[:8]}…")
    account_scope = (
        f"/subscriptions/{subscription_id}/resourceGroups/{resource_group}"
        f"/providers/Microsoft.CognitiveServices/accounts/{account_name}"
    )
    project_scope = f"{account_scope}/projects/{project_name}"

    new_assignments = False

    new_assignments |= _assign_role_idempotent(
        principal_id=principal_id,
        role=ROLE_AZURE_AI_USER_NAME,
        scope=project_scope,
        label="Azure AI User (project)",
    )
    new_assignments |= _assign_role_idempotent(
        principal_id=principal_id,
        role=ROLE_OPENAI_USER,
        scope=account_scope,
        label="Cognitive Services OpenAI User (account)",
    )

    if new_assignments:
        print(
            f"New role assignment(s) created; waiting "
            f"{RBAC_PROPAGATION_WAIT_SECONDS}s for RBAC propagation..."
        )
        time.sleep(RBAC_PROPAGATION_WAIT_SECONDS)
    else:
        print("All required role assignments already in place.")


def maybe_purge_before_deploy(
    *, project_endpoint: str, agent_name: str, force: bool
) -> None:
    """Optionally purge the agent + all versions before deploying a new one.

    Triggered by ``--purge-before-deploy`` or ``PURGE_BEFORE_DEPLOY=1``. Uses
    ``scripts/purge_agent_versions.py`` so the purge logic stays in one place.
    """
    if not force and os.environ.get("PURGE_BEFORE_DEPLOY", "").lower() not in {
        "1",
        "true",
        "yes",
    }:
        return

    print(f"\nPURGE_BEFORE_DEPLOY enabled — purging '{agent_name}' first...")
    purge_script = os.path.join(os.path.dirname(__file__), "purge_agent_versions.py")
    proc = subprocess.run(  # noqa: S603 - script path and interpreter are controlled by this repo.
        [sys.executable, purge_script, "--agent-name", agent_name],
        env={**os.environ, "AZURE_AI_PROJECT_ENDPOINT": project_endpoint},
        check=False,
    )
    if proc.returncode != 0:
        print(
            f"WARNING: Purge step exited with code {proc.returncode}. "
            "Continuing with deployment — duplicate-name errors are still possible."
        )


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


def _resolve_principal_id_via_rest(project_endpoint: str) -> str | None:
    """Fallback: query the Foundry data-plane REST API for the agent identity.

    The SDK occasionally fails to surface ``instance_identity.principal_id``
    even after the agent reports ``active``. The data-plane endpoint exposes
    the same field reliably once provisioning completes, so we shell out to
    ``az rest`` (which already has the OIDC token from ``azure/login``).

    Returns the principal ID string if found, ``None`` otherwise.
    """
    az_path = shutil.which("az")
    if not az_path:
        print("REST fallback skipped: 'az' CLI not found on PATH.")
        return None

    base = project_endpoint.rstrip("/")
    url = f"{base}/agents/{AGENT_NAME}?api-version=v1"

    try:
        proc = subprocess.run(  # noqa: S603 - az path is resolved with shutil.which and args are a list.
            [
                az_path,
                "rest",
                "--method",
                "GET",
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
        return None

    if proc.returncode != 0:
        print(
            f"REST fallback returned non-zero exit ({proc.returncode}): "
            f"{(proc.stderr or proc.stdout or '').strip()[:500]}"
        )
        return None

    try:
        payload = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError as exc:
        print(f"REST fallback could not parse response JSON: {exc}")
        return None

    instance_identity = payload.get("instance_identity") or {}
    principal_id = instance_identity.get("principal_id")
    if isinstance(principal_id, str) and principal_id:
        return principal_id

    print(
        "REST fallback succeeded but instance_identity.principal_id "
        "is still empty in the response payload."
    )
    return None


def resolve_agent_identity_principal_id(
    client: AIProjectClient,
    *,
    attempts: int = AGENT_IDENTITY_LOOKUP_ATTEMPTS,
    wait_seconds: int = AGENT_IDENTITY_LOOKUP_WAIT_SECONDS,
) -> tuple[str | None, str]:
    """Resolve the hosted agent instance identity principal ID via Foundry APIs.

    Returns a ``(principal_id, source)`` tuple. ``source`` is ``"sdk"`` when the
    Python SDK returned the value, ``"rest"`` when the data-plane REST fallback
    succeeded, or ``"none"`` when neither path produced a value.
    """
    for attempt in range(1, attempts + 1):
        try:
            agent = client.agents.get(agent_name=AGENT_NAME)
        except HttpResponseError as exc:
            if attempt == attempts:
                print(
                    f"WARNING: Failed to fetch agent identity after {attempts} attempts: {exc}"
                )
                break
            print(
                f"Agent identity not available yet (attempt {attempt}/{attempts}): {exc}"
            )
        else:
            principal_id = _extract_agent_identity_principal_id(agent)
            if principal_id:
                print(
                    f"Resolved hosted agent instance identity principal ID via SDK: {principal_id}"
                )
                return principal_id, "sdk"
            if attempt == attempts:
                print(
                    "WARNING: Hosted agent instance identity principal ID was not returned by SDK."
                )
                break
            print(
                f"Hosted agent instance identity not ready yet (attempt {attempt}/{attempts})."
            )

        time.sleep(wait_seconds)

    project_endpoint = os.environ.get("AZURE_AI_PROJECT_ENDPOINT", "").strip()
    if not project_endpoint:
        print("REST fallback skipped: AZURE_AI_PROJECT_ENDPOINT is not set.")
        return None, "none"

    print("Falling back to data-plane REST endpoint for instance_identity...")
    principal_id = _resolve_principal_id_via_rest(project_endpoint)
    if principal_id:
        print(
            f"Resolved hosted agent instance identity principal ID via REST: {principal_id}"
        )
        return principal_id, "rest"

    return None, "none"


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


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--purge-before-deploy",
        action="store_true",
        help=(
            "Purge the existing agent + all versions before deploying. "
            "Equivalent to setting PURGE_BEFORE_DEPLOY=1."
        ),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)

    # Silence the azure.ai.projects GenAI tracing warning during this script's
    # execution (the SDK checks this env var at instantiation time).
    os.environ.setdefault("AZURE_EXPERIMENTAL_ENABLE_GENAI_TRACING", "true")

    project_endpoint = os.environ.get("AZURE_AI_PROJECT_ENDPOINT", "").strip()
    container_image = os.environ.get("CONTAINER_IMAGE", "").strip()
    subscription_id = os.environ.get("AZURE_SUBSCRIPTION_ID", "").strip()
    resource_group = os.environ.get(
        "AZURE_RESOURCE_GROUP", DEFAULT_RESOURCE_GROUP
    ).strip()

    if not project_endpoint or not container_image:
        print("ERROR: AZURE_AI_PROJECT_ENDPOINT and CONTAINER_IMAGE are required")
        sys.exit(1)

    account_name, project_name = parse_account_and_project(project_endpoint)

    print(f"Deploying agent '{AGENT_NAME}'")
    print(f"  Project endpoint: {project_endpoint}")
    print(f"  Account / project: {account_name} / {project_name}")
    print(f"  Resource group:    {resource_group}")
    print(f"  Image:             {container_image}")

    maybe_purge_before_deploy(
        project_endpoint=project_endpoint,
        agent_name=AGENT_NAME,
        force=args.purge_before_deploy,
    )

    client = AIProjectClient(
        endpoint=project_endpoint,
        credential=DefaultAzureCredential(),
        allow_preview=True,
    )

    try:
        environment_variables = build_environment_variables(account_name=account_name)
    except ValueError as exc:
        print(f"ERROR: {exc}")
        sys.exit(1)

    # Fail before registering a hosted version that cannot boot or route model calls.
    missing = [v for v in CRITICAL_ENV_VARS if v not in environment_variables]
    if missing:
        print("ERROR: One or more critical hosted-agent env vars are missing.")
        print(
            "  The hosted agent would otherwise fall back to local/model defaults "
            "and fail at runtime."
        )
        print(
            "  Ensure the deploy workflow resolves these from Azure infrastructure "
            "or explicit workflow inputs."
        )
        print(f"  Missing: {', '.join(missing)}")
        sys.exit(1)

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
    github_output = os.environ.get("GITHUB_OUTPUT")

    agent_identity_principal_id: str | None = None
    identity_source = "none"
    if active:
        agent_identity_principal_id, identity_source = (
            resolve_agent_identity_principal_id(client)
        )

    # Write version to GITHUB_OUTPUT for downstream steps
    if github_output:
        with open(github_output, "a") as f:
            f.write(f"agent_version={agent.version}\n")
            f.write(f"agent_active={'true' if active else 'false'}\n")
            f.write(
                f"agent_identity_principal_id={agent_identity_principal_id or ''}\n"
            )
            f.write(f"agent_identity_source={identity_source}\n")

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
            "WARNING: Agent version is active but instance_identity.principal_id "
            "was not returned by Foundry after "
            f"{AGENT_IDENTITY_LOOKUP_ATTEMPTS} attempts "
            f"({max(AGENT_IDENTITY_LOOKUP_ATTEMPTS - 1, 0) * AGENT_IDENTITY_LOOKUP_WAIT_SECONDS}s)."
        )
        print(
            "Skipping runtime identity RBAC assignment for this run. Re-run the workflow "
            "to retry the lookup, or inspect the agent in the Foundry portal to confirm "
            "the identity has been provisioned."
        )

    # The agent runtime identity is now known; assign the RBAC roles it needs
    # to invoke the project Responses API and the account-scoped Azure OpenAI
    # subdomain. Skipped (with a warning) if subscription_id is missing — that
    # only happens in local invocations, where the operator can run the role
    # assignments by hand.
    if subscription_id and agent_identity_principal_id:
        try:
            assign_agent_identity_rbac(
                principal_id=agent_identity_principal_id,
                subscription_id=subscription_id,
                resource_group=resource_group,
                account_name=account_name,
                project_name=project_name,
            )
        except RuntimeError as exc:
            print(f"ERROR: {exc}")
            sys.exit(1)
    elif not agent_identity_principal_id:
        print(
            "WARNING: Hosted agent runtime identity principal ID is unavailable — "
            "skipping automatic RBAC assignment."
        )
    else:
        print(
            "WARNING: AZURE_SUBSCRIPTION_ID not set — skipping agent identity "
            "RBAC assignment. Grant 'Azure AI User' (project scope) and "
            "'Cognitive Services OpenAI User' (account scope) manually before "
            "the agent can serve traffic."
        )


if __name__ == "__main__":
    main()
