"""Tests for hosted agent deployment environment wiring."""

import importlib.util
import re
import sys
import types
from pathlib import Path
from unittest.mock import patch

import pytest

_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "deploy_agent.py"
_INSPECT_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "inspect_foundry_agent.py"
_REPO_ROOT = Path(__file__).resolve().parents[2]
_OPENAI_USER_ROLE_ID = "5e0bd9bd-7b93-4f28-af87-19fc36ad61bd"
_AI_PROJECT_MANAGER_ROLE_ID = "eadc314b-1a2d-4efa-be10-5d325db5065e"
_OPENAI_ROLE_DEFINITION_ID = (
    "roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', "
    "cognitiveServicesOpenAiUserRole)"
)


def _load_deploy_agent_module():
    azure_module = types.ModuleType("azure")
    azure_ai_module = types.ModuleType("azure.ai")
    azure_core_module = types.ModuleType("azure.core")
    azure_identity_module = types.ModuleType("azure.identity")
    azure_projects_module = types.ModuleType("azure.ai.projects")
    azure_projects_models_module = types.ModuleType("azure.ai.projects.models")
    azure_core_exceptions_module = types.ModuleType("azure.core.exceptions")

    azure_identity_module.DefaultAzureCredential = object
    azure_projects_module.AIProjectClient = object

    class DummyHostedAgentDefinition:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

    class DummyProtocolVersionRecord:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

    class DummyHttpResponseError(Exception):
        pass

    azure_projects_models_module.AgentProtocol = types.SimpleNamespace(RESPONSES="responses")
    azure_projects_models_module.HostedAgentDefinition = DummyHostedAgentDefinition
    azure_projects_models_module.ImageBasedHostedAgentDefinition = DummyHostedAgentDefinition
    azure_projects_models_module.ProtocolVersionRecord = DummyProtocolVersionRecord
    azure_core_exceptions_module.HttpResponseError = DummyHttpResponseError

    azure_module.ai = azure_ai_module
    azure_module.core = azure_core_module
    azure_module.identity = azure_identity_module
    azure_ai_module.projects = azure_projects_module
    azure_core_module.exceptions = azure_core_exceptions_module
    azure_projects_module.models = azure_projects_models_module

    module_name = "test_deploy_agent_module"
    spec = importlib.util.spec_from_file_location(module_name, _SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)

    with patch.dict(
        sys.modules,
        {
            "azure": azure_module,
            "azure.ai": azure_ai_module,
            "azure.ai.projects": azure_projects_module,
            "azure.ai.projects.models": azure_projects_models_module,
            "azure.core": azure_core_module,
            "azure.core.exceptions": azure_core_exceptions_module,
            "azure.identity": azure_identity_module,
            module_name: module,
        },
    ):
        spec.loader.exec_module(module)

    return module


def _load_inspect_foundry_agent_module():
    azure_module = types.ModuleType("azure")
    azure_identity_module = types.ModuleType("azure.identity")
    azure_identity_module.DefaultAzureCredential = object

    module_name = "test_inspect_foundry_agent_module"
    spec = importlib.util.spec_from_file_location(module_name, _INSPECT_SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)

    with patch.dict(
        sys.modules,
        {
            "azure": azure_module,
            "azure.identity": azure_identity_module,
            module_name: module,
        },
    ):
        spec.loader.exec_module(module)

    return module


def _resource_block(contents: str, resource_name: str) -> str:
    match = re.search(
        rf"^resource {re.escape(resource_name)} '[^']+' = \{{.*?^}}",
        contents,
        flags=re.DOTALL | re.MULTILINE,
    )
    assert match is not None, f"{resource_name} resource block missing"
    return match.group(0)


def _workflow_step_block(contents: str, step_name: str) -> str:
    match = re.search(
        rf"^\s*-\s+name:\s+{re.escape(step_name)}\s*$.*?(?=^\s*-\s+name:|\Z)",
        contents,
        flags=re.DOTALL | re.MULTILINE,
    )
    assert match is not None, f"workflow step {step_name!r} missing"
    return match.group(0)


class _IdentityObject:
    def __init__(self, principal_id: str):
        self.principal_id = principal_id


