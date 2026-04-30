from __future__ import annotations

import json
import sys
import types
from enum import Enum

import httpx
import pytest

import evaluation_foundry.redteam_eval as redteam_eval_module
from evaluation_foundry.redteam_eval import (
    _build_enabled_taxonomy_update,
    _build_retry_taxonomy_update_body,
    _count_enabled_subcategories,
    _extract_run_diagnostics,
    _extract_run_status,
    _extract_taxonomy_update_identifiers,
    _extract_total_results,
    _http_response_target_matches,
    _map_enum_member,
    _normalize_attack_strategy,
    _normalize_risk_category,
    _patch_taxonomy_via_rest,
    _split_agent_reference,
    _write_redteam_artifacts,
    run_redteam_scan,
)


class LowercaseStrategy(Enum):
    base64 = "base64"
    flip = "flip"
    morse = "morse"


class UppercaseRisk(Enum):
    VIOLENCE = "violence"
    SELF_HARM = "self_harm"


@pytest.mark.parametrize(
    ("enum_cls", "token", "expected"),
    [
        (LowercaseStrategy, "base64", LowercaseStrategy.base64),
        (LowercaseStrategy, "BASE64", LowercaseStrategy.base64),
        (LowercaseStrategy, " flip ", LowercaseStrategy.flip),
        (UppercaseRisk, "violence", UppercaseRisk.VIOLENCE),
        (UppercaseRisk, "SELF_HARM", UppercaseRisk.SELF_HARM),
    ],
)
def test_map_enum_member_accepts_case_insensitive_names_and_values(
    enum_cls: type[Enum], token: str, expected: Enum
):
    assert _map_enum_member(enum_cls, token) is expected


def test_map_enum_member_lists_valid_values_on_unknown_token():
    with pytest.raises(ValueError, match="Valid values: base64, flip, morse"):
        _map_enum_member(LowercaseStrategy, "unknown")


@pytest.mark.parametrize(
    ("token", "expected"),
    [
        ("base64", "Base64"),
        ("flip", "Flip"),
        ("indirect_jailbreak", "IndirectJailbreak"),
        ("ROT13", "ROT13"),
        ("character-space", "CharacterSpace"),
    ],
)
def test_normalize_attack_strategy(token: str, expected: str):
    assert _normalize_attack_strategy(token) == expected


def test_normalize_risk_category_rejects_unsupported_cloud_taxonomy():
    with pytest.raises(ValueError, match="prohibited_actions taxonomy only"):
        _normalize_risk_category("violence")


@pytest.mark.parametrize(
    ("agent_id", "expected_name", "expected_version"),
    [
        ("qprisma-video-agent:7", "qprisma-video-agent", "7"),
        ("qprisma-video-agent", "qprisma-video-agent", None),
    ],
)
def test_split_agent_reference(agent_id: str, expected_name: str, expected_version: str | None):
    assert _split_agent_reference(agent_id) == (expected_name, expected_version)


def test_build_enabled_taxonomy_update_enables_generated_subcategories():
    taxonomy = {
        "description": "taxonomy",
        "taxonomyInput": {"type": "agent"},
        "taxonomyCategories": [
            {
                "id": "cat-1",
                "name": "category",
                "subCategories": [
                    {"id": "sub-1", "name": "disabled", "enabled": False},
                    {"id": "sub-2", "name": "already-enabled", "enabled": True},
                ],
            }
        ],
    }

    body, changed, supported = _build_enabled_taxonomy_update(taxonomy)

    assert supported is True
    assert changed is True
    assert body["taxonomyInput"] == {"type": "agent"}
    assert body["description"] == "taxonomy"
    assert body["taxonomyCategories"][0]["subCategories"] == [
        {"id": "sub-1", "name": "disabled", "enabled": True},
        {"id": "sub-2", "name": "already-enabled", "enabled": True},
    ]


def test_build_enabled_taxonomy_update_returns_unchanged_when_all_enabled():
    taxonomy = {
        "description": "taxonomy",
        "taxonomyInput": {"type": "agent"},
        "taxonomyCategories": [
            {
                "id": "cat-1",
                "subCategories": [{"id": "sub-1", "enabled": True}],
            }
        ],
    }

    body, changed, supported = _build_enabled_taxonomy_update(taxonomy)

    assert supported is True
    assert changed is False
    assert body["taxonomyInput"] == {"type": "agent"}


def test_build_enabled_taxonomy_update_preserves_optional_fields():
    taxonomy = {
        "description": "desc",
        "taxonomyInput": {"type": "agent"},
        "properties": {"foo": "bar"},
        "tags": ["a", "b"],
        "taxonomyCategories": [
            {"id": "cat-1", "subCategories": [{"id": "sub-1", "enabled": False}]}
        ],
    }

    body, changed, supported = _build_enabled_taxonomy_update(taxonomy)

    assert supported is True
    assert changed is True
    assert body["taxonomyInput"] == {"type": "agent"}
    assert body["properties"] == {"foo": "bar"}
    assert body["tags"] == ["a", "b"]


def test_build_enabled_taxonomy_update_rejects_unexpected_payload_shape():
    body, changed, supported = _build_enabled_taxonomy_update({"taxonomyInput": {"type": "agent"}})

    assert body == {}
    assert changed is False
    assert supported is False


def test_build_retry_taxonomy_update_body_preserves_full_input_metadata():
    taxonomy = {
        "taxonomyInput": {
            "type": "agent",
            "riskCategories": ["ProhibitedActions"],
            "target": {"type": "azure_ai_agent", "name": "qprisma-video-agent", "version": "54"},
        },
        "taxonomyCategories": [
            {"id": "cat-1", "subCategories": [{"id": "sub-1", "enabled": True}]}
        ],
    }
    base_body = {
        "taxonomyCategories": taxonomy["taxonomyCategories"],
        "taxonomyInput": {"type": "agent"},
    }

    retry_body = _build_retry_taxonomy_update_body(taxonomy, base_body)

    assert retry_body["taxonomyInput"] == taxonomy["taxonomyInput"]


def test_extract_taxonomy_update_identifiers_prefers_returned_values():
    taxonomy = {
        "name": "returned-taxonomy-name",
        "id": "taxonomy-asset-id",
    }

    assert _extract_taxonomy_update_identifiers(taxonomy, "requested-name") == [
        "returned-taxonomy-name",
        "taxonomy-asset-id",
        "requested-name",
    ]


