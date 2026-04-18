"""
Cloud AI Red Team runner for the QPrisma video agent.

This module uses the Microsoft Foundry cloud red-teaming workflow for Foundry
Agents rather than the local PyRIT ``azure.ai.evaluation.red_team.RedTeam``
helper. The cloud path matches the documented Foundry-Agent flow:

1. Create a red team evaluation group
2. Create or update the prohibited-actions taxonomy for the target agent
3. Create a red-team run against the hosted agent
4. Poll until the run reaches a terminal state
5. Persist the run summary and output items as a JSON artifact

Usage::

    python -m evaluation_foundry.redteam_eval \
        --agent-id qprisma-video-agent:3 \
        --endpoint https://<foundry>.services.ai.azure.com/api/projects/<project> \
        --model-deployment gpt-4o \
        --strategies base64,flip,indirect_jailbreak \
        --output redteam-results.json

Environment variables:
    AZURE_AI_PROJECT_ENDPOINT - Foundry project endpoint URL (fallback for --endpoint)
    AZURE_AI_MODEL_DEPLOYMENT_NAME - model deployment used by builtin.task_adherence
    QPRISMA_REDTEAM_NUM_TURNS - generated red-team turn depth (default: 5)
    QPRISMA_REDTEAM_TIMEOUT_SECONDS - max poll time before failing (default: 3600)
    QPRISMA_REDTEAM_POLL_INTERVAL_SECONDS - polling interval (default: 10)
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

DEFAULT_STRATEGIES: list[str] = ["base64", "flip", "indirect_jailbreak"]
DEFAULT_RISK_CATEGORIES: list[str] = ["prohibited_actions"]
DEFAULT_MODEL_DEPLOYMENT = "gpt-4o"
TERMINAL_RUN_STATUSES = {"completed", "failed", "canceled"}
_ATTACK_STRATEGY_ALIASES = {
    "ansi_attack": "AnsiAttack",
    "ascii_art": "AsciiArt",
    "ascii_smuggler": "AsciiSmuggler",
    "atbash": "Atbash",
    "base64": "Base64",
    "binary": "Binary",
    "caesar": "Caesar",
    "character_space": "CharacterSpace",
    "charswap": "CharSwap",
    "char_swap": "CharSwap",
    "crescendo": "Crescendo",
    "diacritic": "Diacritic",
    "flip": "Flip",
    "indirect_attack": "IndirectAttack",
    "indirect_jailbreak": "IndirectJailbreak",
    "jailbreak": "Jailbreak",
    "leetspeak": "Leetspeak",
    "morse": "Morse",
    "multiturn": "Multiturn",
    "multi_turn": "Multiturn",
    "rot13": "ROT13",
    "string_join": "StringJoin",
    "suffix_append": "SuffixAppend",
    "tense": "Tense",
    "unicode_confusable": "UnicodeConfusable",
    "unicode_substitution": "UnicodeSubstitution",
    "url": "Url",
}
_RISK_CATEGORY_ALIASES = {
    "prohibitedactions": "PROHIBITED_ACTIONS",
    "prohibited_actions": "PROHIBITED_ACTIONS",
}


def _split_agent_reference(agent_id: str) -> tuple[str, str | None]:
    """Split a ``name[:version]`` identifier into components."""
    normalized = agent_id.strip()
    if not normalized:
        raise ValueError("Agent identifier cannot be empty.")

    if ":" not in normalized:
        return normalized, None

    name, version = normalized.split(":", 1)
    name = name.strip()
    version = version.strip()
    if not name or not version:
        raise ValueError(
            "Agent identifier must use the format '<agent_name>:<agent_version>' "
            "when a version is provided."
        )
    return name, version


def _normalize_attack_strategy(name: str) -> str:
    """Convert CLI-friendly strategy tokens to the cloud API representation."""
    normalized = re.sub(r"[\s\-]+", "_", name.strip().lower())
    if not normalized:
        raise ValueError("Attack strategy values cannot be empty.")

    if normalized in _ATTACK_STRATEGY_ALIASES:
        return _ATTACK_STRATEGY_ALIASES[normalized]

    parts = [part for part in normalized.split("_") if part]
    if not parts:
        raise ValueError(f"Invalid attack strategy '{name}'.")

    return "".join(part[:1].upper() + part[1:] for part in parts)


def _map_enum_member(cls: Any, name: str) -> Any:
    """Map a CLI token to an SDK enum member case-insensitively."""
    normalized = name.strip().lower()
    for member in cls:
        if member.name.lower() == normalized:
            return member
        value = getattr(member, "value", None)
        if isinstance(value, str) and value.lower() == normalized:
            return member

    valid = ", ".join(m.name.lower() for m in cls)
    raise ValueError(f"Unknown {cls.__name__} '{name}'. Valid values: {valid}")


def _normalize_risk_category(name: str) -> str:
    normalized = re.sub(r"[\s\-]+", "_", name.strip().lower())
    if normalized not in _RISK_CATEGORY_ALIASES:
        raise ValueError(
            "Cloud Foundry Agent red-team currently uses the prohibited_actions "
            "taxonomy only. Use --risk-categories prohibited_actions."
        )
    return _RISK_CATEGORY_ALIASES[normalized]


def _to_json_primitive(value: Any) -> Any:
    """Convert SDK objects into JSON-serializable primitives."""
    if hasattr(value, "as_dict") and callable(value.as_dict):
        return _to_json_primitive(value.as_dict())
    if hasattr(value, "model_dump") and callable(value.model_dump):
        try:
            return _to_json_primitive(value.model_dump(mode="json"))
        except TypeError:
            return _to_json_primitive(value.model_dump())
    if isinstance(value, dict):
        return {key: _to_json_primitive(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_to_json_primitive(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    return repr(value)


def _build_enabled_taxonomy_update(taxonomy: Any) -> tuple[dict[str, Any], bool, bool]:
    """Build a PATCH payload with all generated taxonomy items enabled."""
    raw = _to_json_primitive(taxonomy)
    if not isinstance(raw, dict):
        return {}, False, False

    categories = raw.get("taxonomyCategories")
    if not isinstance(categories, list):
        return {}, False, False

    changed = False
    updated_categories: list[dict[str, Any]] = []
    for category in categories:
        if not isinstance(category, dict):
            updated_categories.append(category)
            continue

        updated_category = dict(category)
        if isinstance(updated_category.get("enabled"), bool) and not updated_category["enabled"]:
            updated_category["enabled"] = True
            changed = True

        sub_categories = updated_category.get("subCategories")
        if isinstance(sub_categories, list):
            updated_sub_categories: list[dict[str, Any]] = []
            for sub_category in sub_categories:
                if not isinstance(sub_category, dict):
                    updated_sub_categories.append(sub_category)
                    continue

                updated_sub_category = dict(sub_category)
                if isinstance(updated_sub_category.get("enabled"), bool):
                    if not updated_sub_category["enabled"]:
                        updated_sub_category["enabled"] = True
                        changed = True
                else:
                    updated_sub_category["enabled"] = True
                    changed = True

                updated_sub_categories.append(updated_sub_category)
            updated_category["subCategories"] = updated_sub_categories

        updated_categories.append(updated_category)

    taxonomy_input = raw.get("taxonomyInput")
    body: dict[str, Any] = {"taxonomyCategories": updated_categories}
    if isinstance(taxonomy_input, dict):
        input_type = taxonomy_input.get("type")
        if isinstance(input_type, str) and input_type.strip():
            # The PATCH contract documents ``taxonomyInput`` as optional, but if
            # it is present the discriminator must still be included.
            body["taxonomyInput"] = {"type": input_type}
    if raw.get("description") is not None:
        body["description"] = raw["description"]
    if raw.get("properties") is not None:
        body["properties"] = raw["properties"]
    if raw.get("tags") is not None:
        body["tags"] = raw["tags"]

    return body, changed, True


def _count_enabled_subcategories(taxonomy: Any) -> int:
    """Return the number of enabled subcategories across all categories."""
    raw = _to_json_primitive(taxonomy)
    if not isinstance(raw, dict):
        return 0

    count = 0
    for category in raw.get("taxonomyCategories") or []:
        if not isinstance(category, dict):
            continue
        for sub in category.get("subCategories") or []:
            if isinstance(sub, dict) and sub.get("enabled") is True:
                count += 1
    return count


def _extract_taxonomy_update_identifiers(taxonomy: Any, requested_name: str) -> list[str]:
    """Return unique identifier candidates for the taxonomy update call."""
    raw = _to_json_primitive(taxonomy)
    candidates: list[str] = []

    def add(candidate: Any) -> None:
        if not isinstance(candidate, str):
            return
        normalized = candidate.strip()
        if normalized and normalized not in candidates:
            candidates.append(normalized)

    if isinstance(raw, dict):
        add(raw.get("name"))
        add(raw.get("id"))

    add(getattr(taxonomy, "name", None))
    add(getattr(taxonomy, "id", None))
    add(requested_name)
    return candidates


def _build_retry_taxonomy_update_body(
    taxonomy: Any,
    base_body: dict[str, Any],
) -> dict[str, Any]:
    """Return a broader PATCH body that reuses the original taxonomy input."""
    raw = _to_json_primitive(taxonomy)
    if not isinstance(raw, dict):
        return base_body

    taxonomy_input = raw.get("taxonomyInput")
    if not isinstance(taxonomy_input, dict):
        return base_body

    input_type = taxonomy_input.get("type")
    if not isinstance(input_type, str) or not input_type.strip():
        return base_body

    retry_body = dict(base_body)
    retry_body["taxonomyInput"] = dict(taxonomy_input)
    return retry_body


def _http_response_target_matches(exc: Exception, target: str) -> bool:
    return f"target: {target.lower()}" in str(exc).lower()


def _is_resource_not_found_error(exc: Exception) -> bool:
    return exc.__class__.__name__ == "ResourceNotFoundError" or "not found" in str(exc).lower()


def _patch_taxonomy_via_rest(
    *,
    credential: Any,
    endpoint: str,
    taxonomy_name: str,
    body: dict[str, Any],
) -> None:
    """PATCH a taxonomy using the documented Foundry REST endpoint."""
    token = credential.get_token("https://ai.azure.com/.default").token
    url = f"{endpoint.rstrip('/')}/evaluationtaxonomies/{taxonomy_name}?api-version=v1"
    try:
        response = httpx.patch(
            url,
            json=body,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Foundry-Features": "Evaluations=V1Preview",
            },
            timeout=30.0,
        )
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        details = exc.response.text.strip() or str(exc)
        raise RuntimeError(
            f"Foundry REST taxonomy PATCH failed for '{taxonomy_name}' with status "
            f"{exc.response.status_code}: {details}"
        ) from exc
    except httpx.RequestError as exc:
        raise RuntimeError(
            f"Foundry REST taxonomy PATCH failed for '{taxonomy_name}' at '{url}': {exc}"
        ) from exc


def _extract_run_status(run: Any) -> str:
    raw = _to_json_primitive(run)
    if isinstance(raw, dict):
        return str(raw.get("status", "") or "").lower()

    return str(getattr(run, "status", "") or "").lower()


def _extract_total_results(source: Any) -> int:
    """Best-effort total result count from a run object or full summary dict.

    Falls back to per-criteria counts and ``output_items`` length when the
    primary ``result_counts.total`` field is missing or zero, which has been
    observed in completed-but-empty Foundry runs.
    """
    raw = _to_json_primitive(source)
    if not isinstance(raw, dict):
        return 0

    # ``source`` can be a run dict OR a summary that wraps a run.
    candidates: list[dict[str, Any]] = [raw]
    nested_run = raw.get("run")
    if isinstance(nested_run, dict):
        candidates.append(nested_run)

    for candidate in candidates:
        result_counts = candidate.get("result_counts") or candidate.get("resultCounts")
        if isinstance(result_counts, dict):
            total = result_counts.get("total")
            if isinstance(total, int) and total > 0:
                return total

        per_criteria = candidate.get("per_testing_criteria_results") or candidate.get(
            "perTestingCriteriaResults"
        )
        if isinstance(per_criteria, list) and per_criteria:
            criteria_totals: list[int] = []
            for entry in per_criteria:
                if not isinstance(entry, dict):
                    continue
                passed = entry.get("passed", 0)
                failed = entry.get("failed", 0)
                if isinstance(passed, int) and isinstance(failed, int):
                    criteria_totals.append(passed + failed)
            if criteria_totals and max(criteria_totals) > 0:
                return max(criteria_totals)

    output_items = raw.get("output_items")
    if isinstance(output_items, list) and output_items:
        return len(output_items)

    return 0


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, default=_to_json_primitive, indent=2), encoding="utf-8")


def _build_testing_criteria(model_deployment: str) -> list[dict[str, Any]]:
    return [
        {
            "type": "azure_ai_evaluator",
            "name": "Prohibited Actions",
            "evaluator_name": "builtin.prohibited_actions",
            "evaluator_version": "1",
        },
        {
            "type": "azure_ai_evaluator",
            "name": "Task Adherence",
            "evaluator_name": "builtin.task_adherence",
            "evaluator_version": "1",
            "initialization_parameters": {"deployment_name": model_deployment},
        },
        {
            "type": "azure_ai_evaluator",
            "name": "Sensitive Data Leakage",
            "evaluator_name": "builtin.sensitive_data_leakage",
            "evaluator_version": "1",
        },
    ]


def _resolve_agent_target(
    *,
    project_client: Any,
    agent_id: str | None,
    agent_name: str | None,
    agent_version: str | None,
) -> tuple[str, str]:
    if agent_id:
        parsed_name, parsed_version = _split_agent_reference(agent_id)
        agent_name = agent_name or parsed_name
        agent_version = agent_version or parsed_version

    if not agent_name:
        raise ValueError("Missing target agent. Provide --agent-id or --agent-name.")

    if not agent_version:
        logger.info("No agent version supplied, resolving the latest version for %s", agent_name)
        latest_agent = project_client.agents.get(agent_name=agent_name)
        agent_version = str(getattr(latest_agent, "version", "") or "").strip()
        if not agent_version:
            raise RuntimeError(f"Could not resolve a latest version for agent '{agent_name}'.")

    return agent_name, agent_version


def run_redteam_scan(
    *,
    endpoint: str,
    agent_id: str | None,
    agent_name: str | None,
    agent_version: str | None,
    model_deployment: str,
    strategies: list[str],
    risk_categories: list[str],
    num_turns: int,
    output_path: Path,
    scan_name: str,
    poll_interval_seconds: int,
    timeout_seconds: int,
) -> dict[str, Any]:
    """Execute a cloud red-team run against the hosted agent."""
    try:
        from azure.ai.projects import AIProjectClient
        from azure.ai.projects.models import (
            AgentTaxonomyInput,
            AzureAIAgentTarget,
            EvaluationTaxonomy,
            RiskCategory,
        )
        from azure.core.exceptions import HttpResponseError
        from azure.identity import DefaultAzureCredential
    except ImportError as exc:
        raise RuntimeError(
            "azure-ai-projects>=2.0.0 and azure-identity are required. "
            "Install with `pip install azure-ai-projects azure-identity`."
        ) from exc

    normalized_strategies = [_normalize_attack_strategy(strategy) for strategy in strategies]
    mapped_risks = [
        _map_enum_member(RiskCategory, _normalize_risk_category(category))
        for category in risk_categories
    ]

    credential = DefaultAzureCredential()
    openai_client = None
    try:
        with AIProjectClient(
            endpoint=endpoint,
            credential=credential,
            allow_preview=True,
        ) as project_client:
            openai_client = project_client.get_openai_client()
            resolved_agent_name, resolved_agent_version = _resolve_agent_target(
                project_client=project_client,
                agent_id=agent_id,
                agent_name=agent_name,
                agent_version=agent_version,
            )
            target = AzureAIAgentTarget(
                name=resolved_agent_name,
                version=resolved_agent_version,
            )

            logger.info(
                "Starting cloud red-team run (agent=%s:%s, strategies=%s, risk_categories=%s, "
                "num_turns=%d)",
                resolved_agent_name,
                resolved_agent_version,
                normalized_strategies,
                [risk.name for risk in mapped_risks],
                num_turns,
            )

            red_team = openai_client.evals.create(
                name=f"{scan_name}-group",
                data_source_config={"type": "azure_ai_source", "scenario": "red_team"},
                testing_criteria=_build_testing_criteria(model_deployment),
            )

            taxonomy_name = f"{resolved_agent_name}-prohibited-actions"
            taxonomy = project_client.beta.evaluation_taxonomies.create(
                name=taxonomy_name,
                body=EvaluationTaxonomy(
                    description="QPrisma prohibited-actions taxonomy for cloud red teaming",
                    taxonomy_input=AgentTaxonomyInput(
                        risk_categories=mapped_risks,
                        target=target,
                    ),
                ),
            )
            (
                taxonomy_update_body,
                taxonomy_changed,
                taxonomy_payload_supported,
            ) = _build_enabled_taxonomy_update(taxonomy)
            if taxonomy_changed:
                logger.info(
                    "Enabling generated prohibited-actions taxonomy items before creating the run."
                )
                update_identifiers = _extract_taxonomy_update_identifiers(
                    taxonomy,
                    requested_name=taxonomy_name,
                )
                retry_update_body = _build_retry_taxonomy_update_body(
                    taxonomy,
                    taxonomy_update_body,
                )
                last_update_error: HttpResponseError | None = None
                update_succeeded = False
                for identifier in update_identifiers:
                    try:
                        taxonomy = project_client.beta.evaluation_taxonomies.update(
                            name=identifier,
                            body=taxonomy_update_body,
                        )
                        update_succeeded = True
                        break
                    except HttpResponseError as exc:
                        last_update_error = exc
                        if _http_response_target_matches(exc, "taxonomyId"):
                            logger.warning(
                                "Taxonomy update rejected identifier '%s'; trying the next "
                                "identifier candidate.",
                                identifier,
                            )
                            continue
                        if _is_resource_not_found_error(exc):
                            logger.warning(
                                "Taxonomy update could not resolve identifier '%s'; trying "
                                "the next identifier candidate.",
                                identifier,
                            )
                            continue
                        if (
                            _http_response_target_matches(exc, "taxonomyInput")
                            and retry_update_body != taxonomy_update_body
                        ):
                            logger.warning(
                                "Taxonomy update rejected the minimal PATCH taxonomyInput for "
                                "identifier '%s'; retrying with the original taxonomy input "
                                "metadata.",
                                identifier,
                            )
                            try:
                                taxonomy = project_client.beta.evaluation_taxonomies.update(
                                    name=identifier,
                                    body=retry_update_body,
                                )
                                update_succeeded = True
                                break
                            except HttpResponseError as retry_exc:
                                last_update_error = retry_exc
                                if _http_response_target_matches(retry_exc, "taxonomyId"):
                                    logger.warning(
                                        "Taxonomy update still rejected identifier '%s' after "
                                        "retrying with the full taxonomy input.",
                                        identifier,
                                    )
                                    continue
                                if _is_resource_not_found_error(retry_exc):
                                    logger.warning(
                                        "Taxonomy update still could not resolve identifier "
                                        "'%s' after retrying with the full taxonomy input.",
                                        identifier,
                                    )
                                    continue
                                raise
                        raise
                if not update_succeeded:
                    if last_update_error is None:
                        raise RuntimeError(
                            "Could not determine a valid taxonomy identifier to update."
                        )
                    if _http_response_target_matches(
                        last_update_error, "taxonomyId"
                    ) or _is_resource_not_found_error(last_update_error):
                        logger.warning(
                            "SDK taxonomy update did not match the live Foundry service "
                            "contract; retrying taxonomy enablement through the documented "
                            "REST PATCH endpoint."
                        )
                        rest_bodies = [taxonomy_update_body]
                        if retry_update_body != taxonomy_update_body:
                            rest_bodies.append(retry_update_body)
                        rest_error: RuntimeError | None = None
                        for rest_body in rest_bodies:
                            try:
                                _patch_taxonomy_via_rest(
                                    credential=credential,
                                    endpoint=endpoint,
                                    taxonomy_name=taxonomy_name,
                                    body=rest_body,
                                )
                                taxonomy = project_client.beta.evaluation_taxonomies.get(
                                    name=taxonomy_name
                                )
                                update_succeeded = True
                                break
                            except RuntimeError as rest_exc:
                                rest_error = rest_exc
                                if (
                                    _http_response_target_matches(rest_exc, "taxonomyInput")
                                    and rest_body == taxonomy_update_body
                                    and retry_update_body != taxonomy_update_body
                                ):
                                    logger.warning(
                                        "REST taxonomy PATCH rejected the minimal taxonomyInput "
                                        "payload; retrying with the original taxonomy input "
                                        "metadata."
                                    )
                                    continue
                                raise
                        if not update_succeeded and rest_error is not None:
                            raise rest_error
                    else:
                        raise last_update_error
                enabled_count = _count_enabled_subcategories(taxonomy)
                if enabled_count == 0:
                    taxonomy_id = getattr(taxonomy, "id", None) or "<unknown>"
                    raise RuntimeError(
                        "Failed to enable taxonomy subcategories for taxonomy "
                        f"'{taxonomy_id}'. All subcategories remain disabled after "
                        "the update; the red-team run would generate zero attack "
                        f"prompts. Review and enable manually at {endpoint}/evaluations."
                    )
                logger.info(
                    "Taxonomy '%s' now has %d enabled subcategories.",
                    getattr(taxonomy, "id", "<unknown>"),
                    enabled_count,
                )
            elif not taxonomy_payload_supported:
                logger.warning(
                    "Generated taxonomy payload used an unexpected shape; skipping enablement "
                    "update. The red-team run may produce zero cases."
                )
            else:
                logger.warning(
                    "Generated taxonomy returned no disabled items to enable. "
                    "The red-team run may produce zero cases."
                )

            eval_run = openai_client.evals.runs.create(
                eval_id=red_team.id,
                name=scan_name,
                data_source={
                    "type": "azure_ai_red_team",
                    "item_generation_params": {
                        "type": "red_team_taxonomy",
                        "attack_strategies": normalized_strategies,
                        "num_turns": num_turns,
                        "source": {"type": "file_id", "id": taxonomy.id},
                    },
                    "target": target.as_dict(),
                },
            )

            deadline = time.monotonic() + timeout_seconds
            run = eval_run
            while True:
                status = _extract_run_status(run)
                logger.info("Red-team run status: %s", status or "<unknown>")
                if status in TERMINAL_RUN_STATUSES:
                    break
                if time.monotonic() >= deadline:
                    raise TimeoutError(
                        f"Timed out waiting for red-team run '{eval_run.id}' after "
                        f"{timeout_seconds} seconds."
                    )
                time.sleep(poll_interval_seconds)
                run = openai_client.evals.runs.retrieve(run_id=eval_run.id, eval_id=red_team.id)

            output_items: list[Any] = []
            output_items_error: str | None = None
            try:
                output_items = list(
                    openai_client.evals.runs.output_items.list(
                        run_id=run.id,
                        eval_id=red_team.id,
                    )
                )
            except HttpResponseError as exc:
                output_items_error = str(exc)
                logger.warning("Could not fetch red-team output items: %s", exc)

            summary = {
                "mode": "cloud_foundry_agent_redteam",
                "endpoint": endpoint,
                "agent": {
                    "name": resolved_agent_name,
                    "version": resolved_agent_version,
                },
                "model_deployment": model_deployment,
                "strategies": normalized_strategies,
                "risk_categories": [risk.name for risk in mapped_risks],
                "red_team": _to_json_primitive(red_team),
                "taxonomy": _to_json_primitive(taxonomy),
                "run": _to_json_primitive(run),
                "output_items": _to_json_primitive(output_items),
                "output_items_error": output_items_error,
                "portal_url": f"{endpoint}/evaluations",
            }
            _write_json(output_path, summary)
            return summary
    finally:
        if openai_client is not None and hasattr(openai_client, "close"):
            openai_client.close()
        if hasattr(credential, "close"):
            credential.close()


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run cloud red-team scan against QPrisma agent")
    parser.add_argument(
        "--agent-id",
        help="Foundry agent identifier in the form '<name>:<version>'",
    )
    parser.add_argument(
        "--agent-name",
        help="Foundry agent name. Use with --agent-version or omit version to resolve latest.",
    )
    parser.add_argument(
        "--agent-version",
        help="Foundry agent version. Optional when --agent-id includes it or when resolving latest.",
    )
    parser.add_argument(
        "--endpoint",
        default=os.environ.get("AZURE_AI_PROJECT_ENDPOINT"),
        help="Foundry project endpoint URL (env: AZURE_AI_PROJECT_ENDPOINT)",
    )
    parser.add_argument(
        "--model-deployment",
        default=os.environ.get("AZURE_AI_MODEL_DEPLOYMENT_NAME", DEFAULT_MODEL_DEPLOYMENT),
        help=(
            "Foundry project deployment name used to initialize builtin.task_adherence "
            f"(default: {DEFAULT_MODEL_DEPLOYMENT})"
        ),
    )
    parser.add_argument(
        "--strategies",
        default=",".join(DEFAULT_STRATEGIES),
        help=f"Comma-separated attack strategies (default: {','.join(DEFAULT_STRATEGIES)})",
    )
    parser.add_argument(
        "--risk-categories",
        default=",".join(DEFAULT_RISK_CATEGORIES),
        help=(
            "Comma-separated taxonomy risk categories. "
            "Cloud Foundry Agent red-team currently supports prohibited_actions."
        ),
    )
    parser.add_argument(
        "--num-turns",
        type=int,
        default=int(os.environ.get("QPRISMA_REDTEAM_NUM_TURNS", "5")),
        help="Generated red-team turn depth (default: 5)",
    )
    parser.add_argument(
        "--poll-interval-seconds",
        type=int,
        default=int(os.environ.get("QPRISMA_REDTEAM_POLL_INTERVAL_SECONDS", "10")),
        help="Polling interval while waiting for the red-team run (default: 10)",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=int(os.environ.get("QPRISMA_REDTEAM_TIMEOUT_SECONDS", "3600")),
        help="Fail if the red-team run does not finish within this many seconds (default: 3600)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("redteam-results.json"),
        help="Output JSON path for run summary and output items",
    )
    parser.add_argument(
        "--scan-name",
        default="qprisma-cloud-redteam",
        help="Display name for the Foundry red-team run",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = _parse_args(argv)

    if not args.endpoint:
        logger.error("Missing --endpoint (or AZURE_AI_PROJECT_ENDPOINT env var)")
        return 2

    if not args.agent_id and not args.agent_name:
        logger.error("Missing target agent. Provide --agent-id or --agent-name.")
        return 2

    strategies = [strategy.strip() for strategy in args.strategies.split(",") if strategy.strip()]
    risk_categories = [item.strip() for item in args.risk_categories.split(",") if item.strip()]

    try:
        summary = run_redteam_scan(
            endpoint=args.endpoint,
            agent_id=args.agent_id,
            agent_name=args.agent_name,
            agent_version=args.agent_version,
            model_deployment=args.model_deployment,
            strategies=strategies,
            risk_categories=risk_categories,
            num_turns=args.num_turns,
            output_path=args.output,
            scan_name=args.scan_name,
            poll_interval_seconds=args.poll_interval_seconds,
            timeout_seconds=args.timeout_seconds,
        )
    except Exception as exc:
        logger.exception("Cloud red-team run failed")
        _write_json(
            args.output,
            {
                "mode": "cloud_foundry_agent_redteam",
                "status": "failed",
                "error": str(exc),
                "endpoint": args.endpoint,
                "agent_id": args.agent_id,
                "agent_name": args.agent_name,
                "agent_version": args.agent_version,
            },
        )
        return 1

    status = _extract_run_status(summary.get("run"))
    logger.info("Red-team results written to %s", args.output)
    if status != "completed":
        logger.error(
            "Red-team run finished with status '%s'. Check Azure AI User role, supported "
            "region, and Foundry project prerequisites.",
            status or "<unknown>",
        )
        return 1
    total_results = _extract_total_results(summary)
    if total_results == 0:
        taxonomy_info = summary.get("taxonomy") if isinstance(summary, dict) else None
        taxonomy_id = (
            taxonomy_info.get("id") if isinstance(taxonomy_info, dict) else None
        ) or "<unknown>"
        portal_url = (
            summary.get("portal_url") if isinstance(summary, dict) else None
        ) or f"{args.endpoint}/evaluations"
        logger.error(
            "Red-team run completed but generated zero result items. "
            "Taxonomy ID: %s. Review and enable prohibited-actions subcategories at %s",
            taxonomy_id,
            portal_url,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
