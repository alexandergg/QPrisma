"""
Evaluation Data File Generator
================================

Generates Azure AI Foundry-compatible evaluation data files from query templates
and environment-configured test media.

Usage:
    # From backend/ directory:
    python -m evaluation_foundry.generate_eval_data

    # With custom output directory:
    python -m evaluation_foundry.generate_eval_data --output-dir /tmp/eval

Environment variables:
    EVAL_MEDIA_ID_1, EVAL_MEDIA_ID_2, ...  — current media IDs for uploaded test videos
    EVAL_USER_ID                            — current runtime user ID recognized by the hosted agent
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

from agent.hosted.context_envelope import format_qprisma_context

from evaluation_foundry.config import (
    AGENT_EVAL_EVALUATORS,
    AGENT_EVAL_FILE,
    ENV_MEDIA_ID_PREFIX,
    ENV_USER_ID,
    QUALITY_EVAL_EVALUATORS,
    QUALITY_EVAL_FILE,
    SAFETY_EVAL_EVALUATORS,
    SAFETY_EVAL_FILE,
)
from evaluation_foundry.data.query_templates import (
    ALL_GENERAL_TEMPLATES,
    ALL_SAFETY_TEMPLATES,
    QueryTemplate,
)
from evaluation_foundry.tool_definitions import TOOL_DEFINITIONS

logger = logging.getLogger(__name__)
USER_ID_RUNTIME_PATTERN = re.compile(r"^user_[0-9a-f]{12}$")


def _format_context(
    media_id: str | None,
    user_id: str | None,
    *,
    media_ids: list[str] | None = None,
    response_mode: str | None = None,
) -> str:
    """Build the QPRISMA_CONTEXT prefix string.

    Parameters
    ----------
    media_id:
        Single video/media ID for single-video queries.
    user_id:
        Runtime user ID recognized by the hosted agent.
    media_ids:
        Full list of video/media IDs for multi-video / cross-video queries.
    response_mode:
        Optional response mode hint for the hosted agent converter.
        This is deprecated for normal evaluation generation because production
        traffic does not set it by default. Keep it available only as an
        explicit override while the adapter audit is still in progress.
    """
    parts: dict[str, str | list[str]] = {}
    if media_id:
        parts["media_id"] = media_id
    if media_ids:
        parts["media_ids"] = media_ids
    if user_id:
        parts["user_id"] = user_id
    if response_mode:
        parts["response_mode"] = response_mode
    if not parts:
        return ""
    return format_qprisma_context(parts, "")


# ---------------------------------------------------------------------------
# Environment helpers
# ---------------------------------------------------------------------------


def _collect_media_ids() -> list[str]:
    """Collect all EVAL_MEDIA_ID_* environment variables."""
    ids: list[str] = []
    for i in range(1, 20):
        val = os.environ.get(f"{ENV_MEDIA_ID_PREFIX}{i}")
        if val:
            ids.append(val.strip())
    return ids


def _get_user_id() -> str | None:
    """Get EVAL_USER_ID from environment."""
    val = os.environ.get(ENV_USER_ID)
    return val.strip() if val else None


def _has_runtime_user_id_format(user_id: str) -> bool:
    """Check whether a user_id matches the hosted-agent runtime format."""
    return USER_ID_RUNTIME_PATTERN.fullmatch(user_id) is not None


# ---------------------------------------------------------------------------
# Tool-definitions format transform
# ---------------------------------------------------------------------------


def _flatten_tool_definitions(definitions: list[dict]) -> list[dict]:
    """Convert OpenAI Chat Completions tool format to Foundry evaluator format.

    The canonical ``TOOL_DEFINITIONS`` use the OpenAI nested schema::

        {"type": "function", "function": {"name": "...", "description": "...", ...}}

    The Foundry evaluator (``tool_call_accuracy``, etc.) expects ``name`` at the
    root level::

        {"type": "function", "name": "...", "description": "...", "parameters": {...}}

    This function performs that flattening at data-generation time so the
    canonical definitions remain in standard OpenAI format.
    """
    flat: list[dict] = []
    for tool_def in definitions:
        fn = tool_def.get("function")
        if fn and isinstance(fn, dict):
            flat.append(
                {
                    "type": tool_def.get("type", "function"),
                    "name": fn["name"],
                    "description": fn.get("description", ""),
                    "parameters": fn.get("parameters", {}),
                }
            )
        else:
            # Already flat or unknown format — pass through
            flat.append(tool_def)
    return flat


# ---------------------------------------------------------------------------
# Data file generation
# ---------------------------------------------------------------------------


def _build_query(
    template: QueryTemplate,
    media_id: str | None,
    user_id: str | None,
    *,
    media_ids: list[str] | None = None,
    include_tool_definitions: bool = False,
    response_mode: str | None = None,
) -> dict | None:
    """Convert a template into a Foundry data row, or ``None`` if unmet.

    Parameters
    ----------
    media_id:
        Targeted video/media ID for this specific row (single-video queries).
    user_id:
        Runtime user ID recognized by the hosted agent.
    media_ids:
        Full list of available video/media IDs — included in the context
        envelope for multi-video queries (``needs_user=True``).
    response_mode:
        Optional response mode hint passed through to the context envelope.
        Deprecated for default evaluation generation so eval traffic mirrors
        the production/frontend request shape.
    """
    if template.needs_media and not media_id:
        logger.warning("Skipping query (needs media_id): %s", template.text[:60])
        return None
    if template.needs_user and not user_id:
        logger.warning("Skipping query (needs user_id): %s", template.text[:60])
        return None

    # Build context prefix
    ctx_media = media_id if template.needs_media else None
    ctx_user = user_id if (template.needs_user or template.needs_media) else None
    ctx_media_ids = media_ids if template.needs_user else None
    prefix = _format_context(
        ctx_media, ctx_user, media_ids=ctx_media_ids, response_mode=response_mode
    )

    row: dict = {"query": prefix + template.text}
    if template.ground_truth:
        row["ground_truth"] = template.ground_truth
    if include_tool_definitions:
        row["tool_definitions"] = _flatten_tool_definitions(TOOL_DEFINITIONS)

    return row


def generate_data_file(
    name: str,
    templates: list[QueryTemplate],
    evaluators: list[str],
    media_ids: list[str],
    user_id: str | None,
    *,
    include_tool_definitions: bool = False,
    response_mode: str | None = None,
) -> dict:
    """Generate a single Foundry evaluation data file structure.

    Video-specific templates (``needs_media=True``) are expanded across
    **all** available ``media_ids`` so that every configured test video
    receives independent evaluation coverage.

    Parameters
    ----------
    response_mode:
        Optional response mode override. Left unset by default so evaluation
        traffic mirrors the production/frontend hosted-agent path. This can
        still be used for targeted debugging while the adapter audit is in
        progress.
    """
    rows: list[dict] = []
    skipped = 0

    for template in templates:
        if template.needs_media and media_ids:
            # Expand video-specific queries: one row per configured video
            for mid in media_ids:
                row = _build_query(
                    template,
                    media_id=mid,
                    user_id=user_id,
                    media_ids=media_ids,
                    include_tool_definitions=include_tool_definitions,
                    response_mode=response_mode,
                )
                if row is None:
                    skipped += 1
                else:
                    rows.append(row)
        else:
            # General or multi-video (needs_user only) templates — single row
            row = _build_query(
                template,
                media_id=None,
                user_id=user_id,
                media_ids=media_ids,
                include_tool_definitions=include_tool_definitions,
                response_mode=response_mode,
            )
            if row is None:
                skipped += 1
            else:
                rows.append(row)

    logger.info(
        "Generated %d queries for '%s' (%d skipped due to missing config)",
        len(rows),
        name,
        skipped,
    )

    # Map tool_definitions from data items to the evaluator input when present.
    data_mapping: dict[str, str] = {}
    if include_tool_definitions:
        data_mapping["tool_definitions"] = "{{item.tool_definitions}}"

    return {
        "name": name,
        "evaluators": evaluators,
        "data": rows,
        "data_mapping": data_mapping,
        "evaluator_parameters": {},
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def _build_run_metadata(
    *,
    media_ids: list[str],
    user_id: str | None,
    eval_payloads: dict[str, dict],
) -> dict:
    """Build the reproducibility run-metadata document (F2).

    Captures the fields needed to compare a Foundry result row against another
    run of the same agent / dataset / judge configuration:

    * judge model + temperature + run count (from env, with defaults)
    * frame-sampling FPS / max frames / subtitle mode (from env)
    * agent commit SHA (``GITHUB_SHA`` in CI; ``HEAD`` locally if available)
    * stable hash of the generated eval payloads (so dataset drift is
      detectable without diffing JSON)
    * benchmark identifiers (``benchmark_name``, ``benchmark_version``) for
      runs gated through the benchmark adapters

    Read by ``microsoft/ai-agent-evals`` consumers / cluster-CSV analysis to
    bucket rows by ``[QPRISMA_BENCH]`` and judge configuration.
    """

    def _env(name: str, default: str | None = None) -> str | None:
        value = os.environ.get(name)
        return value if value not in (None, "") else default

    def _env_float(name: str) -> float | None:
        raw = _env(name)
        try:
            return float(raw) if raw is not None else None
        except ValueError:
            return None

    def _env_int(name: str) -> int | None:
        raw = _env(name)
        try:
            return int(raw) if raw is not None else None
        except ValueError:
            return None

    payload_bytes = json.dumps(eval_payloads, sort_keys=True).encode("utf-8")
    dataset_hash = hashlib.sha256(payload_bytes).hexdigest()

    return {
        "schema_version": 1,
        "created_at": datetime.now(UTC).isoformat(),
        "agent": {
            "name": _env("AGENT_NAME", "qprisma-video-agent"),
            "commit_sha": _env("GITHUB_SHA") or _env("AGENT_COMMIT_SHA"),
            "version_override": _env("AGENT_VERSION_OVERRIDE"),
        },
        "judge": {
            "model": _env("EVAL_JUDGE_MODEL", "gpt-5.5"),
            "temperature": _env_float("EVAL_JUDGE_TEMPERATURE") or 0.0,
            "n_runs": _env_int("EVAL_JUDGE_N_RUNS") or 1,
        },
        "frame_sampling": {
            "fps": _env_float("EVAL_FRAME_SAMPLING_FPS"),
            "max_frames": _env_int("EVAL_MAX_FRAMES"),
            "subtitle_mode": _env("EVAL_SUBTITLE_MODE"),
        },
        "dataset": {
            "hash": dataset_hash,
            "media_ids": media_ids,
            "user_id": user_id,
            "n_quality": len(eval_payloads.get("quality", {}).get("data", [])),
            "n_agent": len(eval_payloads.get("agent", {}).get("data", [])),
            "n_safety": len(eval_payloads.get("safety", {}).get("data", [])),
        },
        "benchmark": {
            "name": _env("EVAL_BENCHMARK_NAME"),
            "version": _env("EVAL_BENCHMARK_VERSION"),
            "manifest_path": _env("EVAL_BENCHMARK_MANIFEST"),
        },
        "github": {
            "run_id": _env("GITHUB_RUN_ID"),
            "run_attempt": _env("GITHUB_RUN_ATTEMPT"),
            "ref": _env("GITHUB_REF"),
            "workflow": _env("GITHUB_WORKFLOW"),
        },
    }


def main() -> int:
    """Entry point for data generation."""
    parser = argparse.ArgumentParser(description="Generate Azure AI Foundry evaluation data files")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).parent / "data",
        help="Directory to write generated JSON files (default: evaluation_foundry/data/)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print to stdout instead of writing files",
    )
    parser.add_argument(
        "--response-mode",
        choices=["full", "final_answer"],
        default=None,
        help=(
            "Optional response_mode override to embed in QPRISMA_CONTEXT. "
            "Omit to mirror the production/frontend hosted-agent path."
        ),
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    # Collect environment config
    media_ids = _collect_media_ids()
    user_id = _get_user_id()

    logger.info("Found %d media IDs", len(media_ids))
    logger.info("User ID configured: %s", "yes" if user_id else "NO")

    if not media_ids:
        logger.warning("No EVAL_MEDIA_ID_* variables set — video-specific queries will be skipped")
    elif len(media_ids) < 2:
        logger.warning(
            "Only %d video configured — multi-video/cross-video templates will run "
            "but won't exercise the intended cross-video agent path (needs ≥2 videos)",
            len(media_ids),
        )
    if not user_id:
        logger.warning("EVAL_USER_ID not set — multi-video and user-scoped queries will be skipped")
    elif _has_runtime_user_id_format(user_id):
        logger.info("EVAL_USER_ID matches the current hosted-agent runtime format")
    else:
        logger.warning(
            "EVAL_USER_ID is set to '%s'. Ensure this matches the current runtime user_id format "
            "accepted by the hosted agent for the target environment.",
            user_id,
        )

    # Generate text-quality evaluation data (no tool_definitions needed)
    quality = generate_data_file(
        name="qprisma-quality-eval",
        templates=ALL_GENERAL_TEMPLATES,
        evaluators=QUALITY_EVAL_EVALUATORS,
        media_ids=media_ids,
        user_id=user_id,
        response_mode=args.response_mode,
    )

    # Generate agent/tool evaluation data (includes flattened tool_definitions)
    agent = generate_data_file(
        name="qprisma-agent-eval",
        templates=ALL_GENERAL_TEMPLATES,
        evaluators=AGENT_EVAL_EVALUATORS,
        media_ids=media_ids,
        user_id=user_id,
        include_tool_definitions=True,
        response_mode=args.response_mode,
    )

    # Generate safety evaluation data
    safety = generate_data_file(
        name="qprisma-safety-eval",
        templates=ALL_SAFETY_TEMPLATES,
        evaluators=SAFETY_EVAL_EVALUATORS,
        media_ids=media_ids,
        user_id=user_id,
        response_mode=args.response_mode,
    )

    # Reproducibility manifest (F2): captures judge/sampling/agent provenance
    # so a Foundry run can be matched to an exact dataset snapshot, agent
    # commit, and frame-sampling configuration. Emitted alongside the eval
    # JSON files and uploaded as part of the ``eval-data`` artifact.
    run_metadata = _build_run_metadata(
        media_ids=media_ids,
        user_id=user_id,
        eval_payloads={"quality": quality, "agent": agent, "safety": safety},
    )

    if args.dry_run:
        print(
            json.dumps(
                {
                    "quality": quality,
                    "agent": agent,
                    "safety": safety,
                    "run_metadata": run_metadata,
                },
                indent=2,
            )
        )
        return 0

    # Write files
    args.output_dir.mkdir(parents=True, exist_ok=True)

    quality_path = args.output_dir / QUALITY_EVAL_FILE
    quality_path.write_text(json.dumps(quality, indent=2) + "\n", encoding="utf-8")
    logger.info("Wrote %s (%d queries)", quality_path, len(quality["data"]))

    agent_path = args.output_dir / AGENT_EVAL_FILE
    agent_path.write_text(json.dumps(agent, indent=2) + "\n", encoding="utf-8")
    logger.info("Wrote %s (%d queries)", agent_path, len(agent["data"]))

    safety_path = args.output_dir / SAFETY_EVAL_FILE
    safety_path.write_text(json.dumps(safety, indent=2) + "\n", encoding="utf-8")
    logger.info("Wrote %s (%d queries)", safety_path, len(safety["data"]))

    metadata_path = args.output_dir / "run-metadata.json"
    metadata_path.write_text(json.dumps(run_metadata, indent=2) + "\n", encoding="utf-8")
    logger.info("Wrote %s", metadata_path)

    # Summary
    total = len(quality["data"]) + len(agent["data"]) + len(safety["data"])
    print(f"\n✅ Generated {total} evaluation queries across {len(media_ids)} video(s):")
    print(f"   Quality: {len(quality['data'])} queries → {quality_path}")
    print(f"   Agent:   {len(agent['data'])} queries → {agent_path}")
    print(f"   Safety:  {len(safety['data'])} queries → {safety_path}")
    if media_ids:
        print("\n   Videos under test:")
        for i, mid in enumerate(media_ids, 1):
            print(f"     {i}. {mid}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