def test_extract_run_helpers_support_dicts_and_models():
    class FakeRunModel:
        def model_dump(self, mode: str = "json") -> dict[str, object]:
            return {"status": "completed", "result_counts": {"total": 4}}

    assert _extract_run_status(FakeRunModel()) == "completed"
    assert _extract_total_results(FakeRunModel()) == 4
    assert _extract_run_status({"status": "failed"}) == "failed"
    assert _extract_total_results({"resultCounts": {"total": 2}}) == 2


def test_extract_total_results_falls_back_to_per_criteria():
    run = {
        "result_counts": {"total": 0},
        "per_testing_criteria_results": [
            {"testing_criteria": "Prohibited Actions", "passed": 3, "failed": 1},
            {"testing_criteria": "Task Adherence", "passed": 2, "failed": 0},
        ],
    }

    assert _extract_total_results(run) == 4


def test_extract_total_results_falls_back_to_output_items_in_summary():
    summary = {
        "run": {"result_counts": {"total": 0}},
        "output_items": [{"item_id": "a"}, {"item_id": "b"}, {"item_id": "c"}],
    }

    assert _extract_total_results(summary) == 3


def test_extract_total_results_returns_zero_when_no_signals():
    assert _extract_total_results({"run": {}, "output_items": []}) == 0
    assert _extract_total_results({}) == 0
    assert _extract_total_results(None) == 0


def test_extract_run_diagnostics_captures_common_error_fields():
    class FakeRunModel:
        def model_dump(self, mode: str = "json") -> dict[str, object]:
            return {
                "status": "failed",
                "last_error": {"code": "BadRequest", "message": "invalid target"},
                "failureReason": "unsupported-region",
                "statusDetails": {"phase": "item_generation"},
                "ignored": "not copied",
            }

    diagnostics = _extract_run_diagnostics(FakeRunModel())

    assert diagnostics == {
        "status": "failed",
        "last_error": {"code": "BadRequest", "message": "invalid target"},
        "failureReason": "unsupported-region",
        "statusDetails": {"phase": "item_generation"},
    }


def test_write_redteam_artifacts_persists_summary_request_shape_and_jsonl(tmp_path):
    output_path = tmp_path / "redteam-results.json"
    summary = {
        "status": "completed",
        "request_shape": {"eval_id": "eval-1"},
        "output_items": [{"id": "item-1"}, {"id": "item-2"}],
    }

    _write_redteam_artifacts(output_path, summary)

    saved_summary = json.loads(output_path.read_text(encoding="utf-8"))
    request_shape_path = tmp_path / "redteam-results-request-shape.json"
    output_items_path = tmp_path / "redteam-results-output-items.jsonl"

    assert saved_summary["artifact_paths"] == {
        "summary": str(output_path),
        "request_shape": str(request_shape_path),
        "output_items": str(output_items_path),
    }
    assert json.loads(request_shape_path.read_text(encoding="utf-8")) == {"eval_id": "eval-1"}
    assert output_items_path.read_text(encoding="utf-8").splitlines() == [
        '{"id": "item-1"}',
        '{"id": "item-2"}',
    ]


def test_patch_taxonomy_via_rest_wraps_request_errors(monkeypatch: pytest.MonkeyPatch):
    class FakeCredential:
        def get_token(self, scope: str):
            assert scope == "https://ai.azure.com/.default"
            return types.SimpleNamespace(token="token")

    def fake_patch(*args, **kwargs):
        request = httpx.Request("PATCH", args[0])
        raise httpx.ConnectError("connection dropped", request=request)

    monkeypatch.setattr(redteam_eval_module.httpx, "patch", fake_patch)

    with pytest.raises(
        RuntimeError,
        match=(
            "Foundry REST taxonomy PATCH failed for 'demo-taxonomy' at "
            "'https://example.services.ai.azure.com/api/projects/demo/evaluationtaxonomies/"
            "demo-taxonomy\\?api-version=v1': connection dropped"
        ),
    ):
        _patch_taxonomy_via_rest(
            credential=FakeCredential(),
            endpoint="https://example.services.ai.azure.com/api/projects/demo",
            taxonomy_name="demo-taxonomy",
            body={"taxonomyCategories": []},
        )


def test_http_response_target_matches_sdk_and_rest_error_shapes():
    assert _http_response_target_matches(
        RuntimeError("Target: taxonomyId"),
        "taxonomyId",
    )
    assert _http_response_target_matches(
        RuntimeError('{"error": {"target": "taxonomyInput"}}'),
        "taxonomyInput",
    )
    assert not _http_response_target_matches(
        RuntimeError('{"error": {"target": "taxonomyId"}}'),
        "taxonomyInput",
    )


def test_patch_taxonomy_via_rest_retries_preview_version_for_taxonomy_id_rejection(
    monkeypatch: pytest.MonkeyPatch,
):
    calls: list[dict[str, object]] = []

    class FakeCredential:
        def get_token(self, scope: str):
            assert scope == "https://ai.azure.com/.default"
            return types.SimpleNamespace(token="token")

    def fake_patch(*args, **kwargs):
        url = args[0]
        calls.append({"url": url, "kwargs": kwargs})
        request = httpx.Request("PATCH", url)
        if "api-version=v1" in url:
            response = httpx.Response(
                400,
                request=request,
                json={
                    "error": {
                        "target": "taxonomyId",
                        "message": "{argumentName} is invalid",
                    }
                },
            )
            raise httpx.HTTPStatusError(
                "taxonomy id rejected",
                request=request,
                response=response,
            )
        return httpx.Response(200, request=request, json={})

    monkeypatch.setattr(redteam_eval_module.httpx, "patch", fake_patch)

    _patch_taxonomy_via_rest(
        credential=FakeCredential(),
        endpoint="https://example.services.ai.azure.com/api/projects/demo/",
        taxonomy_name=(
            "azureai://accounts/demo/projects/project/evaluationtaxonomies/taxonomy/versions/1.0"
        ),
        body={"taxonomyCategories": []},
    )

    assert [call["url"] for call in calls] == [
        "https://example.services.ai.azure.com/api/projects/demo/evaluationtaxonomies/"
        "azureai%3A%2F%2Faccounts%2Fdemo%2Fprojects%2Fproject%2Fevaluationtaxonomies%2Ftaxonomy%2Fversions%2F1.0"
        "?api-version=v1",
        "https://example.services.ai.azure.com/api/projects/demo/evaluationtaxonomies/"
        "azureai%3A%2F%2Faccounts%2Fdemo%2Fprojects%2Fproject%2Fevaluationtaxonomies%2Ftaxonomy%2Fversions%2F1.0"
        "?api-version=2025-11-15-preview",
    ]
    assert calls[0]["kwargs"]["headers"]["Foundry-Features"] == "Evaluations=V1Preview"