@pytest.mark.unit
def test_build_environment_variables_defaults_to_secretless_hosted_contract():
    deploy_agent = _load_deploy_agent_module()
    env_vars = deploy_agent.build_environment_variables(env={})

    assert env_vars["ENVIRONMENT"] == "hosted"
    assert env_vars["AZURE_OPENAI_ENDPOINT"] == "https://aif-qprisma-dev.openai.azure.com/"
    assert env_vars["AZURE_OPENAI_API_VERSION"] == "2025-04-01-preview"
    assert env_vars["AZURE_OPENAI_DEPLOYMENT_GPT"] == "gpt-5.5"
    assert env_vars["AZURE_OPENAI_DEPLOYMENT_EMBEDDING"] == "text-embedding-3-large"
    assert env_vars["AZURE_USE_MANAGED_IDENTITY"] == "true"
    assert "NEO4J_PASSWORD" not in env_vars
    assert "DATABASE_URL" not in env_vars
    assert "REDIS_URL" not in env_vars
    assert "AZURE_STORAGE_CONNECTION_STRING" not in env_vars


@pytest.mark.unit
def test_build_environment_variables_preserves_explicit_runtime_overrides():
    deploy_agent = _load_deploy_agent_module()
    env_vars = deploy_agent.build_environment_variables(
        env={
            "AZURE_OPENAI_ENDPOINT": "https://custom.openai.azure.com/",
            "AZURE_OPENAI_API_VERSION": "2025-01-01-preview",
            "AZURE_OPENAI_DEPLOYMENT_GPT": "gpt-4.1",
            "AZURE_OPENAI_DEPLOYMENT_EMBEDDING": "text-embedding-3-small",
            "AZURE_USE_MANAGED_IDENTITY": "false",
            "NEO4J_URI": "neo4j+s://example.databases.neo4j.io",
            "NEO4J_PASSWORD": "neo4j-secret",
            "DATABASE_URL": "postgresql://db-secret",
            "REDIS_URL": "rediss://redis-secret",
            "AZURE_STORAGE_CONNECTION_STRING": "DefaultEndpointsProtocol=https;AccountKey=secret",
        }
    )

    assert env_vars["AZURE_OPENAI_ENDPOINT"] == "https://custom.openai.azure.com/"
    assert env_vars["AZURE_OPENAI_API_VERSION"] == "2025-01-01-preview"
    assert env_vars["AZURE_OPENAI_DEPLOYMENT_GPT"] == "gpt-4.1"
    assert env_vars["AZURE_OPENAI_DEPLOYMENT_EMBEDDING"] == "text-embedding-3-small"
    assert env_vars["AZURE_USE_MANAGED_IDENTITY"] == "false"
    assert env_vars["NEO4J_URI"] == "neo4j+s://example.databases.neo4j.io"
    assert env_vars["NEO4J_PASSWORD"] == "neo4j-secret"
    assert env_vars["DATABASE_URL"] == "postgresql://db-secret"
    assert env_vars["REDIS_URL"] == "rediss://redis-secret"
    assert (
        env_vars["AZURE_STORAGE_CONNECTION_STRING"]
        == "DefaultEndpointsProtocol=https;AccountKey=secret"
    )


@pytest.mark.unit
def test_build_environment_variables_rejects_legacy_secret_reference_values():
    deploy_agent = _load_deploy_agent_module()
    env = {
        "NEO4J_PASSWORD_KEY_VAULT_URI": "https://kv.vault.azure.net/secrets/neo4j-password",
        "DATABASE_URL_KV_URI": "https://kv.vault.azure.net/secrets/database-url",
        "REDIS_URL_KEY_VAULT_URI": "https://kv.vault.azure.net/secrets/redis-url",
        "AZURE_STORAGE_ACCOUNT_URL": "https://storage.blob.core.windows.net",
    }

    with pytest.raises(ValueError, match="Key Vault URI"):
        deploy_agent.build_environment_variables(env=env)


@pytest.mark.unit
def test_build_environment_variables_accepts_memory_contract_aliases():
    deploy_agent = _load_deploy_agent_module()
    env_vars = deploy_agent.build_environment_variables(
        env={
            "FOUNDRY_MEMORY_STORE_NAME": "qprisma-memory",
            "FOUNDRY_MEMORY_CHAT_MODEL": "gpt-5.5",
            "FOUNDRY_MEMORY_EMBEDDING_MODEL": "text-embedding-3-large",
        }
    )

    assert env_vars["MEMORY_STORE_NAME"] == "qprisma-memory"
    assert env_vars["MEMORY_CHAT_MODEL"] == "gpt-5.5"
    assert env_vars["MEMORY_EMBEDDING_MODEL"] == "text-embedding-3-large"


