"""Provision a Neo4j AuraDB Free instance via the Aura API v1.

Automates the full lifecycle: authenticate, check for existing instances,
create if needed, resume if paused, and poll until running. Outputs the
connection details to $GITHUB_OUTPUT for downstream CI/CD steps.

Usage:
    export AURA_CLIENT_ID="..."
    export AURA_CLIENT_SECRET="..."
    export AURA_TENANT_ID="..."
    export ENVIRONMENT="dev"          # optional, defaults to "dev"
    python scripts/deploy_neo4j_aura.py

Environment variables:
    AURA_CLIENT_ID      OAuth2 client ID for the Neo4j Aura API
    AURA_CLIENT_SECRET  OAuth2 client secret for the Neo4j Aura API
    AURA_TENANT_ID      Tenant ID for instance ownership
    ENVIRONMENT         Target environment suffix (default: "dev")
    GITHUB_OUTPUT       Path to GitHub Actions output file (set by Actions)

Reference:
    https://neo4j.com/docs/aura/platform/api/specification/
"""

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from http.client import HTTPResponse
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

AURA_AUTH_URL = "https://api.neo4j.io/oauth/token"
AURA_API_BASE = "https://api.neo4j.io/v1"

INSTANCE_NAME_TEMPLATE = "qprisma-graph-{environment}"

POLL_INTERVAL_SECONDS = 30
POLL_TIMEOUT_SECONDS = 600  # 10 minutes

MAX_RETRIES = 5
RETRY_BACKOFF_SECONDS = [2, 4, 8, 16, 32]

RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _required_env(name: str) -> str:
    """Return the value of an env var or exit with a clear error."""
    value = os.environ.get(name, "").strip()
    if not value:
        print(f"ERROR: Required environment variable '{name}' is not set or empty.")
        sys.exit(1)
    return value


def _api_request(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    data: bytes | None = None,
) -> tuple[int, dict[str, Any]]:
    """Make an HTTP request with automatic retry on 5xx / 429.

    Returns ``(status_code, parsed_json_body)``.  On non-retryable failures
    the function raises or returns the error status for the caller to handle.
    """
    # Validate URL against known-safe API endpoints to prevent SSRF
    _ALLOWED_PREFIXES = (AURA_AUTH_URL, AURA_API_BASE)
    if not any(url == prefix or url.startswith(prefix + "/") for prefix in _ALLOWED_PREFIXES):
        raise ValueError(f"URL not in allowed API endpoints: {url}")

    headers = headers or {}
    last_exc: Exception | None = None

    for attempt in range(1, MAX_RETRIES + 1):
        req = urllib.request.Request(  # noqa: S310
            url, data=data, headers=headers, method=method
        )
        try:
            resp: HTTPResponse = urllib.request.urlopen(req)  # noqa: S310
            body = resp.read().decode("utf-8")
            parsed = json.loads(body) if body else {}
            return resp.status, parsed
        except urllib.error.HTTPError as exc:
            status = exc.code
            body_text = exc.read().decode("utf-8", errors="replace")
            last_exc = exc

            if status in RETRYABLE_STATUS_CODES and attempt < MAX_RETRIES:
                wait = RETRY_BACKOFF_SECONDS[attempt - 1]
                print(
                    f"  Retryable HTTP {status} "
                    f"(attempt {attempt}/{MAX_RETRIES}). Waiting {wait}s..."
                )
                time.sleep(wait)
                continue

            # Non-retryable or final attempt — return status + body for caller
            try:
                parsed = json.loads(body_text)
            except json.JSONDecodeError:
                parsed = {"error": body_text}
            return status, parsed
        except urllib.error.URLError as exc:
            last_exc = exc
            if attempt < MAX_RETRIES:
                wait = RETRY_BACKOFF_SECONDS[attempt - 1]
                print(
                    f"  Network error: {exc.reason} "
                    f"(attempt {attempt}/{MAX_RETRIES}). Waiting {wait}s..."
                )
                time.sleep(wait)
                continue
            raise

    # Should never reach here, but satisfy the type checker.
    if last_exc is not None:
        raise last_exc
    raise RuntimeError(f"All {MAX_RETRIES} attempts failed for {method} request")


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