def test_run_redteam_scan_uses_cloud_foundry_agent_flow(monkeypatch: pytest.MonkeyPatch, tmp_path):
    calls: dict[str, object] = {}

    class FakeCredential:
        def close(self):
            calls["credential_closed"] = True

    class FakeHttpResponseError(Exception):
        pass

    class FakeRiskCategory(Enum):
        PROHIBITED_ACTIONS = "ProhibitedActions"

    class FakeAzureAIAgentTarget:
        def __init__(self, *, name: str, version: str):
            self.name = name
            self.version = version

        def as_dict(self) -> dict[str, str]:
            return {
                "type": "azure_ai_agent",
                "name": self.name,
                "version": self.version,
            }

    class FakeAgentTaxonomyInput:
        def __init__(
            self, *, risk_categories: list[FakeRiskCategory], target: FakeAzureAIAgentTarget
        ):
            self.risk_categories = risk_categories
            self.target = target

    class FakeEvaluationTaxonomy:
        def __init__(self, *, description: str, taxonomy_input: FakeAgentTaxonomyInput):
            self.description = description
            self.taxonomy_input = taxonomy_input

    class FakeResource:
        def __init__(self, resource_id: str, status: str = "queued"):
            self.id = resource_id
            self.status = status

        def model_dump(self, mode: str = "json") -> dict[str, object]:
            return {
                "id": self.id,
                "status": self.status,
                "result_counts": {"total": 1 if self.status == "completed" else 0},
            }

    class FakeTaxonomy(FakeResource):
        def __init__(self, resource_id: str, subcategory_enabled: bool):
            super().__init__(resource_id, "completed")
            self.subcategory_enabled = subcategory_enabled

        def as_dict(self) -> dict[str, object]:
            return {
                "id": self.id,
                "name": "foundry-generated-taxonomy",
                "description": "taxonomy",
                "taxonomyInput": {"type": "agent"},
                "taxonomyCategories": [
                    {
                        "id": "cat-1",
                        "name": "category",
                        "subCategories": [
                            {
                                "id": "sub-1",
                                "name": "disabled-until-confirmed",
                                "enabled": self.subcategory_enabled,
                            }
                        ],
                    }
                ],
            }

    class FakeOutputItem:
        def __init__(self, item_id: str):
            self.item_id = item_id

        def as_dict(self) -> dict[str, str]:
            return {"item_id": self.item_id}

    class FakeOutputItemsClient:
        def list(self, *, run_id: str, eval_id: str):
            calls["output_items_list"] = {"run_id": run_id, "eval_id": eval_id}
            return [FakeOutputItem("item-1")]

    class FakeRunsClient:
        def __init__(self):
            self.output_items = FakeOutputItemsClient()

        def create(self, *, eval_id: str, name: str, data_source: dict[str, object]):
            calls["run_create"] = {"eval_id": eval_id, "name": name, "data_source": data_source}
            return FakeResource("run-1", "queued")

        def retrieve(self, *, run_id: str, eval_id: str):
            calls.setdefault("run_retrieve_calls", 0)
            calls["run_retrieve_calls"] = int(calls["run_retrieve_calls"]) + 1
            return FakeResource(run_id, "completed")

    class FakeEvalsClient:
        def __init__(self):
            self.runs = FakeRunsClient()

        def create(
            self, *, name: str, data_source_config: dict[str, str], testing_criteria: list[dict]
        ):
            calls["eval_create"] = {
                "name": name,
                "data_source_config": data_source_config,
                "testing_criteria": testing_criteria,
            }
            return FakeResource("eval-1", "created")

    class FakeOpenAIClient:
        def __init__(self):
            self.evals = FakeEvalsClient()

        def close(self):
            calls["openai_closed"] = True

    class FakeEvaluationTaxonomiesClient:
        def __init__(self):
            self.create_calls = 0
            self.update_calls = 0

        def create(self, *, name: str, body: FakeEvaluationTaxonomy | dict[str, object]):
            self.create_calls += 1
            if isinstance(body, dict):
                raise FakeHttpResponseError("Taxonomy input is required is invalid")
            calls.setdefault("taxonomy_create_calls", []).append({"name": name, "body": body})
            return FakeTaxonomy("taxonomy-1", subcategory_enabled=False)

        def update(self, *, name: str, body: dict[str, object]):
            self.update_calls += 1
            calls.setdefault("taxonomy_update_calls", []).append({"name": name, "body": body})
            return FakeTaxonomy("taxonomy-1", subcategory_enabled=True)

    class FakeBetaClient:
        def __init__(self):
            self.evaluation_taxonomies = FakeEvaluationTaxonomiesClient()

    class FakeAgentsClient:
        def get(self, *, agent_name: str):
            calls["agents_get"] = agent_name
            return types.SimpleNamespace(version="99")

    class FakeProjectClient:
        def __init__(self, *, endpoint: str, credential: FakeCredential, allow_preview: bool):
            calls["project_init"] = {
                "endpoint": endpoint,
                "allow_preview": allow_preview,
                "credential_type": type(credential).__name__,
            }
            self.beta = FakeBetaClient()
            self.agents = FakeAgentsClient()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def get_openai_client(self):
            return FakeOpenAIClient()

    azure_module = types.ModuleType("azure")
    azure_ai_module = types.ModuleType("azure.ai")
    projects_module = types.ModuleType("azure.ai.projects")
    projects_models_module = types.ModuleType("azure.ai.projects.models")
    azure_core_module = types.ModuleType("azure.core")
    azure_core_exceptions_module = types.ModuleType("azure.core.exceptions")
    azure_identity_module = types.ModuleType("azure.identity")

    projects_module.AIProjectClient = FakeProjectClient
    projects_models_module.AgentTaxonomyInput = FakeAgentTaxonomyInput
    projects_models_module.AzureAIAgentTarget = FakeAzureAIAgentTarget
    projects_models_module.EvaluationTaxonomy = FakeEvaluationTaxonomy
    projects_models_module.RiskCategory = FakeRiskCategory
    azure_core_exceptions_module.HttpResponseError = FakeHttpResponseError
    azure_identity_module.DefaultAzureCredential = FakeCredential

    monkeypatch.setitem(sys.modules, "azure", azure_module)
    monkeypatch.setitem(sys.modules, "azure.ai", azure_ai_module)
    monkeypatch.setitem(sys.modules, "azure.ai.projects", projects_module)
    monkeypatch.setitem(sys.modules, "azure.ai.projects.models", projects_models_module)
    monkeypatch.setitem(sys.modules, "azure.core", azure_core_module)
    monkeypatch.setitem(sys.modules, "azure.core.exceptions", azure_core_exceptions_module)
    monkeypatch.setitem(sys.modules, "azure.identity", azure_identity_module)

    output_path = tmp_path / "redteam-results.json"
    summary = run_redteam_scan(
        endpoint="https://example.services.ai.azure.com/api/projects/demo",
        agent_id="qprisma-video-agent:7",
        agent_name=None,
        agent_version=None,
        model_deployment="gpt-4o",
        strategies=["base64", "flip"],
        risk_categories=["prohibited_actions"],
        num_turns=3,
        output_path=output_path,
        scan_name="qprisma-redteam",
        poll_interval_seconds=0,
        timeout_seconds=5,
    )

    assert summary["mode"] == "cloud_foundry_agent_redteam"
    assert summary["agent"] == {"name": "qprisma-video-agent", "version": "7"}
    assert output_path.exists()
    assert json.loads(output_path.read_text(encoding="utf-8"))["run"]["status"] == "completed"

    eval_create = calls["eval_create"]
    assert eval_create["data_source_config"] == {"type": "azure_ai_source", "scenario": "red_team"}
    assert eval_create["testing_criteria"][1]["initialization_parameters"] == {
        "deployment_name": "gpt-4o"
    }

    taxonomy_create_calls = calls["taxonomy_create_calls"]
    initial_taxonomy = taxonomy_create_calls[0]
    assert initial_taxonomy["name"] == "qprisma-video-agent-prohibited-actions"
    assert initial_taxonomy["body"].taxonomy_input.target.name == "qprisma-video-agent"
    assert initial_taxonomy["body"].taxonomy_input.target.version == "7"
    assert initial_taxonomy["body"].taxonomy_input.risk_categories == [
        FakeRiskCategory.PROHIBITED_ACTIONS
    ]
    assert len(taxonomy_create_calls) == 1
    taxonomy_update_calls = calls["taxonomy_update_calls"]
    updated_taxonomy = taxonomy_update_calls[0]
    assert updated_taxonomy["name"] == "foundry-generated-taxonomy"
    assert updated_taxonomy["body"]["taxonomyCategories"][0]["subCategories"][0]["enabled"] is True
    assert updated_taxonomy["body"]["taxonomyInput"] == {"type": "agent"}

    run_create = calls["run_create"]
    assert run_create["data_source"]["item_generation_params"]["attack_strategies"] == [
        "Base64",
        "Flip",
    ]
    assert run_create["data_source"]["item_generation_params"]["source"] == {
        "type": "file_id",
        "id": "taxonomy-1",
    }
    assert run_create["data_source"]["target"] == {
        "type": "azure_ai_agent",
        "name": "qprisma-video-agent",
        "version": "7",
    }
    assert "agents_get" not in calls


