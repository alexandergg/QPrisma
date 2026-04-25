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

    class DummyImageBasedHostedAgentDefinition:
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
    azure_projects_models_module.ImageBasedHostedAgentDefinition = (
        DummyImageBasedHostedAgentDefinition
    )
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


@pytest.mark.unit
def test_build_environment_variables_defaults_to_secretless_hosted_contract():
    deploy_agent = _load_deploy_agent_module()
    env_vars = deploy_agent.build_environment_variables(env={})

    assert env_vars["ENVIRONMENT"] == "hosted"
    assert env_vars["AZURE_OPENAI_ENDPOINT"] == "https://aif-qprisma-dev.openai.azure.com/"
    assert env_vars["AZURE_OPENAI_API_VERSION"] == "2024-08-01-preview"
    assert env_vars["AZURE_OPENAI_DEPLOYMENT_GPT"] == "gpt-4o"
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
def test_hosted_agent_openai_rbac_is_durable_and_bootstrapped():
    ai_foundry_bicep = (_REPO_ROOT / "infra" / "modules" / "ai-foundry.bicep").read_text(
        encoding="utf-8"
    )
    hosted_workflow = (_REPO_ROOT / ".github" / "workflows" / "deploy-hosted-agent.yml").read_text(
        encoding="utf-8"
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
    assert _OPENAI_USER_ROLE_ID in hosted_workflow
    assert "Cognitive Services OpenAI User" in hosted_workflow