@pytest.mark.unit
def test_hosted_manifest_openai_api_version_matches_script_default():
    deploy_agent = _load_deploy_agent_module()
    default_api_version = deploy_agent.build_environment_variables(env={})[
        "AZURE_OPENAI_API_VERSION"
    ]
    manifest_path = Path(__file__).resolve().parents[1] / "agent" / "hosted" / "agent.yaml"
    lines = manifest_path.read_text(encoding="utf-8").splitlines()

    for index, line in enumerate(lines):
        if line.strip() == "- name: AZURE_OPENAI_API_VERSION":
            assert lines[index + 1].strip() == 'value: "${AZURE_OPENAI_API_VERSION}"'
            assert default_api_version == "2025-04-01-preview"
            break
    else:
        pytest.fail("AZURE_OPENAI_API_VERSION missing from hosted agent manifest")


@pytest.mark.unit
def test_hosted_manifest_uses_flat_azd_shape():
    manifest = (_REPO_ROOT / "backend" / "agent" / "hosted" / "agent.yaml").read_text(
        encoding="utf-8"
    )
    infra_main = (_REPO_ROOT / "infra" / "main.bicep").read_text(encoding="utf-8")

    assert manifest.startswith("kind: hosted\nname: qprisma-video-agent\n")
    assert "\ntemplate:" not in manifest
    assert "id: gpt-5.5" not in manifest
    assert 'value: "${AZURE_OPENAI_DEPLOYMENT_GPT}"' in manifest
    assert 'value: "${AZURE_OPENAI_DEPLOYMENT_EMBEDDING}"' in manifest
    assert "APPLICATIONINSIGHTS_CONNECTION_STRING" not in manifest
    assert "{ name: 'AZURE_OPENAI_DEPLOYMENT_GPT', value: 'gpt-5.5' }" in infra_main


@pytest.mark.unit
def test_azure_yaml_declares_official_hosted_agent_service():
    azure_yaml = (_REPO_ROOT / "azure.yaml").read_text(encoding="utf-8")

    assert 'azure.ai.agents: ">=0.1.0-preview"' in azure_yaml
    assert "qprisma-video-agent:" in azure_yaml
    assert "project: ./backend/agent/hosted" in azure_yaml
    assert "host: azure.ai.agent" in azure_yaml
    assert "language: docker" in azure_yaml
    assert "context: ../.." in azure_yaml
    assert "remoteBuild: true" in azure_yaml
    assert "startupCommand: python -m agent.hosted.main" in azure_yaml
    assert "postdeploy.ps1" in azure_yaml
    assert "postdeploy.sh" in azure_yaml


@pytest.mark.unit
def test_deploy_hosted_agent_workflow_uses_azd_and_gpt_55_default():
    hosted_workflow = (_REPO_ROOT / ".github" / "workflows" / "deploy-hosted-agent.yml").read_text(
        encoding="utf-8"
    )
    preflight_step = _workflow_step_block(
        hosted_workflow, "Preflight - verify chat deployment exists"
    )
    init_step = _workflow_step_block(hosted_workflow, "Initialize azd environment")
    configure_step = _workflow_step_block(hosted_workflow, "Configure azd environment")
    deploy_step = _workflow_step_block(hosted_workflow, "Deploy hosted agent with azd")
    inspect_step = _workflow_step_block(hosted_workflow, "Inspect deployed agent")

    assert (
        "DEPLOYMENT_NAME: ${{ inputs.chat_deployment || "
        "vars.AZURE_OPENAI_DEPLOYMENT_GPT || 'gpt-5.5' }}" in preflight_step
    )
    assert (
        "CHAT_DEPLOYMENT: ${{ inputs.chat_deployment || vars.AZURE_OPENAI_DEPLOYMENT_GPT || 'gpt-5.5' }}"
        in configure_step
    )
    assert 'set_azd_env AZURE_OPENAI_DEPLOYMENT_GPT "$CHAT_DEPLOYMENT"' in configure_step
    assert 'azd deploy "$SERVICE_NAME" --no-prompt' in deploy_step
    assert 'azd env select "$AZD_ENV_NAME" --no-prompt' in init_step
    assert 'azd env new "$AZD_ENV_NAME"' in init_step
    assert f'AI_PROJECT_MANAGER_ROLE="{_AI_PROJECT_MANAGER_ROLE_ID}"' in hosted_workflow
    assert "Register agent in Foundry" not in hosted_workflow
    assert "python scripts/deploy_agent.py" not in hosted_workflow
    assert "Python SDK (AIProjectClient)" not in hosted_workflow
    assert "azd + azure.ai.agent" in hosted_workflow
    assert "default: gpt-5.5" in hosted_workflow
    assert "default: gpt-5.4-pro" not in hosted_workflow
    assert "MEMORY_CHAT_MODEL: ${{ vars.MEMORY_CHAT_MODEL || 'gpt-5.5' }}" in configure_step
    assert "python - <<'PY'" in inspect_step
    assert "hosted-agent-inspection.json" in inspect_step
    assert "jq" not in inspect_step


