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
    EVAL_MEDIA_ID_1, EVAL_MEDIA_ID_2, ...  — UUIDs of uploaded test videos
    EVAL_USER_ID                            — Entra Object ID of the video uploader
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

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

# ---------------------------------------------------------------------------
# QPRISMA_CONTEXT formatting
# ---------------------------------------------------------------------------

CONTEXT_PREFIX = "[QPRISMA_CONTEXT:{ctx}]\n"


def _format_context(
    media_id: str | None,
    user_id: str | None,
    *,
    media_ids: list[str] | None = None,
) -> str:
    """Build the QPRISMA_CONTEXT prefix string.

    Parameters
    ----------
    media_id:
        Single video UUID for single-video queries.
    user_id:
        Entra Object-ID of the video owner.
    media_ids:
        Full list of video UUIDs for multi-video / cross-video queries.
    """
    parts: dict[str, str | list[str]] = {}
    if media_id:
        parts["media_id"] = media_id
    if media_ids:
        parts["media_ids"] = media_ids
    if user_id:
        parts["user_id"] = user_id
    if not parts:
        return ""
    return CONTEXT_PREFIX.format(ctx=json.dumps(parts, separators=(",", ":")))


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
) -> dict | None:
    """Convert a template into a Foundry data row, or ``None`` if unmet.

    Parameters
    ----------
    media_id:
        Targeted video UUID for this specific row (single-video queries).
    user_id:
        Entra Object-ID of the video owner.
    media_ids:
        Full list of available video UUIDs — included in the context
        envelope for multi-video queries (``needs_user=True``).
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
    prefix = _format_context(ctx_media, ctx_user, media_ids=ctx_media_ids)

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
) -> dict:
    """Generate a single Foundry evaluation data file structure.

    Video-specific templates (``needs_media=True``) are expanded across
    **all** available ``media_ids`` so that every configured test video
    receives independent evaluation coverage.
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

    # Generate text-quality evaluation data (no tool_definitions needed)
    quality = generate_data_file(
        name="qprisma-quality-eval",
        templates=ALL_GENERAL_TEMPLATES,
        evaluators=QUALITY_EVAL_EVALUATORS,
        media_ids=media_ids,
        user_id=user_id,
    )

    # Generate agent/tool evaluation data (includes flattened tool_definitions)
    agent = generate_data_file(
        name="qprisma-agent-eval",
        templates=ALL_GENERAL_TEMPLATES,
        evaluators=AGENT_EVAL_EVALUATORS,
        media_ids=media_ids,
        user_id=user_id,
        include_tool_definitions=True,
    )

    # Generate safety evaluation data
    safety = generate_data_file(
        name="qprisma-safety-eval",
        templates=ALL_SAFETY_TEMPLATES,
        evaluators=SAFETY_EVAL_EVALUATORS,
        media_ids=media_ids,
        user_id=user_id,
    )

    if args.dry_run:
        print(json.dumps({"quality": quality, "agent": agent, "safety": safety}, indent=2))
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

    # Summary
    total = len(quality["data"]) + len(agent["data"]) + len(safety["data"])
    print(f"\n✅ Generated {total} evaluation queries across {len(media_ids)} video(s):")
    print(f"   Quality: {len(quality['data'])} queries → {quality_path}")
    print(f"   Agent:   {len(agent['data'])} queries → {agent_path}")
    print(f"   Safety:  {len(safety['data'])} queries → {safety_path}")
    if media_ids:
        print(f"\n   Videos under test:")
        for i, mid in enumerate(media_ids, 1):
            print(f"     {i}. {mid}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
