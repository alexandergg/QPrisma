"""Tests for Hosted Agent Key Vault startup secret resolution."""

import json

import pytest
from agent.hosted.secrets import resolve_key_vault_secret_environment


class _Token:
    token = "test-token"


class _Credential:
    def get_token(self, *scopes: str):
        assert scopes == ("https://vault.azure.net/.default",)
        return _Token()


class _Response:
    def __init__(self, payload: dict[str, str]):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")


@pytest.mark.unit
def test_resolve_key_vault_secret_environment_resolves_configured_uris():
    env = {
        "NEO4J_PASSWORD_KEY_VAULT_URI": "https://kv-qprisma-dev.vault.azure.net/secrets/neo4j-password",
        "DATABASE_URL_KEY_VAULT_URI": "https://kv-qprisma-dev.vault.azure.net/secrets/database-url",
        "REDIS_URL_KEY_VAULT_URI": "https://kv-qprisma-dev.vault.azure.net/secrets/redis-url",
    }
    values = {
        "neo4j-password": "neo4j-secret",
        "database-url": "postgresql://db",
        "redis-url": "rediss://redis",
    }

    def opener(request, timeout: int):
        assert timeout == 10
        assert request.headers["Authorization"] == "Bearer test-token"
        secret_name = request.full_url.split("/secrets/", 1)[1].split("?", 1)[0]
        return _Response({"value": values[secret_name]})

    resolved = resolve_key_vault_secret_environment(
        env=env,
        credential=_Credential(),
        opener=opener,
    )

    assert resolved == ["NEO4J_PASSWORD", "DATABASE_URL", "REDIS_URL"]
    assert env["NEO4J_PASSWORD"] == "neo4j-secret"
    assert env["DATABASE_URL"] == "postgresql://db"
    assert env["REDIS_URL"] == "rediss://redis"


@pytest.mark.unit
def test_resolve_key_vault_secret_environment_keeps_direct_local_values():
    env = {
        "NEO4J_PASSWORD": "local-secret",
        "NEO4J_PASSWORD_KEY_VAULT_URI": "https://kv-qprisma-dev.vault.azure.net/secrets/neo4j-password",
    }

    resolved = resolve_key_vault_secret_environment(
        env=env,
        credential=_Credential(),
        opener=lambda request, timeout: pytest.fail("Key Vault should not be called"),
    )

    assert resolved == []
    assert env["NEO4J_PASSWORD"] == "local-secret"


@pytest.mark.unit
def test_resolve_key_vault_secret_environment_rejects_malformed_uri():
    env = {"DATABASE_URL_KEY_VAULT_URI": "not-a-secret-uri"}

    with pytest.raises(ValueError, match="DATABASE_URL_KEY_VAULT_URI"):
        resolve_key_vault_secret_environment(env=env, credential=_Credential())