def authenticate(client_id: str, client_secret: str) -> str:
    """Obtain an OAuth2 bearer token via client-credentials flow.

    Returns the access token string.
    """
    print("Authenticating with Neo4j Aura API...")

    payload = urllib.parse.urlencode(
        {
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
        }
    ).encode("utf-8")

    headers = {"Content-Type": "application/x-www-form-urlencoded"}

    status, body = _api_request(
        AURA_AUTH_URL,
        method="POST",
        headers=headers,
        data=payload,
    )

    if status != 200:
        print(f"ERROR: Authentication failed (HTTP {status})")
        sys.exit(1)

    token: str = body.get("access_token", "")
    if not token:
        print("ERROR: No access_token in authentication response.")
        sys.exit(1)

    print("  Authentication successful.")
    return token


# ---------------------------------------------------------------------------
# Instance management
# ---------------------------------------------------------------------------


def _auth_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def list_instances(token: str) -> list[dict[str, Any]]:
    """Return all AuraDB instances visible to the authenticated principal."""
    status, body = _api_request(
        f"{AURA_API_BASE}/instances",
        headers=_auth_headers(token),
    )
    if status != 200:
        print(f"ERROR: Failed to list instances (HTTP {status})")
        sys.exit(1)
    return body.get("data", [])


def get_instance(token: str, instance_id: str) -> dict[str, Any]:
    """Fetch full details for a single instance by ID."""
    status, body = _api_request(
        f"{AURA_API_BASE}/instances/{instance_id}",
        headers=_auth_headers(token),
    )
    if status != 200:
        print(f"ERROR: Failed to get instance {instance_id} (HTTP {status})")
        sys.exit(1)
    return body.get("data", body)


