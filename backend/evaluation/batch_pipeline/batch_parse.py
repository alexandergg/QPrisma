"""
Step 3: Parse and validate batch result files.

Validates each response against expected Pydantic schemas.
Malformed responses are logged and skipped.
"""

import json
import logging
from pathlib import Path

from evaluation.models.eval_schemas import (
    JudgeResponse,
    QuantitativeJudgeResponse,
    WinRateJudgeResponse,
)

logger = logging.getLogger(__name__)


async def parse_batch_results(
    result_paths: list[Path],
    model: str = "gpt-4o",
) -> list[JudgeResponse]:
    """Parse all batch result files into JudgeResponse objects.

    Args:
        result_paths: Paths to JSONL result files.
        model: Model name (reserved for future retry support).

    Returns:
        List of parsed JudgeResponse objects.

    Note:
        Malformed responses are logged and skipped. Automatic retry of
        malformed responses requires storing the original input JSONL
        alongside result files, which is not yet implemented.
    """
    all_responses: list[JudgeResponse] = []
    malformed_count = 0

    for path in result_paths:
        responses, malformed = await _parse_single_file(path)
        all_responses.extend(responses)
        malformed_count += malformed

    logger.info(
        "Parsed %d responses total (%d malformed skipped)",
        len(all_responses),
        malformed_count,
    )
    return all_responses


async def _parse_single_file(
    path: Path,
) -> tuple[list[JudgeResponse], int]:
    """Parse a single JSONL result file."""
    responses = []
    malformed = 0

    with open(path, encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue

            try:
                result = json.loads(line)
                parsed = _parse_single_result(result)
                if parsed:
                    responses.append(parsed)
                else:
                    malformed += 1
                    logger.debug(
                        "Malformed response on line %d in %s (custom_id=%s)",
                        line_num,
                        path,
                        result.get("custom_id", "?"),
                    )

            except (json.JSONDecodeError, KeyError, ValueError) as e:
                logger.warning("Failed to parse line %d in %s: %s", line_num, path, e)
                malformed += 1

    return responses, malformed


def _parse_single_result(result: dict) -> JudgeResponse | None:
    """Parse a single batch API result into a JudgeResponse."""
    custom_id = result.get("custom_id", "")
    parts = custom_id.split("++")

    response_body = result.get("response", {}).get("body", {})
    choices = response_body.get("choices", [])
    if not choices:
        return None

    content = choices[0].get("message", {}).get("content", "")
    if not content:
        return None

    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        return None

    # Determine if this is winrate or quantitative based on custom_id structure
    is_winrate = "ori" in custom_id or "reversed" in custom_id or len(parts) >= 5

    if is_winrate:
        return _parse_winrate_result(parts, data)
    else:
        return _parse_quantitative_result(parts, data)


def _parse_winrate_result(parts: list[str], data: dict) -> JudgeResponse | None:
    """Parse a win-rate result."""
    try:
        winrate_response = WinRateJudgeResponse.model_validate(data)
    except (ValueError, KeyError) as e:
        logger.debug("Win-rate validation failed: %s", e)
        return None

    question_id = parts[0] if parts else "unknown"
    method_a = parts[1] if len(parts) > 1 else "unknown"
    method_b = parts[2] if len(parts) > 2 else "unknown"
    run_part = parts[3] if len(parts) > 3 else "run0"
    ordering = parts[4] if len(parts) > 4 else "original"

    run_index = int(run_part.replace("run", "")) if run_part.startswith("run") else 0

    return JudgeResponse(
        question_id=question_id,
        run_index=run_index,
        ordering=ordering,
        method_a=method_a,
        method_b=method_b,
        winrate_response=winrate_response,
        raw_response=json.dumps(data),
    )


def _parse_quantitative_result(parts: list[str], data: dict) -> JudgeResponse | None:
    """Parse a quantitative result."""
    try:
        quant_response = QuantitativeJudgeResponse.model_validate(data)
    except (ValueError, KeyError) as e:
        logger.debug("Quantitative validation failed: %s", e)
        return None

    question_id = parts[0] if parts else "unknown"
    method = parts[1] if len(parts) > 1 else "unknown"
    baseline = parts[2] if len(parts) > 2 else "unknown"
    run_part = parts[3] if len(parts) > 3 else "run0"

    run_index = int(run_part.replace("run", "")) if run_part.startswith("run") else 0

    return JudgeResponse(
        question_id=question_id,
        run_index=run_index,
        ordering="original",
        method_a=method,
        method_b=baseline,
        quantitative_response=quant_response,
        raw_response=json.dumps(data),
    )
