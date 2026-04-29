"""Hosted Agent startup secret resolution."""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Callable, MutableMapping
from dataclasses import dataclass
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from azure.identity import DefaultAzureCredential

logger = logging.getLogger(__name__)

KEY_VAULT_API_VERSION = "7.4"
KEY_VAULT_SCOPE = "https://vault.azure.net/.default"

SECRET_ENV_URI_MAP = {
    "NEO4J_PASSWORD": "NEO4J_PASSWORD_KEY_VAULT_URI",
    "DATABASE_URL": "DATABASE_URL_KEY_VAULT_URI",
    "REDIS_URL": "REDIS_URL_KEY_VAULT_URI",
}


class _TokenCredential(Protocol):
    def get_token(self, *scopes: str):
        """Return an Azure access token."""


@dataclass(frozen=True)
class KeyVaultSecretRef:
    """Parsed Key Vault secret reference."""

    target_env_var: str
    uri_env_var: str
    uri: str
    vault_host: str
    secret_name: str


def _parse_secret_ref(target_env_var: str, uri_env_var: str, uri: str) -> KeyVaultSecretRef:
    parsed = urlparse(uri)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError(f"{uri_env_var} must be an https Key Vault secret URI")

    path_parts = [part for part in parsed.path.split("/") if part]
    if len(path_parts) < 2 or path_parts[0].lower() != "secrets":
        raise ValueError(f"{uri_env_var} must point to a Key Vault /secrets/<name> URI")

    return KeyVaultSecretRef(
        target_env_var=target_env_var,
        uri_env_var=uri_env_var,
        uri=uri,
        vault_host=parsed.netloc,
        secret_name=path_parts[1],
    )


def _secret_url(uri: str) -> str:
    separator = "&" if "?" in uri else "?"
    return f"{uri}{separator}api-version={KEY_VAULT_API_VERSION}"


def _fetch_secret_value(
    ref: KeyVaultSecretRef,
    *,
    credential: _TokenCredential,
    opener: Callable[..., object],
) -> str:
    token = credential.get_token(KEY_VAULT_SCOPE).token
    request = Request(  # noqa: S310 - URI is validated as a Key Vault secret URI.
        _secret_url(ref.uri),
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
    )

    try:
        with opener(request, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"Key Vault returned HTTP {exc.code} for {ref.uri_env_var} "
            f"({ref.vault_host}/{ref.secret_name}): {detail}"
        ) from exc
    except URLError as exc:
        raise RuntimeError(
            f"Could not reach Key Vault for {ref.uri_env_var} "
            f"({ref.vault_host}/{ref.secret_name}): {exc.reason}"
        ) from exc

    value = payload.get("value")
    if not isinstance(value, str) or not value:
        raise RuntimeError(
            f"Key Vault response for {ref.uri_env_var} did not contain a non-empty secret value"
        )
    return value


def resolve_key_vault_secret_environment(
    *,
    env: MutableMapping[str, str] | None = None,
    credential: _TokenCredential | None = None,
    credential_factory: Callable[[], _TokenCredential] | None = None,
    opener: Callable[..., object] = urlopen,
) -> list[str]:
    """Resolve configured Key Vault secret URIs into runtime environment variables."""
    target_env = os.environ if env is None else env
    refs: list[KeyVaultSecretRef] = []

    for target_env_var, uri_env_var in SECRET_ENV_URI_MAP.items():
        if target_env.get(target_env_var):
            logger.info(
                "%s already configured directly; skipping Key Vault resolution", target_env_var
            )
            continue

        uri = target_env.get(uri_env_var, "")
        if not uri:
            continue
        refs.append(_parse_secret_ref(target_env_var, uri_env_var, uri))

    if not refs:
        return []

    active_credential = credential or (
        credential_factory() if credential_factory else DefaultAzureCredential()
    )

    resolved: list[str] = []
    for ref in refs:
        target_env[ref.target_env_var] = _fetch_secret_value(
            ref,
            credential=active_credential,
            opener=opener,
        )
        resolved.append(ref.target_env_var)
        logger.info(
            "Resolved %s from Key Vault secret %s/%s",
            ref.target_env_var,
            ref.vault_host,
            ref.secret_name,
        )

    return resolved