def test_run_redteam_scan_falls_back_to_rest_patch_when_sdk_update_identifiers_fail(
    monkeypatch: pytest.MonkeyPatch, tmp_path
):
    calls: dict[str, object] = {}

    class FakeCredential:
        def close(self):
            calls["credential_closed"] = True

    class FakeHttpResponseError(Exception):
        pass

    class FakeRiskCategory(Enum):
        PROHIBITED_ACTIONS = "ProhibitedActions"

    class FakeAzureAIAgentTarget:
        def __init__(self, *, name: str, version: str):
            self.name = name
            self.version = version

        def as_dict(self) -> dict[str, str]:
            return {
                "type": "azure_ai_agent",
                "name": self.name,
                "version": self.version,
            }

    class FakeAgentTaxonomyInput:
        def __init__(
            self, *, risk_categories: list[FakeRiskCategory], target: FakeAzureAIAgentTarget
        ):
            self.risk_categories = risk_categories
            self.target = target

    class FakeEvaluationTaxonomy:
        def __init__(self, *, description: str, taxonomy_input: FakeAgentTaxonomyInput):
            self.description = description
            self.taxonomy_input = taxonomy_input

    class FakeResource:
        def __init__(self, resource_id: str, status: str = "queued"):
            self.id = resource_id
            self.status = status

        def model_dump(self, mode: str = "json") -> dict[str, object]:
            return {
                "id": self.id,
                "status": self.status,
                "result_counts": {"total": 1 if self.status == "completed" else 0},
            }

    class FakeTaxonomy(FakeResource):
        def __init__(self, resource_id: str, subcategory_enabled: bool):
            super().__init__(resource_id, "completed")
            self.subcategory_enabled = subcategory_enabled

        def as_dict(self) -> dict[str, object]:
            return {
                "id": self.id,
                "name": "foundry-generated-taxonomy",
                "description": "taxonomy",
                "taxonomyInput": {"type": "agent"},
                "taxonomyCategories": [
                    {
                        "id": "cat-1",
                        "subCategories": [{"id": "sub-1", "enabled": self.subcategory_enabled}],
                    }
                ],
            }

    class FakeOutputItem:
        def __init__(self, item_id: str):
            self.item_id = item_id

        def as_dict(self) -> dict[str, str]:
            return {"item_id": self.item_id}

    class FakeOutputItemsClient:
        def list(self, *, run_id: str, eval_id: str):
            return [FakeOutputItem("item-1")]

    class FakeRunsClient:
        def __init__(self):
            self.output_items = FakeOutputItemsClient()

        def create(self, *, eval_id: str, name: str, data_source: dict[str, object]):
            calls["run_create"] = {"eval_id": eval_id, "name": name, "data_source": data_source}
            return FakeResource("run-1", "queued")

        def retrieve(self, *, run_id: str, eval_id: str):
            return FakeResource(run_id, "completed")

    class FakeEvalsClient:
        def __init__(self):
            self.runs = FakeRunsClient()

        def create(
            self, *, name: str, data_source_config: dict[str, str], testing_criteria: list[dict]
        ):
            return FakeResource("eval-1", "created")

    class FakeOpenAIClient:
        def __init__(self):
            self.evals = FakeEvalsClient()

        def close(self):
            calls["openai_closed"] = True

    class FakeEvaluationTaxonomiesClient:
        def create(self, *, name: str, body: FakeEvaluationTaxonomy | dict[str, object]):
            calls.setdefault("taxonomy_create_calls", []).append({"name": name, "body": body})
            return FakeTaxonomy("taxonomy-asset-id", subcategory_enabled=False)

        def update(self, *, name: str, body: dict[str, object]):
            calls.setdefault("taxonomy_update_calls", []).append({"name": name, "body": body})
            if name == "foundry-generated-taxonomy":
                raise FakeHttpResponseError(
                    "(UserError) {argumentName} is invalid\n"
                    "Code: UserError\n"
                    "Message: {argumentName} is invalid\n"
                    "Target: taxonomyId"
                )
            raise FakeHttpResponseError("Operation returned an invalid status 'Not Found'")

        def get(self, *, name: str):
            calls.setdefault("taxonomy_get_calls", []).append(name)
            assert name == "qprisma-video-agent-prohibited-actions"
            return FakeTaxonomy("taxonomy-asset-id", subcategory_enabled=True)

    class FakeBetaClient:
        def __init__(self):
            self.evaluation_taxonomies = FakeEvaluationTaxonomiesClient()

    class FakeProjectClient:
        def __init__(self, *, endpoint: str, credential: FakeCredential, allow_preview: bool):
            self.beta = FakeBetaClient()
            self.agents = types.SimpleNamespace()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def get_openai_client(self):
            return FakeOpenAIClient()

    azure_module = types.ModuleType("azure")
    azure_ai_module = types.ModuleType("azure.ai")
    projects_module = types.ModuleType("azure.ai.projects")
    projects_models_module = types.ModuleType("azure.ai.projects.models")
    azure_core_module = types.ModuleType("azure.core")
    azure_core_exceptions_module = types.ModuleType("azure.core.exceptions")
    azure_identity_module = types.ModuleType("azure.identity")

    projects_module.AIProjectClient = FakeProjectClient
    projects_models_module.AgentTaxonomyInput = FakeAgentTaxonomyInput
    projects_models_module.AzureAIAgentTarget = FakeAzureAIAgentTarget
    projects_models_module.EvaluationTaxonomy = FakeEvaluationTaxonomy
    projects_models_module.RiskCategory = FakeRiskCategory
    azure_core_exceptions_module.HttpResponseError = FakeHttpResponseError
    azure_identity_module.DefaultAzureCredential = FakeCredential

    monkeypatch.setitem(sys.modules, "azure", azure_module)
    monkeypatch.setitem(sys.modules, "azure.ai", azure_ai_module)
    monkeypatch.setitem(sys.modules, "azure.ai.projects", projects_module)
    monkeypatch.setitem(sys.modules, "azure.ai.projects.models", projects_models_module)
    monkeypatch.setitem(sys.modules, "azure.core", azure_core_module)
    monkeypatch.setitem(sys.modules, "azure.core.exceptions", azure_core_exceptions_module)
    monkeypatch.setitem(sys.modules, "azure.identity", azure_identity_module)

    def fake_rest_patch(*, credential, endpoint: str, taxonomy_name: str, body: dict[str, object]):
        calls.setdefault("rest_patch_calls", []).append(
            {
                "credential": credential,
                "endpoint": endpoint,
                "taxonomy_name": taxonomy_name,
                "body": body,
            }
        )

    monkeypatch.setattr(redteam_eval_module, "_patch_taxonomy_via_rest", fake_rest_patch)

    summary = run_redteam_scan(
        endpoint="https://example.services.ai.azure.com/api/projects/demo",
        agent_id="qprisma-video-agent:7",
        agent_name=None,
        agent_version=None,
        model_deployment="gpt-4o",
        strategies=["base64"],
        risk_categories=["prohibited_actions"],
        num_turns=1,
        output_path=tmp_path / "redteam-results.json",
        scan_name="qprisma-redteam",
        poll_interval_seconds=0,
        timeout_seconds=5,
    )

    assert summary["run"]["status"] == "completed"
    assert [call["name"] for call in calls["taxonomy_update_calls"]] == [
        "foundry-generated-taxonomy",
        "taxonomy-asset-id",
        "qprisma-video-agent-prohibited-actions",
    ]
    assert calls["taxonomy_update_calls"][0]["body"]["taxonomyInput"] == {"type": "agent"}
    assert len(calls["rest_patch_calls"]) == 1
    assert (
        calls["rest_patch_calls"][0]["endpoint"]
        == "https://example.services.ai.azure.com/api/projects/demo"
    )
    assert calls["rest_patch_calls"][0]["taxonomy_name"] == "qprisma-video-agent-prohibited-actions"
    assert calls["rest_patch_calls"][0]["body"] == calls["taxonomy_update_calls"][0]["body"]
    assert calls["taxonomy_get_calls"] == ["qprisma-video-agent-prohibited-actions"]


