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
    ENV_MEDIA_ID_PREFIX,
    ENV_USER_ID,
    GENERAL_EVAL_EVALUATORS,
    GENERAL_EVAL_FILE,
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


def _format_context(media_id: str | None, user_id: str | None) -> str:
    """Build the QPRISMA_CONTEXT prefix string."""
    parts: dict[str, str] = {}
    if media_id:
        parts["media_id"] = media_id
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
# Data file generation
# ---------------------------------------------------------------------------


def _build_query(
    template: QueryTemplate,
    media_ids: list[str],
    user_id: str | None,
    *,
    include_tool_definitions: bool = False,
) -> dict | None:
    """Convert a template into a Foundry data row, or None if requirements unmet."""
    # Check requirements
    if template.needs_media and not media_ids:
        logger.warning("Skipping query (needs media_id): %s", template.text[:60])
        return None
    if template.needs_user and not user_id:
        logger.warning("Skipping query (needs user_id): %s", template.text[:60])
        return None

    # Build context prefix
    ctx_media = media_ids[0] if template.needs_media else None
    ctx_user = user_id if (template.needs_user or template.needs_media) else None
    prefix = _format_context(ctx_media, ctx_user)

    row: dict = {"query": prefix + template.text}
    if template.ground_truth:
        row["ground_truth"] = template.ground_truth
    if include_tool_definitions:
        row["tool_definitions"] = TOOL_DEFINITIONS

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
    """Generate a single Foundry evaluation data file structure."""
    rows: list[dict] = []
    skipped = 0

    for template in templates:
        row = _build_query(
            template,
            media_ids,
            user_id,
            include_tool_definitions=include_tool_definitions,
        )
        if row is None:
            skipped += 1
            continue
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
    if not user_id:
        logger.warning("EVAL_USER_ID not set — multi-video and user-scoped queries will be skipped")

    # Generate general evaluation data (includes tool_definitions for tool evaluators)
    general = generate_data_file(
        name="qprisma-general-eval",
        templates=ALL_GENERAL_TEMPLATES,
        evaluators=GENERAL_EVAL_EVALUATORS,
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
        print(json.dumps({"general": general, "safety": safety}, indent=2))
        return 0

    # Write files
    args.output_dir.mkdir(parents=True, exist_ok=True)

    general_path = args.output_dir / GENERAL_EVAL_FILE
    general_path.write_text(json.dumps(general, indent=2) + "\n", encoding="utf-8")
    logger.info("Wrote %s (%d queries)", general_path, len(general["data"]))

    safety_path = args.output_dir / SAFETY_EVAL_FILE
    safety_path.write_text(json.dumps(safety, indent=2) + "\n", encoding="utf-8")
    logger.info("Wrote %s (%d queries)", safety_path, len(safety["data"]))

    # Summary
    total = len(general["data"]) + len(safety["data"])
    print(f"\n✅ Generated {total} evaluation queries:")
    print(f"   General: {len(general['data'])} queries → {general_path}")
    print(f"   Safety:  {len(safety['data'])} queries → {safety_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