@pytest.mark.unit
def test_extract_agent_identity_principal_id_supports_mapping_and_model():
    deploy_agent = _load_deploy_agent_module()

    mapping_agent = types.SimpleNamespace(instance_identity={"principal_id": "pid-from-mapping"})
    model_agent = types.SimpleNamespace(instance_identity=_IdentityObject("pid-from-model"))
    missing_agent = types.SimpleNamespace(instance_identity=None)

    assert deploy_agent._extract_agent_identity_principal_id(mapping_agent) == "pid-from-mapping"
    assert deploy_agent._extract_agent_identity_principal_id(model_agent) == "pid-from-model"
    assert deploy_agent._extract_agent_identity_principal_id(missing_agent) is None


@pytest.mark.unit
def test_extract_agent_version_status_supports_mapping_and_model():
    deploy_agent = _load_deploy_agent_module()

    mapping_version = {"status": "creating"}
    model_version = types.SimpleNamespace(status="active")
    missing_version = types.SimpleNamespace(status=None)

    assert deploy_agent._extract_agent_version_status(mapping_version) == "creating"
    assert deploy_agent._extract_agent_version_status(model_version) == "active"
    assert deploy_agent._extract_agent_version_status(missing_version) is None


@pytest.mark.unit
def test_wait_for_agent_active_polls_foundry_sdk_until_active():
    deploy_agent = _load_deploy_agent_module()

    class _AgentsClient:
        def __init__(self):
            self.calls = 0

        def get_version(self, *, agent_name: str, agent_version: str):
            self.calls += 1
            assert agent_name == deploy_agent.AGENT_NAME
            assert agent_version == "7"
            if self.calls == 1:
                return {"status": "creating"}
            return types.SimpleNamespace(status="active")

    fake_client = types.SimpleNamespace(agents=_AgentsClient())

    with patch.object(deploy_agent.time, "sleep") as sleep_mock:
        active = deploy_agent.wait_for_agent_active(fake_client, "7")

    assert active == "active"
    sleep_mock.assert_called_once_with(deploy_agent.POLL_INTERVAL_SECONDS)


@pytest.mark.unit
def test_wait_for_agent_active_surfaces_failure_details():
    deploy_agent = _load_deploy_agent_module()

    class _AgentsClient:
        def get_version(self, *, agent_name: str, agent_version: str):
            assert agent_name == deploy_agent.AGENT_NAME
            assert agent_version == "9"
            return {
                "status": "failed",
                "error": {
                    "code": "image_pull_failed",
                    "message": "bad image",
                },
            }

    fake_client = types.SimpleNamespace(agents=_AgentsClient())

    with patch("builtins.print") as print_mock:
        active = deploy_agent.wait_for_agent_active(fake_client, "9")

    assert active == "failed"
    printed = "\n".join(call.args[0] for call in print_mock.call_args_list if call.args)
    assert "Provisioning error: image_pull_failed: bad image" in printed


@pytest.mark.unit
def test_resolve_agent_identity_principal_id_polls_foundry_api():
    deploy_agent = _load_deploy_agent_module()

    class _AgentsClient:
        def __init__(self):
            self.calls = 0

        def get(self, *, agent_name: str):
            self.calls += 1
            assert agent_name == deploy_agent.AGENT_NAME
            if self.calls == 1:
                return types.SimpleNamespace(instance_identity=None)
            return types.SimpleNamespace(instance_identity={"principal_id": "pid-from-foundry"})

    fake_client = types.SimpleNamespace(agents=_AgentsClient())

    with patch.object(deploy_agent.time, "sleep") as sleep_mock:
        principal_id, source = deploy_agent.resolve_agent_identity_principal_id(
            fake_client,
            attempts=3,
            wait_seconds=1,
        )

    assert principal_id == "pid-from-foundry"
    assert source == "sdk"
    sleep_mock.assert_called_once_with(1)


