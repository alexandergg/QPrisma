"""Tests for hosted agent deployment environment wiring."""

import importlib.util
import re
import sys
import types
from pathlib import Path
from unittest.mock import patch

import pytest

_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "deploy_agent.py"
_REPO_ROOT = Path(__file__).resolve().parents[2]
_OPENAI_USER_ROLE_ID = "5e0bd9bd-7b93-4f28-af87-19fc36ad61bd"
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
    assert env_vars["AZURE_OPENAI_DEPLOYMENT_GPT"] == "gpt-5.4-pro"
    assert env_vars["AZURE_OPENAI_DEPLOYMENT_EMBEDDING"] == "text-embedding-3-large"
    assert env_vars["AZURE_USE_MANAGED_IDENTITY"] == "true"


@pytest.mark.unit
def test_build_environment_variables_preserves_explicit_openai_overrides():
    deploy_agent = _load_deploy_agent_module()
    env_vars = deploy_agent.build_environment_variables(
        env={
            "AZURE_OPENAI_ENDPOINT": "https://custom.openai.azure.com/",
            "AZURE_OPENAI_API_VERSION": "2025-01-01-preview",
            "AZURE_OPENAI_DEPLOYMENT_GPT": "gpt-4.1",
            "AZURE_OPENAI_DEPLOYMENT_EMBEDDING": "text-embedding-3-small",
            "AZURE_USE_MANAGED_IDENTITY": "false",
            "NEO4J_URI": "neo4j+s://example.databases.neo4j.io",
        }
    )

    assert env_vars["AZURE_OPENAI_ENDPOINT"] == "https://custom.openai.azure.com/"
    assert env_vars["AZURE_OPENAI_API_VERSION"] == "2025-01-01-preview"
    assert env_vars["AZURE_OPENAI_DEPLOYMENT_GPT"] == "gpt-4.1"
    assert env_vars["AZURE_OPENAI_DEPLOYMENT_EMBEDDING"] == "text-embedding-3-small"
    assert env_vars["AZURE_USE_MANAGED_IDENTITY"] == "false"
    assert env_vars["NEO4J_URI"] == "neo4j+s://example.databases.neo4j.io"


@pytest.mark.unit
def test_build_environment_variables_accepts_memory_contract_aliases():
    deploy_agent = _load_deploy_agent_module()
    env_vars = deploy_agent.build_environment_variables(
        env={
            "FOUNDRY_MEMORY_STORE_NAME": "qprisma-memory",
            "FOUNDRY_MEMORY_CHAT_MODEL": "gpt-5.4-pro",
            "FOUNDRY_MEMORY_EMBEDDING_MODEL": "text-embedding-3-large",
        }
    )

    assert env_vars["MEMORY_STORE_NAME"] == "qprisma-memory"
    assert env_vars["MEMORY_CHAT_MODEL"] == "gpt-5.4-pro"
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
            assert lines[index + 1].strip() == f'value: "{default_api_version}"'
            break
    else:
        pytest.fail("AZURE_OPENAI_API_VERSION missing from hosted agent manifest")


@pytest.mark.unit
def test_hosted_manifest_chat_model_matches_provisioned_infra_default():
    manifest = (_REPO_ROOT / "backend" / "agent" / "hosted" / "agent.yaml").read_text(
        encoding="utf-8"
    )
    infra_main = (_REPO_ROOT / "infra" / "main.bicep").read_text(encoding="utf-8")

    assert "id: gpt-5.4-pro" in manifest
    assert "name: chat" in manifest
    assert "{ name: 'AZURE_OPENAI_DEPLOYMENT_GPT', value: 'gpt-5.4-pro' }" in infra_main


@pytest.mark.unit
def test_deploy_hosted_agent_workflow_defaults_match_provisioned_chat_models():
    hosted_workflow = (_REPO_ROOT / ".github" / "workflows" / "deploy-hosted-agent.yml").read_text(
        encoding="utf-8"
    )
    register_step = _workflow_step_block(hosted_workflow, "Register agent in Foundry")

    assert (
        "AZURE_OPENAI_DEPLOYMENT_GPT: ${{ inputs.chat_deployment "
        "|| vars.AZURE_OPENAI_DEPLOYMENT_GPT || 'gpt-5.4-pro' }}" in register_step
    )
    assert "MEMORY_CHAT_MODEL: ${{ vars.MEMORY_CHAT_MODEL || 'gpt-4o' }}" in register_step


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
    hosted_openai_step = _workflow_step_block(
        hosted_workflow, "Ensure hosted agent instance identity has Azure OpenAI access"
    )
    ai_foundry_openai_role = _resource_block(ai_foundry_bicep, "openAiRoleAiFoundry")
    project_openai_role = _resource_block(ai_foundry_bicep, "openAiRoleProject")

    assert f"var cognitiveServicesOpenAiUserRole = '{_OPENAI_USER_ROLE_ID}'" in ai_foundry_bicep
    assert "scope: aiFoundry" in ai_foundry_openai_role
    assert _OPENAI_ROLE_DEFINITION_ID in ai_foundry_openai_role
    assert "principalId: aiFoundry.identity.principalId" in ai_foundry_openai_role
    assert "scope: aiFoundry" in project_openai_role
    assert _OPENAI_ROLE_DEFINITION_ID in project_openai_role
    assert "principalId: aiProject.identity.principalId" in project_openai_role
    assert _OPENAI_USER_ROLE_ID in hosted_openai_step
    assert "Cognitive Services OpenAI User" in hosted_openai_step
    assert "'infra/modules/ai-foundry.bicep'" in hosted_workflow
    assert (
        "AGENT_IDENTITY_PID: ${{ steps.register.outputs.agent_identity_principal_id }}"
        in hosted_openai_step
    )
    assert '--assignee-object-id "$AGENT_IDENTITY_PID"' in hosted_openai_step
    assert "az ad sp list" not in hosted_workflow
    assert "Ensure hosted AgentIdentity has Azure OpenAI access" not in ai_foundry_workflow
    assert "az ad sp list" not in ai_foundry_workflow
    assert 'pip install "azure-ai-projects==2.1.0"' in hosted_workflow
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
    return output_path


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
def test_main_active_without_identity_exits_one(monkeypatch, tmp_path):
    deploy_agent = _load_deploy_agent_module()
    output_path = _setup_main_env(monkeypatch, tmp_path)
    fake_client_cls, fake_agent = _make_main_test_client(deploy_agent)

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
