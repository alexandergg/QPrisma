"""Unit tests for ``scripts/purge_agent_versions.py``.

The script wipes the legacy ``qprisma-video-agent`` (and every accumulated
version) from a Foundry project before re-deploying with the refreshed
``azure-ai-agentserver-responses`` runtime. These tests exercise the helper
functions in isolation with an ``AIProjectClient`` mock so we can validate
idempotency, the ``--dry-run`` switch, and the REST fallback path without
touching Azure.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from azure.core.exceptions import HttpResponseError, ResourceNotFoundError

SCRIPT_PATH = Path(__file__).resolve().parent.parent.parent / "scripts" / "purge_agent_versions.py"


@pytest.fixture(scope="module")
def purge_module():
    """Load ``scripts/purge_agent_versions.py`` as a module without packaging it."""
    spec = importlib.util.spec_from_file_location("purge_agent_versions", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules["purge_agent_versions"] = module
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


@pytest.fixture
def mock_client():
    """Mock ``AIProjectClient`` with an ``agents`` attribute."""
    client = MagicMock(name="AIProjectClient")
    client.agents = MagicMock(name="agents_ops")
    return client


# ---------------------------------------------------------------------------
# _extract_version
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestExtractVersion:
    def test_extracts_from_dict(self, purge_module):
        assert purge_module._extract_version({"version": "v3"}) == "v3"

    def test_extracts_from_object(self, purge_module):
        item = SimpleNamespace(version="v9")
        assert purge_module._extract_version(item) == "v9"

    def test_returns_none_for_missing(self, purge_module):
        assert purge_module._extract_version({}) is None
        assert purge_module._extract_version(SimpleNamespace()) is None
        assert purge_module._extract_version(None) is None

    def test_returns_none_for_non_string(self, purge_module):
        assert purge_module._extract_version({"version": 7}) is None
        assert purge_module._extract_version({"version": ""}) is None


# ---------------------------------------------------------------------------
# list_versions
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestListVersions:
    def test_returns_versions_from_iterable(self, purge_module, mock_client):
        mock_client.agents.list_versions.return_value = iter(
            [SimpleNamespace(version="v1"), SimpleNamespace(version="v2")]
        )
        result = purge_module.list_versions(mock_client, "agent")
        assert result == ["v1", "v2"]

    def test_returns_empty_on_resource_not_found(self, purge_module, mock_client):
        mock_client.agents.list_versions.side_effect = ResourceNotFoundError(
            response=MagicMock(status_code=404)
        )
        assert purge_module.list_versions(mock_client, "agent") == []

    def test_returns_empty_on_http_404(self, purge_module, mock_client):
        err = HttpResponseError(response=MagicMock(status_code=404))
        err.status_code = 404
        mock_client.agents.list_versions.side_effect = err
        assert purge_module.list_versions(mock_client, "agent") == []

    def test_reraises_on_other_http_errors(self, purge_module, mock_client):
        err = HttpResponseError(response=MagicMock(status_code=500))
        err.status_code = 500
        mock_client.agents.list_versions.side_effect = err
        with pytest.raises(HttpResponseError):
            purge_module.list_versions(mock_client, "agent")

    def test_skips_items_without_version(self, purge_module, mock_client):
        mock_client.agents.list_versions.return_value = [
            SimpleNamespace(version="v1"),
            SimpleNamespace(version=""),
            {"version": "v3"},
            {"name": "no-version"},
        ]
        assert purge_module.list_versions(mock_client, "agent") == ["v1", "v3"]


# ---------------------------------------------------------------------------
# delete_version
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDeleteVersion:
    def test_dry_run_does_not_call_sdk(self, purge_module, mock_client):
        result = purge_module.delete_version(mock_client, "agent", "v1", dry_run=True)
        assert result is False
        mock_client.agents.delete_version.assert_not_called()

    def test_successful_delete(self, purge_module, mock_client):
        result = purge_module.delete_version(mock_client, "agent", "v1", dry_run=False)
        assert result is True
        mock_client.agents.delete_version.assert_called_once_with(
            agent_name="agent", agent_version="v1"
        )

    def test_idempotent_on_resource_not_found(self, purge_module, mock_client):
        mock_client.agents.delete_version.side_effect = ResourceNotFoundError(
            response=MagicMock(status_code=404)
        )
        assert purge_module.delete_version(mock_client, "agent", "v1", dry_run=False) is False

    def test_idempotent_on_http_404(self, purge_module, mock_client):
        err = HttpResponseError(response=MagicMock(status_code=404))
        err.status_code = 404
        mock_client.agents.delete_version.side_effect = err
        assert purge_module.delete_version(mock_client, "agent", "v1", dry_run=False) is False

    def test_warns_on_other_http_error(self, purge_module, mock_client):
        err = HttpResponseError(response=MagicMock(status_code=500))
        err.status_code = 500
        mock_client.agents.delete_version.side_effect = err
        assert purge_module.delete_version(mock_client, "agent", "v1", dry_run=False) is False


# ---------------------------------------------------------------------------
# delete_agent
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDeleteAgent:
    def test_dry_run_does_not_call_sdk(self, purge_module, mock_client):
        result = purge_module.delete_agent(mock_client, "agent", dry_run=True)
        assert result is False
        mock_client.agents.delete.assert_not_called()

    def test_successful_delete(self, purge_module, mock_client):
        result = purge_module.delete_agent(mock_client, "agent", dry_run=False)
        assert result is True
        mock_client.agents.delete.assert_called_once_with(agent_name="agent")

    def test_idempotent_on_resource_not_found(self, purge_module, mock_client):
        mock_client.agents.delete.side_effect = ResourceNotFoundError(
            response=MagicMock(status_code=404)
        )
        assert purge_module.delete_agent(mock_client, "agent", dry_run=False) is False

    def test_idempotent_on_http_404(self, purge_module, mock_client):
        err = HttpResponseError(response=MagicMock(status_code=404))
        err.status_code = 404
        mock_client.agents.delete.side_effect = err
        assert purge_module.delete_agent(mock_client, "agent", dry_run=False) is False

    def test_falls_back_to_rest_on_other_http_error(self, purge_module, mock_client):
        err = HttpResponseError(response=MagicMock(status_code=500))
        err.status_code = 500
        mock_client.agents.delete.side_effect = err

        with patch.object(purge_module, "_rest_delete_assistant", return_value=True) as rest_mock:
            result = purge_module.delete_agent(
                mock_client,
                "agent",
                dry_run=False,
                project_endpoint="https://example.services.ai.azure.com/api/projects/p1",
            )
        assert result is True
        rest_mock.assert_called_once()

    def test_no_rest_fallback_when_endpoint_missing(self, purge_module, mock_client):
        err = HttpResponseError(response=MagicMock(status_code=500))
        err.status_code = 500
        mock_client.agents.delete.side_effect = err

        with patch.object(purge_module, "_rest_delete_assistant") as rest_mock:
            result = purge_module.delete_agent(mock_client, "agent", dry_run=False)
        assert result is False
        rest_mock.assert_not_called()


# ---------------------------------------------------------------------------
# _rest_delete_assistant
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRestDeleteAssistant:
    def test_skipped_when_az_cli_missing(self, purge_module):
        with patch.object(purge_module.shutil, "which", return_value=None):
            assert (
                purge_module._rest_delete_assistant("https://example/api/projects/p1", "agent")
                is False
            )

    def test_returns_true_on_success(self, purge_module):
        proc = SimpleNamespace(returncode=0, stderr="", stdout="")
        with (
            patch.object(purge_module.shutil, "which", return_value="az"),
            patch.object(purge_module.subprocess, "run", return_value=proc),
        ):
            assert (
                purge_module._rest_delete_assistant("https://example/api/projects/p1/", "agent")
                is True
            )

    def test_returns_true_on_404_in_stderr(self, purge_module):
        proc = SimpleNamespace(returncode=1, stderr="NotFound: 404", stdout="")
        with (
            patch.object(purge_module.shutil, "which", return_value="az"),
            patch.object(purge_module.subprocess, "run", return_value=proc),
        ):
            assert (
                purge_module._rest_delete_assistant("https://example/api/projects/p1", "agent")
                is True
            )

    def test_returns_false_on_unrecognised_failure(self, purge_module):
        proc = SimpleNamespace(returncode=1, stderr="boom", stdout="")
        with (
            patch.object(purge_module.shutil, "which", return_value="az"),
            patch.object(purge_module.subprocess, "run", return_value=proc),
        ):
            assert (
                purge_module._rest_delete_assistant("https://example/api/projects/p1", "agent")
                is False
            )


# ---------------------------------------------------------------------------
# parse_args / main
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestParseArgs:
    def test_defaults(self, purge_module, monkeypatch):
        monkeypatch.delenv("AGENT_NAME", raising=False)
        ns = purge_module.parse_args([])
        assert ns.agent_name == purge_module.DEFAULT_AGENT_NAME
        assert ns.dry_run is False

    def test_overrides(self, purge_module):
        ns = purge_module.parse_args(["--dry-run", "--agent-name", "other"])
        assert ns.agent_name == "other"
        assert ns.dry_run is True

    def test_env_default_for_agent_name(self, purge_module, monkeypatch):
        monkeypatch.setenv("AGENT_NAME", "from-env")
        ns = purge_module.parse_args([])
        assert ns.agent_name == "from-env"


@pytest.mark.unit
class TestMain:
    def test_returns_error_when_endpoint_missing(self, purge_module, monkeypatch):
        monkeypatch.delenv("AZURE_AI_PROJECT_ENDPOINT", raising=False)
        assert purge_module.main([]) == 1

    def test_full_flow_invokes_list_and_deletes(self, purge_module, monkeypatch):
        monkeypatch.setenv(
            "AZURE_AI_PROJECT_ENDPOINT",
            "https://example.services.ai.azure.com/api/projects/p1",
        )

        client = MagicMock()
        with (
            patch.object(purge_module, "AIProjectClient", return_value=client),
            patch.object(purge_module, "DefaultAzureCredential"),
            patch.object(purge_module, "list_versions", return_value=["v1", "v2"]) as list_mock,
            patch.object(purge_module, "delete_version") as dv_mock,
            patch.object(purge_module, "delete_agent") as da_mock,
        ):
            rc = purge_module.main(["--agent-name", "agent"])

        assert rc == 0
        list_mock.assert_called_once_with(client, "agent")
        assert dv_mock.call_count == 2
        da_mock.assert_called_once()

    def test_dry_run_propagates(self, purge_module, monkeypatch):
        monkeypatch.setenv(
            "AZURE_AI_PROJECT_ENDPOINT",
            "https://example.services.ai.azure.com/api/projects/p1",
        )

        with (
            patch.object(purge_module, "AIProjectClient"),
            patch.object(purge_module, "DefaultAzureCredential"),
            patch.object(purge_module, "list_versions", return_value=["v1"]),
            patch.object(purge_module, "delete_version") as dv_mock,
            patch.object(purge_module, "delete_agent") as da_mock,
        ):
            purge_module.main(["--dry-run", "--agent-name", "agent"])

        assert dv_mock.call_args.kwargs.get("dry_run") is True
        assert da_mock.call_args.kwargs.get("dry_run") is True