def test_run_redteam_scan_logs_unexpected_taxonomy_shape(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    caplog: pytest.LogCaptureFixture,
):
    calls: dict[str, object] = {}

    class FakeCredential:
        def close(self):
            calls["credential_closed"] = True

    class FakeHttpResponseError(Exception):
        pass

    class FakeRiskCategory(Enum):
        PROHIBITED_ACTIONS = "ProhibitedActions"

    class FakeAzureAIAgentTarget:
        def __init__(self, *, name: str, version: str):
            self.name = name
            self.version = version

        def as_dict(self) -> dict[str, str]:
            return {
                "type": "azure_ai_agent",
                "name": self.name,
                "version": self.version,
            }

    class FakeAgentTaxonomyInput:
        def __init__(self, *, risk_categories: list[Enum], target: FakeAzureAIAgentTarget):
            self.risk_categories = risk_categories
            self.target = target

    class FakeEvaluationTaxonomy:
        def __init__(self, *, description: str, taxonomy_input: FakeAgentTaxonomyInput):
            self.description = description
            self.taxonomy_input = taxonomy_input

    class FakeResource:
        def __init__(self, resource_id: str, status: str):
            self.id = resource_id
            self.status = status

        def model_dump(self, mode: str = "json") -> dict[str, object]:
            return {
                "id": self.id,
                "status": self.status,
                "result_counts": {"total": 1 if self.status == "completed" else 0},
            }

    class FakeTaxonomy(FakeResource):
        def as_dict(self) -> dict[str, object]:
            return {
                "id": self.id,
                "name": "qprisma-video-agent-prohibited-actions",
                "description": "taxonomy",
                "taxonomyInput": {"type": "agent"},
            }

    class FakeOutputItem:
        def __init__(self, item_id: str):
            self.item_id = item_id

        def as_dict(self) -> dict[str, str]:
            return {"item_id": self.item_id}

    class FakeOutputItemsClient:
        def list(self, *, run_id: str, eval_id: str):
            calls["output_items_list"] = {"run_id": run_id, "eval_id": eval_id}
            return [FakeOutputItem("item-1")]

    class FakeRunsClient:
        def __init__(self):
            self.output_items = FakeOutputItemsClient()

        def create(self, *, eval_id: str, name: str, data_source: dict[str, object]):
            calls["run_create"] = {"eval_id": eval_id, "name": name, "data_source": data_source}
            return FakeResource("run-1", "queued")

        def retrieve(self, *, run_id: str, eval_id: str):
            calls.setdefault("run_retrieve_calls", 0)
            calls["run_retrieve_calls"] = int(calls["run_retrieve_calls"]) + 1
            return FakeResource(run_id, "completed")

    class FakeEvalsClient:
        def __init__(self):
            self.runs = FakeRunsClient()

        def create(
            self, *, name: str, data_source_config: dict[str, str], testing_criteria: list[dict]
        ):
            calls["eval_create"] = {
                "name": name,
                "data_source_config": data_source_config,
                "testing_criteria": testing_criteria,
            }
            return FakeResource("eval-1", "created")

    class FakeOpenAIClient:
        def __init__(self):
            self.evals = FakeEvalsClient()

        def close(self):
            calls["openai_closed"] = True

    class FakeEvaluationTaxonomiesClient:
        def create(self, *, name: str, body: FakeEvaluationTaxonomy | dict[str, object]):
            calls.setdefault("taxonomy_create_calls", []).append({"name": name, "body": body})
            return FakeTaxonomy("taxonomy-1", "completed")

        def update(self, *, name: str, body: dict[str, object]):
            raise AssertionError("taxonomy update should be skipped for unsupported payloads")

    class FakeBetaClient:
        def __init__(self):
            self.evaluation_taxonomies = FakeEvaluationTaxonomiesClient()

    class FakeProjectClient:
        def __init__(self, *, endpoint: str, credential: FakeCredential, allow_preview: bool):
            calls["project_init"] = {
                "endpoint": endpoint,
                "allow_preview": allow_preview,
                "credential_type": type(credential).__name__,
            }
            self.beta = FakeBetaClient()
            self.agents = types.SimpleNamespace()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def get_openai_client(self):
            return FakeOpenAIClient()

    azure_module = types.ModuleType("azure")
    azure_ai_module = types.ModuleType("azure.ai")
    projects_module = types.ModuleType("azure.ai.projects")
    projects_models_module = types.ModuleType("azure.ai.projects.models")
    azure_core_module = types.ModuleType("azure.core")
    azure_core_exceptions_module = types.ModuleType("azure.core.exceptions")
    azure_identity_module = types.ModuleType("azure.identity")

    projects_module.AIProjectClient = FakeProjectClient
    projects_models_module.AgentTaxonomyInput = FakeAgentTaxonomyInput
    projects_models_module.AzureAIAgentTarget = FakeAzureAIAgentTarget
    projects_models_module.EvaluationTaxonomy = FakeEvaluationTaxonomy
    projects_models_module.RiskCategory = FakeRiskCategory
    azure_core_exceptions_module.HttpResponseError = FakeHttpResponseError
    azure_identity_module.DefaultAzureCredential = FakeCredential

    monkeypatch.setitem(sys.modules, "azure", azure_module)
    monkeypatch.setitem(sys.modules, "azure.ai", azure_ai_module)
    monkeypatch.setitem(sys.modules, "azure.ai.projects", projects_module)
    monkeypatch.setitem(sys.modules, "azure.ai.projects.models", projects_models_module)
    monkeypatch.setitem(sys.modules, "azure.core", azure_core_module)
    monkeypatch.setitem(sys.modules, "azure.core.exceptions", azure_core_exceptions_module)
    monkeypatch.setitem(sys.modules, "azure.identity", azure_identity_module)

    output_path = tmp_path / "redteam-results.json"
    with caplog.at_level("WARNING"):
        summary = run_redteam_scan(
            endpoint="https://example.services.ai.azure.com/api/projects/demo",
            agent_id="qprisma-video-agent:7",
            agent_name=None,
            agent_version=None,
            model_deployment="gpt-4o",
            strategies=["base64"],
            risk_categories=["prohibited_actions"],
            num_turns=1,
            output_path=output_path,
            scan_name="qprisma-redteam",
            poll_interval_seconds=0,
            timeout_seconds=5,
        )

    assert summary["mode"] == "cloud_foundry_agent_redteam"
    assert len(calls["taxonomy_create_calls"]) == 1
    assert (
        "Generated taxonomy payload used an unexpected shape; skipping enablement update."
        in caplog.text
    )