@pytest.mark.unit
def test_agent_identity_lookup_defaults_to_fast_best_effort(monkeypatch):
    monkeypatch.delenv("AGENT_IDENTITY_LOOKUP_ATTEMPTS", raising=False)
    monkeypatch.delenv("AGENT_IDENTITY_LOOKUP_WAIT_SECONDS", raising=False)
    monkeypatch.delenv("AGENT_IDENTITY_REST_TIMEOUT_SECONDS", raising=False)
    deploy_agent = _load_deploy_agent_module()
    hosted_workflow = (_REPO_ROOT / ".github" / "workflows" / "deploy-hosted-agent.yml").read_text(
        encoding="utf-8"
    )
    postdeploy_hook = (_REPO_ROOT / "infra" / "hooks" / "postdeploy.sh").read_text(encoding="utf-8")

    assert deploy_agent.AGENT_IDENTITY_LOOKUP_ATTEMPTS == 1
    assert deploy_agent.AGENT_IDENTITY_LOOKUP_WAIT_SECONDS == 15
    assert deploy_agent.AGENT_IDENTITY_REST_TIMEOUT_SECONDS == 15
    assert "AGENT_IDENTITY_LOOKUP_ATTEMPTS" not in hosted_workflow
    assert (
        "set_azd_env REQUIRE_AGENT_IDENTITY_RBAC \"${{ vars.REQUIRE_AGENT_IDENTITY_RBAC || 'false' }}\""
        in hosted_workflow
    )
    assert "Hosted agent runtime identity is not available yet; skipping" in postdeploy_hook
    assert "extract_agent_principal_id()" in postdeploy_hook
    assert "command -v jq" in postdeploy_hook
    assert "command -v python3" in postdeploy_hook


@pytest.mark.unit
def test_hosted_agent_openai_rbac_is_durable_and_graph_free():
    ai_foundry_bicep = (_REPO_ROOT / "infra" / "modules" / "ai-foundry.bicep").read_text(
        encoding="utf-8"
    )
    hosted_workflow = (_REPO_ROOT / ".github" / "workflows" / "deploy-hosted-agent.yml").read_text(
        encoding="utf-8"
    )
    ai_foundry_workflow = (
        _REPO_ROOT / ".github" / "workflows" / "deploy-ai-foundry.yml"
    ).read_text(encoding="utf-8")
    deploy_agent_script = _SCRIPT_PATH.read_text(encoding="utf-8")
    ai_foundry_openai_role = _resource_block(ai_foundry_bicep, "openAiRoleAiFoundry")
    project_openai_role = _resource_block(ai_foundry_bicep, "openAiRoleProject")

    assert f"var cognitiveServicesOpenAiUserRole = '{_OPENAI_USER_ROLE_ID}'" in ai_foundry_bicep
    assert "scope: aiFoundry" in ai_foundry_openai_role
    assert _OPENAI_ROLE_DEFINITION_ID in ai_foundry_openai_role
    assert "principalId: aiFoundry.identity.principalId" in ai_foundry_openai_role
    assert "scope: aiFoundry" in project_openai_role
    assert _OPENAI_ROLE_DEFINITION_ID in project_openai_role
    assert "principalId: aiProject.identity.principalId" in project_openai_role
    assert _OPENAI_USER_ROLE_ID in deploy_agent_script
    assert "Cognitive Services OpenAI User" in deploy_agent_script
    assert "'infra/modules/ai-foundry.bicep'" in hosted_workflow
    assert "Ensure hosted agent instance identity has Azure OpenAI access" not in hosted_workflow
    assert "Key Vault Secrets User" not in hosted_workflow
    assert "Storage Blob Data Contributor" not in hosted_workflow
    assert "az ad sp list" not in hosted_workflow
    assert "Ensure hosted AgentIdentity has Azure OpenAI access" not in ai_foundry_workflow
    assert "az ad sp list" not in ai_foundry_workflow
    assert 'azd deploy "$SERVICE_NAME" --no-prompt' in hosted_workflow
    assert "Python SDK (AIProjectClient)" not in hosted_workflow
    assert "resolve_agent_identity_principal_id" in deploy_agent_script
    assert "client.agents.get(agent_name=AGENT_NAME)" in deploy_agent_script
    assert "HostedAgentDefinition" in deploy_agent_script
    assert "client.agents.get_version(" in deploy_agent_script
    assert "wait_for_agent_active" in deploy_agent_script
    assert "allow_preview=True" in deploy_agent_script
    assert "agent_identity_principal_id=" in deploy_agent_script
    assert "agent start" not in deploy_agent_script
    assert "agent show" not in deploy_agent_script


