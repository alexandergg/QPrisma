"""
Step 2: Download completed batch results from OpenAI.

Polls for batch completion with exponential backoff,
then downloads result files.
"""

import asyncio
import json
import logging
from pathlib import Path

from openai import AsyncOpenAI

logger = logging.getLogger(__name__)


async def download_batch_results(
    client: AsyncOpenAI,
    batch_ids: list[str],
    output_dir: Path,
    poll_interval: float = 30.0,
    max_poll_interval: float = 300.0,
    timeout: float = 86400.0,  # 24 hours
) -> list[Path]:
    """Poll for batch completion and download result files.

    Args:
        client: OpenAI async client.
        batch_ids: List of batch job IDs to monitor.
        output_dir: Directory to save result files.
        poll_interval: Initial polling interval in seconds.
        max_poll_interval: Maximum polling interval (exponential backoff).
        timeout: Maximum total wait time in seconds.

    Returns:
        List of paths to downloaded result JSONL files.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    pending = set(batch_ids)
    result_paths: list[Path] = []
    elapsed = 0.0
    current_interval = poll_interval

    while pending and elapsed < timeout:
        completed_this_round = []

        for batch_id in list(pending):
            batch = await client.batches.retrieve(batch_id)
            status = batch.status

            if status == "completed":
                path = await _download_output(
                    client, batch.output_file_id, batch_id, output_dir
                )
                result_paths.append(path)
                completed_this_round.append(batch_id)
                logger.info("Batch %s completed -> %s", batch_id, path)

            elif status == "failed":
                logger.error(
                    "Batch %s failed: %s", batch_id, getattr(batch, "errors", "unknown")
                )
                completed_this_round.append(batch_id)

            elif status == "expired":
                logger.error("Batch %s expired", batch_id)
                completed_this_round.append(batch_id)

            elif status in ("cancelled", "cancelling"):
                logger.warning("Batch %s was cancelled", batch_id)
                completed_this_round.append(batch_id)

            else:
                # in_progress, validating, finalizing
                counts = batch.request_counts
                if counts:
                    logger.info(
                        "Batch %s: %s (completed=%d, failed=%d, total=%d)",
                        batch_id,
                        status,
                        counts.completed,
                        counts.failed,
                        counts.total,
                    )

        for bid in completed_this_round:
            pending.discard(bid)

        if pending:
            await asyncio.sleep(current_interval)
            elapsed += current_interval
            current_interval = min(current_interval * 1.5, max_poll_interval)

    if pending:
        logger.warning("Timed out waiting for batches: %s", pending)

    return result_paths


async def _download_output(
    client: AsyncOpenAI,
    output_file_id: str,
    batch_id: str,
    output_dir: Path,
) -> Path:
    """Download a batch output file."""
    content = await client.files.content(output_file_id)
    output_path = output_dir / f"results_{batch_id}.jsonl"

    with open(output_path, "wb") as f:
        f.write(content.content)

    return output_path