def test_count_enabled_subcategories_handles_various_shapes():
    assert _count_enabled_subcategories({}) == 0
    assert _count_enabled_subcategories(None) == 0
    assert _count_enabled_subcategories({"taxonomyCategories": []}) == 0

    all_disabled = {
        "taxonomyCategories": [
            {
                "id": "cat-1",
                "subCategories": [
                    {"id": "sub-1", "enabled": False},
                    {"id": "sub-2", "enabled": False},
                ],
            }
        ]
    }
    assert _count_enabled_subcategories(all_disabled) == 0

    mixed = {
        "taxonomyCategories": [
            {
                "id": "cat-1",
                "subCategories": [
                    {"id": "sub-1", "enabled": True},
                    {"id": "sub-2", "enabled": False},
                ],
            },
            {
                "id": "cat-2",
                "subCategories": [
                    {"id": "sub-3", "enabled": True},
                ],
            },
        ]
    }
    assert _count_enabled_subcategories(mixed) == 2

    all_enabled = {
        "taxonomyCategories": [
            {
                "id": "cat-1",
                "subCategories": [
                    {"id": "sub-1", "enabled": True},
                    {"id": "sub-2", "enabled": True},
                ],
            }
        ]
    }
    assert _count_enabled_subcategories(all_enabled) == 2