def _read_github_output(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line:
            key, _, value = line.partition("=")
            result[key] = value
    return result


def _make_main_test_client(deploy_agent):
    fake_agent = types.SimpleNamespace(name="qprisma-video-agent", id="agent-id-1", version="42")

    class _Agents:
        def create_version(self, *, agent_name, description, definition):
            assert agent_name == deploy_agent.AGENT_NAME
            return fake_agent

    class _Client:
        def __init__(self, *args, **kwargs):
            self.agents = _Agents()

    return _Client, fake_agent


def _setup_main_env(monkeypatch, tmp_path: Path) -> Path:
    output_path = tmp_path / "github_output.txt"
    output_path.write_text("", encoding="utf-8")
    monkeypatch.setenv(
        "AZURE_AI_PROJECT_ENDPOINT", "https://fake.services.ai.azure.com/api/projects/fake"
    )
    monkeypatch.setenv("CONTAINER_IMAGE", "fakeacr.azurecr.io/qprisma-video-agent:test")
    monkeypatch.setenv("GITHUB_OUTPUT", str(output_path))
    monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT_GPT", "gpt-4.1")
    monkeypatch.setenv("NEO4J_URI", "neo4j+s://fake.databases.neo4j.io")
    monkeypatch.setenv("NEO4J_PASSWORD", "neo4j-secret")
    monkeypatch.setenv("DATABASE_URL", "postgresql://fake-db")
    monkeypatch.setenv("REDIS_URL", "rediss://fake-redis")
    monkeypatch.setenv(
        "AZURE_STORAGE_CONNECTION_STRING",
        "DefaultEndpointsProtocol=https;AccountKey=fake",
    )
    return output_path


def _raise_role_assignment_denied(**_kwargs):
    raise RuntimeError("role assignment denied")


@pytest.mark.unit
def test_main_active_with_identity_writes_outputs_and_succeeds(monkeypatch, tmp_path):
    deploy_agent = _load_deploy_agent_module()
    output_path = _setup_main_env(monkeypatch, tmp_path)
    fake_client_cls, fake_agent = _make_main_test_client(deploy_agent)

    monkeypatch.setattr(deploy_agent, "AIProjectClient", fake_client_cls)
    monkeypatch.setattr(deploy_agent, "DefaultAzureCredential", lambda: object())
    monkeypatch.setattr(deploy_agent, "wait_for_agent_active", lambda *a, **kw: "active")
    monkeypatch.setattr(
        deploy_agent,
        "resolve_agent_identity_principal_id",
        lambda *a, **kw: ("principal-id-abc", "sdk"),
    )

    deploy_agent.main([])

    outputs = _read_github_output(output_path)
    assert outputs["agent_version"] == str(fake_agent.version)
    assert outputs["agent_active"] == "true"
    assert outputs["agent_identity_principal_id"] == "principal-id-abc"


@pytest.mark.unit
def test_main_active_without_identity_writes_outputs_and_succeeds(monkeypatch, tmp_path):
    deploy_agent = _load_deploy_agent_module()
    output_path = _setup_main_env(monkeypatch, tmp_path)
    fake_client_cls, fake_agent = _make_main_test_client(deploy_agent)

    monkeypatch.setattr(deploy_agent, "AIProjectClient", fake_client_cls)
    monkeypatch.setattr(deploy_agent, "DefaultAzureCredential", lambda: object())
    monkeypatch.setattr(deploy_agent, "wait_for_agent_active", lambda *a, **kw: "active")
    monkeypatch.setattr(
        deploy_agent, "resolve_agent_identity_principal_id", lambda *a, **kw: (None, "none")
    )

    deploy_agent.main([])

    outputs = _read_github_output(output_path)
    assert outputs["agent_version"] == str(fake_agent.version)
    assert outputs["agent_active"] == "true"
    assert outputs["agent_identity_principal_id"] == ""
    assert outputs["agent_identity_source"] == "none"


@pytest.mark.unit
def test_main_active_without_identity_fails_when_strict_rbac_required(monkeypatch, tmp_path):
    deploy_agent = _load_deploy_agent_module()
    output_path = _setup_main_env(monkeypatch, tmp_path)
    fake_client_cls, fake_agent = _make_main_test_client(deploy_agent)

    monkeypatch.setenv("REQUIRE_AGENT_IDENTITY_RBAC", "1")
    monkeypatch.setattr(deploy_agent, "AIProjectClient", fake_client_cls)
    monkeypatch.setattr(deploy_agent, "DefaultAzureCredential", lambda: object())
    monkeypatch.setattr(deploy_agent, "wait_for_agent_active", lambda *a, **kw: "active")
    monkeypatch.setattr(
        deploy_agent, "resolve_agent_identity_principal_id", lambda *a, **kw: (None, "none")
    )

    with pytest.raises(SystemExit) as excinfo:
        deploy_agent.main([])

    assert excinfo.value.code == 1
    outputs = _read_github_output(output_path)
    assert outputs["agent_version"] == str(fake_agent.version)
    assert outputs["agent_active"] == "true"
    assert outputs["agent_identity_principal_id"] == ""


@pytest.mark.unit
def test_main_active_rbac_assignment_failure_is_best_effort_by_default(monkeypatch, tmp_path):
    deploy_agent = _load_deploy_agent_module()
    output_path = _setup_main_env(monkeypatch, tmp_path)
    fake_client_cls, fake_agent = _make_main_test_client(deploy_agent)

    monkeypatch.setenv("AZURE_SUBSCRIPTION_ID", "sub-123")
    monkeypatch.setattr(deploy_agent, "AIProjectClient", fake_client_cls)
    monkeypatch.setattr(deploy_agent, "DefaultAzureCredential", lambda: object())
    monkeypatch.setattr(deploy_agent, "wait_for_agent_active", lambda *a, **kw: "active")
    monkeypatch.setattr(
        deploy_agent,
        "resolve_agent_identity_principal_id",
        lambda *a, **kw: ("principal-id-abc", "sdk"),
    )
    monkeypatch.setattr(
        deploy_agent,
        "assign_agent_identity_rbac",
        _raise_role_assignment_denied,
    )

    deploy_agent.main([])

    outputs = _read_github_output(output_path)
    assert outputs["agent_version"] == str(fake_agent.version)
    assert outputs["agent_active"] == "true"
    assert outputs["agent_identity_principal_id"] == "principal-id-abc"


@pytest.mark.unit
def test_main_active_rbac_assignment_failure_exits_when_strict(monkeypatch, tmp_path):
    deploy_agent = _load_deploy_agent_module()
    output_path = _setup_main_env(monkeypatch, tmp_path)
    fake_client_cls, fake_agent = _make_main_test_client(deploy_agent)

    monkeypatch.setenv("AZURE_SUBSCRIPTION_ID", "sub-123")
    monkeypatch.setenv("REQUIRE_AGENT_IDENTITY_RBAC", "1")
    monkeypatch.setattr(deploy_agent, "AIProjectClient", fake_client_cls)
    monkeypatch.setattr(deploy_agent, "DefaultAzureCredential", lambda: object())
    monkeypatch.setattr(deploy_agent, "wait_for_agent_active", lambda *a, **kw: "active")
    monkeypatch.setattr(
        deploy_agent,
        "resolve_agent_identity_principal_id",
        lambda *a, **kw: ("principal-id-abc", "sdk"),
    )
    monkeypatch.setattr(
        deploy_agent,
        "assign_agent_identity_rbac",
        _raise_role_assignment_denied,
    )

    with pytest.raises(SystemExit) as excinfo:
        deploy_agent.main([])

    assert excinfo.value.code == 1
    outputs = _read_github_output(output_path)
    assert outputs["agent_version"] == str(fake_agent.version)
    assert outputs["agent_active"] == "true"
    assert outputs["agent_identity_principal_id"] == "principal-id-abc"


@pytest.mark.unit
def test_main_failed_status_exits_one(monkeypatch, tmp_path):
    deploy_agent = _load_deploy_agent_module()
    output_path = _setup_main_env(monkeypatch, tmp_path)
    fake_client_cls, fake_agent = _make_main_test_client(deploy_agent)

    identity_calls: list[bool] = []

    def _identity(*_a, **_kw):
        identity_calls.append(True)
        return ("principal-id-should-not-appear", "sdk")

    monkeypatch.setattr(deploy_agent, "AIProjectClient", fake_client_cls)
    monkeypatch.setattr(deploy_agent, "DefaultAzureCredential", lambda: object())
    monkeypatch.setattr(deploy_agent, "wait_for_agent_active", lambda *a, **kw: "failed")
    monkeypatch.setattr(deploy_agent, "resolve_agent_identity_principal_id", _identity)

    with pytest.raises(SystemExit) as excinfo:
        deploy_agent.main([])

    assert excinfo.value.code == 1
    assert identity_calls == []  # Identity lookup must be skipped on failure.
    outputs = _read_github_output(output_path)
    assert outputs["agent_version"] == str(fake_agent.version)
    assert outputs["agent_active"] == "false"
    assert outputs["agent_identity_principal_id"] == ""


@pytest.mark.unit
def test_main_timeout_status_soft_exits_zero(monkeypatch, tmp_path):
    deploy_agent = _load_deploy_agent_module()
    output_path = _setup_main_env(monkeypatch, tmp_path)
    fake_client_cls, fake_agent = _make_main_test_client(deploy_agent)

    monkeypatch.setattr(deploy_agent, "AIProjectClient", fake_client_cls)
    monkeypatch.setattr(deploy_agent, "DefaultAzureCredential", lambda: object())
    monkeypatch.setattr(deploy_agent, "wait_for_agent_active", lambda *a, **kw: "timeout")
    monkeypatch.setattr(
        deploy_agent,
        "resolve_agent_identity_principal_id",
        lambda *a, **kw: pytest.fail("identity lookup must not run on timeout"),
    )

    with pytest.raises(SystemExit) as excinfo:
        deploy_agent.main([])

    assert excinfo.value.code == 0
    outputs = _read_github_output(output_path)
    assert outputs["agent_version"] == str(fake_agent.version)
    assert outputs["agent_active"] == "false"
    assert outputs["agent_identity_principal_id"] == ""


@pytest.mark.unit
def test_hosted_manifest_environment_names_match_deploy_contract():
    deploy_agent = _load_deploy_agent_module()
    manifest_path = Path(__file__).resolve().parents[1] / "agent" / "hosted" / "agent.yaml"
    lines = manifest_path.read_text(encoding="utf-8").splitlines()
    manifest_env_names = {
        line.split(":", 1)[1].strip() for line in lines if line.strip().startswith("- name:")
    }

    assert manifest_env_names >= deploy_agent.HOSTED_AGENT_ENV_CONTRACT
    assert not (manifest_env_names & {"FOUNDRY_PROJECT_ENDPOINT", "FOUNDRY_AGENT_NAME"})
    assert not (manifest_env_names & set(deploy_agent.LEGACY_SECRET_REFERENCE_ENV_KEYS))


@pytest.mark.unit
def test_hosted_manifest_resources_match_deploy_contract():
    deploy_agent = _load_deploy_agent_module()
    manifest = (Path(__file__).resolve().parents[1] / "agent" / "hosted" / "agent.yaml").read_text(
        encoding="utf-8"
    )
    script = _SCRIPT_PATH.read_text(encoding="utf-8")

    manifest_resource_block = re.search(
        r"^resources:\n\s+cpu:\s+\"?([^\"\s]+)\"?\n\s+memory:\s+\"?([^\"\s]+)\"?",
        manifest,
        re.MULTILINE,
    )
    assert manifest_resource_block, "Hosted agent manifest must declare CPU and memory"
    assert manifest_resource_block.group(1) == "2"
    assert manifest_resource_block.group(2) == "4Gi"

    assert 'cpu="2"' in script
    assert 'memory="4Gi"' in script
    assert deploy_agent is not None


@pytest.mark.unit
def test_hosted_dockerfile_healthcheck_uses_agentserver_readiness():
    dockerfile = (
        Path(__file__).resolve().parents[1] / "agent" / "hosted" / "Dockerfile"
    ).read_text(encoding="utf-8")

    assert "HEALTHCHECK" in dockerfile
    assert "/readiness" in dockerfile
    assert "/health" not in dockerfile


@pytest.mark.unit
def test_foundry_agent_inspection_redacts_sensitive_payload_fields():
    inspect_agent = _load_inspect_foundry_agent_module()
    payload = {
        "id": "qprisma-video-agent",
        "name": "qprisma-video-agent",
        "versions": {
            "latest": {
                "id": "qprisma-video-agent:80",
                "version": "80",
                "status": "active",
                "environment_variables": [
                    {"name": "NEO4J_PASSWORD", "value": "super-secret-password"},
                ],
            },
        },
        "instance_identity": {
            "principal_id": "11111111-2222-3333-4444-555555555555",
        },
        "connection_string": "AccountKey=very-secret",
    }

    summary = inspect_agent.summarize_agent_payload(payload)
    redacted = inspect_agent.redact(payload)

    assert summary["latest_version"] == {
        "id": "qprisma-video-agent:80",
        "version": "80",
        "status": "active",
    }
    assert summary["identity"]["presence"] == "present"
    assert "super-secret-password" not in str(summary)
    assert "super-secret-password" not in str(redacted)
    assert "AccountKey=very-secret" not in str(redacted)
    assert redacted["versions"]["latest"]["environment_variables"] == "***REDACTED***"


@pytest.mark.unit
def test_foundry_agent_inspection_minimal_metadata_parser():
    inspect_agent = _load_inspect_foundry_agent_module()
    metadata = inspect_agent._load_minimal_metadata(
        """
defaultEnvironment: dev
environments:
  dev:
    projectEndpoint: https://aif-qprisma-dev.services.ai.azure.com/api/projects/aif-qprisma-dev-project
    agentName: qprisma-video-agent
"""
    )

    endpoint, agent_name = inspect_agent._resolve_from_metadata(metadata, None)

    assert (
        endpoint
        == "https://aif-qprisma-dev.services.ai.azure.com/api/projects/aif-qprisma-dev-project"
    )
    assert agent_name == "qprisma-video-agent"