def find_instance_by_name(instances: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    """Return the first instance matching *name*, or ``None``."""
    for inst in instances:
        if inst.get("name") == name:
            return inst
    return None


def create_instance(
    token: str,
    *,
    name: str,
    tenant_id: str,
) -> tuple[dict[str, Any], str]:
    """Create a new AuraDB Free instance.

    Returns ``(instance_data, initial_password)``.  The password is **only**
    available in the creation response.
    """
    payload = json.dumps(
        {
            "version": "5",
            "region": "westeurope",
            "memory": "1GB",
            "name": name,
            "type": "free-db",
            "tenant_id": tenant_id,
            "cloud_provider": "azure",
        }
    ).encode("utf-8")

    print(f"Creating AuraDB Free instance '{name}'...")
    status, body = _api_request(
        f"{AURA_API_BASE}/instances",
        method="POST",
        headers=_auth_headers(token),
        data=payload,
    )

    if status not in (200, 201, 202):
        print(f"ERROR: Failed to create instance (HTTP {status})")
        sys.exit(1)

    data: dict[str, Any] = body.get("data", body)
    # Pop password immediately to break taint propagation to other fields
    password: str = data.pop("password", "")

    instance_id = data.get("id", "unknown")
    print(f"  Instance created: id={instance_id}")
    print(f"  Initial password captured: {'yes' if password else 'no'}")

    return data, password


def resume_instance(token: str, instance_id: str) -> None:
    """Send a resume request for a paused instance."""
    print(f"Resuming paused instance {instance_id}...")
    status, body = _api_request(
        f"{AURA_API_BASE}/instances/{instance_id}/resume",
        method="POST",
        headers=_auth_headers(token),
    )
    if status not in (200, 202):
        print(f"ERROR: Failed to resume instance (HTTP {status})")
        sys.exit(1)
    print("  Resume request accepted.")


def poll_until_running(token: str, instance_id: str) -> dict[str, Any]:
    """Poll instance status every 30 s until ``running`` (10-min timeout)."""
    print(f"Polling instance {instance_id} until status is 'running'...")
    start = time.time()
    last_status: str | None = None

    while True:
        elapsed = int(time.time() - start)
        if elapsed >= POLL_TIMEOUT_SECONDS:
            print(
                f"ERROR: Timed out after {elapsed}s waiting for instance to become "
                f"running (last status: {last_status})."
            )
            sys.exit(1)

        data = get_instance(token, instance_id)
        current_status = data.get("status", "unknown")

        if current_status != last_status:
            print(f"  [{elapsed}s] Instance status: {current_status}")
            last_status = current_status

        if current_status == "running":
            print(f"  Instance is running! (after {elapsed}s)")
            return data

        if current_status in ("deleting", "deleted", "destroying", "failed"):
            print(f"ERROR: Instance reached terminal status '{current_status}'.")
            sys.exit(1)

        time.sleep(POLL_INTERVAL_SECONDS)


# ---------------------------------------------------------------------------
# GitHub Actions output
# ---------------------------------------------------------------------------


def write_github_output(outputs: dict[str, str]) -> None:
    """Append key=value pairs to ``$GITHUB_OUTPUT`` if available.

    The calling workflow is responsible for masking sensitive outputs
    (e.g. via ``::add-mask::``) to prevent secrets from appearing in logs.
    """
    github_output = os.environ.get("GITHUB_OUTPUT")
    if not github_output:
        print("  GITHUB_OUTPUT not set — skipping output file writes.")
        return

    with open(github_output, "a") as f:
        for key, value in outputs.items():
            f.write(f"{key}={value}\n")
    print(f"  Wrote {len(outputs)} output(s) to GITHUB_OUTPUT.")


def _write_secret_output(key: str, value: str) -> None:
    """Write a single sensitive value to ``$GITHUB_OUTPUT`` with masking.

    Uses ``::add-mask::`` to ensure the value is redacted in all subsequent
    workflow log output.
    """
    github_output = os.environ.get("GITHUB_OUTPUT")
    if not github_output:
        return
    if value:
        os.write(sys.stdout.fileno(), f"::add-mask::{value}\n".encode())
    with open(github_output, "a") as f:
        f.write(f"{key}={value}\n")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    # ---- Read configuration from environment ----
    client_id = _required_env("AURA_CLIENT_ID")
    client_secret = _required_env("AURA_CLIENT_SECRET")
    tenant_id = _required_env("AURA_TENANT_ID")
    environment = os.environ.get("ENVIRONMENT", "dev").strip() or "dev"

    instance_name = INSTANCE_NAME_TEMPLATE.format(environment=environment)

    print(f"Neo4j AuraDB provisioning — target instance: '{instance_name}'")
    print(f"  Environment: {environment}")

    # ---- Authenticate ----
    token = authenticate(client_id, client_secret)

    # ---- Check for existing instance ----
    print("Checking for existing instances...")
    instances = list_instances(token)
    print(f"  Found {len(instances)} instance(s) in tenant.")

    existing = find_instance_by_name(instances, instance_name)
    instance_created = False
    initial_password = ""

    if existing is not None:
        instance_id: str = existing["id"]
        status = existing.get("status", "unknown")
        print(
            f"  Instance '{instance_name}' already exists " f"(id={instance_id}, status={status})."
        )

        if status == "paused":
            resume_instance(token, instance_id)
        elif status == "running":
            print("  Instance is already running — nothing to do.")
            # Fetch full details for connection_url
            data = get_instance(token, instance_id)
            connection_url: str = data.get("connection_url", "")

            write_github_output(
                {
                    "neo4j_uri": connection_url,
                    "neo4j_instance_id": instance_id,
                    "instance_created": "false",
                }
            )
            _write_secret_output("neo4j_password", "")

            print("\nDone. Instance was already running.")
            print(f"  URI: {connection_url}")
            print("  Password: (not available — only returned on creation)")
            return
        else:
            print(f"  Instance status is '{status}' — will poll until running.")
    else:
        # ---- Create new instance ----
        data, initial_password = create_instance(
            token,
            name=instance_name,
            tenant_id=tenant_id,
        )
        instance_id = data["id"]
        instance_created = True

    # ---- Poll until running ----
    data = poll_until_running(token, instance_id)
    connection_url = data.get("connection_url", "")

    # ---- Write outputs ----
    write_github_output(
        {
            "neo4j_uri": connection_url,
            "neo4j_instance_id": instance_id,
            "instance_created": "true" if instance_created else "false",
        }
    )
    _write_secret_output("neo4j_password", initial_password)

    # ---- Summary ----
    print("\nProvisioning complete.")
    print(f"  Instance ID:  {instance_id}")
    print(f"  Created:      {instance_created}")
    print(f"  Password:     {'captured' if initial_password else 'not available'}")


if __name__ == "__main__":
    main()