def test_run_redteam_scan_raises_when_taxonomy_upsert_leaves_zero_enabled(
    monkeypatch: pytest.MonkeyPatch, tmp_path
):
    calls: dict[str, object] = {}

    class FakeCredential:
        def close(self):
            calls["credential_closed"] = True

    class FakeHttpResponseError(Exception):
        pass

    class FakeRiskCategory(Enum):
        PROHIBITED_ACTIONS = "ProhibitedActions"

    class FakeAzureAIAgentTarget:
        def __init__(self, *, name: str, version: str):
            self.name = name
            self.version = version

        def as_dict(self) -> dict[str, str]:
            return {
                "type": "azure_ai_agent",
                "name": self.name,
                "version": self.version,
            }

    class FakeAgentTaxonomyInput:
        def __init__(
            self, *, risk_categories: list[FakeRiskCategory], target: FakeAzureAIAgentTarget
        ):
            self.risk_categories = risk_categories
            self.target = target

    class FakeEvaluationTaxonomy:
        def __init__(self, *, description: str, taxonomy_input: FakeAgentTaxonomyInput):
            self.description = description
            self.taxonomy_input = taxonomy_input

    class FakeResource:
        def __init__(self, resource_id: str, status: str = "queued"):
            self.id = resource_id
            self.status = status

        def model_dump(self, mode: str = "json") -> dict[str, object]:
            return {
                "id": self.id,
                "status": self.status,
                "result_counts": {"total": 0},
            }

    class FakeTaxonomy(FakeResource):
        def __init__(self, resource_id: str):
            super().__init__(resource_id, "completed")

        def as_dict(self) -> dict[str, object]:
            return {
                "id": self.id,
                "name": "qprisma-video-agent-prohibited-actions",
                "description": "taxonomy",
                "taxonomyInput": {"type": "agent"},
                "taxonomyCategories": [
                    {
                        "id": "cat-1",
                        "name": "category",
                        "subCategories": [
                            {
                                "id": "sub-1",
                                "name": "still-disabled",
                                "enabled": False,
                            }
                        ],
                    }
                ],
            }

    class FakeOutputItemsClient:
        def list(self, *, run_id: str, eval_id: str):
            return []

    class FakeRunsClient:
        def __init__(self):
            self.output_items = FakeOutputItemsClient()

        def create(self, *, eval_id: str, name: str, data_source: dict[str, object]):
            calls["run_create"] = {"eval_id": eval_id, "name": name, "data_source": data_source}
            return FakeResource("run-1", "queued")

        def retrieve(self, *, run_id: str, eval_id: str):
            return FakeResource(run_id, "completed")

    class FakeEvalsClient:
        def __init__(self):
            self.runs = FakeRunsClient()

        def create(
            self, *, name: str, data_source_config: dict[str, str], testing_criteria: list[dict]
        ):
            return FakeResource("eval-1", "created")

    class FakeOpenAIClient:
        def __init__(self):
            self.evals = FakeEvalsClient()

        def close(self):
            calls["openai_closed"] = True

    class FakeEvaluationTaxonomiesClient:
        def __init__(self):
            self.create_calls = 0
            self.update_calls = 0

        def create(self, *, name: str, body: FakeEvaluationTaxonomy | dict[str, object]):
            self.create_calls += 1
            if isinstance(body, dict):
                raise FakeHttpResponseError("Taxonomy input is required is invalid")
            calls.setdefault("taxonomy_create_calls", []).append({"name": name, "body": body})
            return FakeTaxonomy("taxonomy-zero")

        def update(self, *, name: str, body: dict[str, object]):
            self.update_calls += 1
            calls.setdefault("taxonomy_update_calls", []).append({"name": name, "body": body})
            return FakeTaxonomy("taxonomy-zero")

    class FakeBetaClient:
        def __init__(self):
            self.evaluation_taxonomies = FakeEvaluationTaxonomiesClient()

    class FakeAgentsClient:
        def get(self, *, agent_name: str):
            return types.SimpleNamespace(version="99")

    class FakeProjectClient:
        def __init__(self, *, endpoint: str, credential: FakeCredential, allow_preview: bool):
            self.endpoint = endpoint
            self.beta = FakeBetaClient()
            self.agents = FakeAgentsClient()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def get_openai_client(self):
            return FakeOpenAIClient()

    azure_module = types.ModuleType("azure")
    azure_ai_module = types.ModuleType("azure.ai")
    projects_module = types.ModuleType("azure.ai.projects")
    projects_models_module = types.ModuleType("azure.ai.projects.models")
    azure_core_module = types.ModuleType("azure.core")
    azure_core_exceptions_module = types.ModuleType("azure.core.exceptions")
    azure_identity_module = types.ModuleType("azure.identity")

    projects_module.AIProjectClient = FakeProjectClient
    projects_models_module.AgentTaxonomyInput = FakeAgentTaxonomyInput
    projects_models_module.AzureAIAgentTarget = FakeAzureAIAgentTarget
    projects_models_module.EvaluationTaxonomy = FakeEvaluationTaxonomy
    projects_models_module.RiskCategory = FakeRiskCategory
    azure_core_exceptions_module.HttpResponseError = FakeHttpResponseError
    azure_identity_module.DefaultAzureCredential = FakeCredential

    monkeypatch.setitem(sys.modules, "azure", azure_module)
    monkeypatch.setitem(sys.modules, "azure.ai", azure_ai_module)
    monkeypatch.setitem(sys.modules, "azure.ai.projects", projects_module)
    monkeypatch.setitem(sys.modules, "azure.ai.projects.models", projects_models_module)
    monkeypatch.setitem(sys.modules, "azure.core", azure_core_module)
    monkeypatch.setitem(sys.modules, "azure.core.exceptions", azure_core_exceptions_module)
    monkeypatch.setitem(sys.modules, "azure.identity", azure_identity_module)

    output_path = tmp_path / "redteam-results.json"
    endpoint = "https://example.services.ai.azure.com/api/projects/demo"
    with pytest.raises(RuntimeError) as excinfo:
        run_redteam_scan(
            endpoint=endpoint,
            agent_id="qprisma-video-agent:7",
            agent_name=None,
            agent_version=None,
            model_deployment="gpt-4o",
            strategies=["base64"],
            risk_categories=["prohibited_actions"],
            num_turns=1,
            output_path=output_path,
            scan_name="qprisma-redteam",
            poll_interval_seconds=0,
            timeout_seconds=5,
        )

    message = str(excinfo.value)
    assert "taxonomy-zero" in message
    assert f"{endpoint}/evaluations" in message
    assert len(calls["taxonomy_create_calls"]) == 1
    assert len(calls["taxonomy_update_calls"]) == 1
    # The run must not be created when the taxonomy upsert leaves 0 enabled
    # subcategories; otherwise Foundry generates a zero-prompt scan.
    assert "run_create" not in calls


def _install_minimal_redteam_sdk_fakes(monkeypatch: pytest.MonkeyPatch, calls: dict[str, object]):
    class FakeCredential:
        def close(self):
            calls["credential_closed"] = True

    class FakeHttpResponseError(Exception):
        pass

    class FakeRiskCategory(Enum):
        PROHIBITED_ACTIONS = "ProhibitedActions"

    class FakeAzureAIAgentTarget:
        def __init__(self, *, name: str, version: str):
            self.name = name
            self.version = version

        def as_dict(self) -> dict[str, str]:
            return {
                "type": "azure_ai_agent",
                "name": self.name,
                "version": self.version,
            }

    class FakeAgentTaxonomyInput:
        def __init__(
            self, *, risk_categories: list[FakeRiskCategory], target: FakeAzureAIAgentTarget
        ):
            self.risk_categories = risk_categories
            self.target = target

    class FakeEvaluationTaxonomy:
        def __init__(self, *, description: str, taxonomy_input: FakeAgentTaxonomyInput):
            self.description = description
            self.taxonomy_input = taxonomy_input

    class FakeTaxonomy:
        id = "taxonomy-1"
        status = "completed"

        def as_dict(self) -> dict[str, object]:
            return {
                "id": self.id,
                "name": "qprisma-video-agent-prohibited-actions",
                "description": "taxonomy",
                "taxonomyInput": {"type": "agent"},
                "taxonomyCategories": [
                    {
                        "id": "cat-1",
                        "subCategories": [{"id": "sub-1", "enabled": True}],
                    }
                ],
            }

    class FakeEvaluationTaxonomiesClient:
        def create(self, *, name: str, body: FakeEvaluationTaxonomy | dict[str, object]):
            calls["taxonomy_create"] = {"name": name, "body": body}
            return FakeTaxonomy()

        def update(self, *, name: str, body: dict[str, object]):
            calls["taxonomy_update"] = {"name": name, "body": body}
            return FakeTaxonomy()

    class FakeRunsClient:
        class output_items:
            @staticmethod
            def list(*, run_id: str, eval_id: str):
                raise AssertionError("output items should not be listed in dry-run/preflight")

        def create(self, *, eval_id: str, name: str, data_source: dict[str, object]):
            raise AssertionError("red-team run should not be created in dry-run/preflight")

    class FakeEvalsClient:
        def __init__(self):
            self.runs = FakeRunsClient()

        def create(
            self, *, name: str, data_source_config: dict[str, str], testing_criteria: list[dict]
        ):
            raise AssertionError("eval group should not be created in dry-run/preflight")

    class FakeOpenAIClient:
        def __init__(self):
            self.evals = FakeEvalsClient()

        def close(self):
            calls["openai_closed"] = True

    class FakeBetaClient:
        def __init__(self):
            self.evaluation_taxonomies = FakeEvaluationTaxonomiesClient()

    class FakeAgentsClient:
        def get(self, *, agent_name: str):
            calls["agents_get"] = agent_name
            return types.SimpleNamespace(version="99")

    class FakeProjectClient:
        def __init__(self, *, endpoint: str, credential: FakeCredential, allow_preview: bool):
            calls["project_init"] = {"endpoint": endpoint, "allow_preview": allow_preview}
            self.beta = FakeBetaClient()
            self.agents = FakeAgentsClient()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def get_openai_client(self):
            return FakeOpenAIClient()

    azure_module = types.ModuleType("azure")
    azure_ai_module = types.ModuleType("azure.ai")
    projects_module = types.ModuleType("azure.ai.projects")
    projects_models_module = types.ModuleType("azure.ai.projects.models")
    azure_core_module = types.ModuleType("azure.core")
    azure_core_exceptions_module = types.ModuleType("azure.core.exceptions")
    azure_identity_module = types.ModuleType("azure.identity")

    projects_module.AIProjectClient = FakeProjectClient
    projects_models_module.AgentTaxonomyInput = FakeAgentTaxonomyInput
    projects_models_module.AzureAIAgentTarget = FakeAzureAIAgentTarget
    projects_models_module.EvaluationTaxonomy = FakeEvaluationTaxonomy
    projects_models_module.RiskCategory = FakeRiskCategory
    azure_core_exceptions_module.HttpResponseError = FakeHttpResponseError
    azure_identity_module.DefaultAzureCredential = FakeCredential

    monkeypatch.setitem(sys.modules, "azure", azure_module)
    monkeypatch.setitem(sys.modules, "azure.ai", azure_ai_module)
    monkeypatch.setitem(sys.modules, "azure.ai.projects", projects_module)
    monkeypatch.setitem(sys.modules, "azure.ai.projects.models", projects_models_module)
    monkeypatch.setitem(sys.modules, "azure.core", azure_core_module)
    monkeypatch.setitem(sys.modules, "azure.core.exceptions", azure_core_exceptions_module)
    monkeypatch.setitem(sys.modules, "azure.identity", azure_identity_module)


def test_run_redteam_scan_dry_run_writes_request_shape_without_foundry_resources(
    monkeypatch: pytest.MonkeyPatch, tmp_path
):
    calls: dict[str, object] = {}
    _install_minimal_redteam_sdk_fakes(monkeypatch, calls)
    output_path = tmp_path / "redteam-results.json"

    summary = run_redteam_scan(
        endpoint="https://example.services.ai.azure.com/api/projects/demo",
        agent_id="qprisma-video-agent:7",
        agent_name=None,
        agent_version=None,
        model_deployment="gpt-4o",
        strategies=["base64"],
        risk_categories=["prohibited_actions"],
        num_turns=1,
        output_path=output_path,
        scan_name="qprisma-redteam",
        poll_interval_seconds=0,
        timeout_seconds=5,
        dry_run=True,
    )

    assert summary["status"] == "dry_run"
    assert "taxonomy_create" not in calls
    assert summary["request_shape"]["data_source"]["item_generation_params"]["source"] == {
        "type": "file_id",
        "id": "<taxonomy-file-id-from-preflight-or-created-taxonomy>",
    }
    assert output_path.exists()
    assert (tmp_path / "redteam-results-request-shape.json").exists()


def test_run_redteam_scan_preflight_validates_taxonomy_without_creating_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path
):
    calls: dict[str, object] = {}
    _install_minimal_redteam_sdk_fakes(monkeypatch, calls)
    output_path = tmp_path / "redteam-preflight.json"

    summary = run_redteam_scan(
        endpoint="https://example.services.ai.azure.com/api/projects/demo",
        agent_id="qprisma-video-agent:7",
        agent_name=None,
        agent_version=None,
        model_deployment="gpt-4o",
        strategies=["base64"],
        risk_categories=["prohibited_actions"],
        num_turns=1,
        output_path=output_path,
        scan_name="qprisma-redteam",
        poll_interval_seconds=0,
        timeout_seconds=5,
        preflight=True,
    )

    assert summary["status"] == "preflight_passed"
    assert calls["taxonomy_create"]["name"] == "qprisma-video-agent-prohibited-actions"
    assert "taxonomy_update" not in calls
    assert summary["taxonomy_enabled_subcategories"] == 1
    assert output_path.exists()
    assert (tmp_path / "redteam-preflight-request-shape.json").exists()
