"""
LLM-as-Judge evaluation using GPT-4o with structured Pydantic output.

Provides the core judge interface used by both win-rate and quantitative
evaluation protocols. Supports position debiasing and retry on malformed output.
"""

import json
import logging
from pathlib import Path

from openai import AsyncOpenAI
from pydantic import BaseModel

from evaluation.models.eval_schemas import (
    JudgeResponse,
    QuantitativeJudgeResponse,
    WinRateJudgeResponse,
)

logger = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).parent / "prompts"


class LLMJudge:
    """GPT-4o judge for evaluating video understanding answers."""

    def __init__(
        self,
        client: AsyncOpenAI,
        model: str = "gpt-4o",
        max_retries: int = 3,
    ):
        self.client = client
        self.model = model
        self.max_retries = max_retries
        self._winrate_prompt = (PROMPTS_DIR / "winrate.txt").read_text()
        self._quantitative_prompt = (PROMPTS_DIR / "quantitative.txt").read_text()

    async def judge_winrate(
        self,
        question: str,
        answer_1: str,
        answer_2: str,
        method_1: str,
        method_2: str,
        question_id: str,
        run_index: int = 0,
        ordering: str = "original",
    ) -> JudgeResponse:
        """Run pairwise A/B comparison.

        Args:
            question: The benchmark question.
            answer_1: First answer (displayed as "Answer 1").
            answer_2: Second answer (displayed as "Answer 2").
            method_1: Name of method that produced answer_1.
            method_2: Name of method that produced answer_2.
            question_id: Unique question ID.
            run_index: Which evaluation run (0-indexed).
            ordering: "original" or "reversed" for position debiasing.

        Returns:
            JudgeResponse with winrate_response populated.
        """
        prompt = self._winrate_prompt.format(
            question=question,
            answer_1=answer_1,
            answer_2=answer_2,
        )

        response = await self._call_structured(prompt, WinRateJudgeResponse)

        return JudgeResponse(
            question_id=question_id,
            run_index=run_index,
            ordering=ordering,
            method_a=method_1,
            method_b=method_2,
            winrate_response=response,
            judge_model=self.model,
        )

    async def judge_quantitative(
        self,
        question: str,
        evaluated_answer: str,
        baseline_answer: str,
        method: str,
        baseline_method: str,
        question_id: str,
        run_index: int = 0,
    ) -> JudgeResponse:
        """Run 1-5 quantitative scoring against baseline.

        Args:
            question: The benchmark question.
            evaluated_answer: Answer being evaluated.
            baseline_answer: Baseline answer for comparison.
            method: Name of evaluated method.
            baseline_method: Name of baseline method.
            question_id: Unique question ID.
            run_index: Which evaluation run (0-indexed).

        Returns:
            JudgeResponse with quantitative_response populated.
        """
        prompt = self._quantitative_prompt.format(
            question=question,
            evaluated_answer=evaluated_answer,
            baseline_answer=baseline_answer,
        )

        response = await self._call_structured(prompt, QuantitativeJudgeResponse)

        return JudgeResponse(
            question_id=question_id,
            run_index=run_index,
            ordering="original",
            method_a=method,
            method_b=baseline_method,
            quantitative_response=response,
            judge_model=self.model,
        )

    async def _call_structured(
        self,
        prompt: str,
        response_model: type[BaseModel],
    ) -> BaseModel:
        """Call OpenAI with structured output enforcement.

        Retries up to max_retries on parse failures.
        """
        for attempt in range(self.max_retries):
            try:
                response = await self.client.beta.chat.completions.parse(
                    model=self.model,
                    messages=[{"role": "user", "content": prompt}],
                    response_format=response_model,
                )
                parsed = response.choices[0].message.parsed
                if parsed is not None:
                    return parsed

                # Fallback: try manual parse from content
                content = response.choices[0].message.content
                if content:
                    return response_model.model_validate_json(content)

            except Exception as e:
                logger.warning(
                    "Judge call attempt %d/%d failed: %s",
                    attempt + 1,
                    self.max_retries,
                    e,
                )
                if attempt == self.max_retries - 1:
                    raise

        raise RuntimeError(f"Judge failed after {self.max_retries} attempts")


def build_winrate_batch_request(
    question_id: str,
    question: str,
    answer_1: str,
    answer_2: str,
    method_1: str,
    method_2: str,
    run_index: int,
    ordering: str,
    model: str = "gpt-4o",
) -> dict:
    """Build a single batch API request for win-rate evaluation.

    Returns a dict in OpenAI Batch API format for batch_upload.

    Args:
        question_id: Unique question ID.
        question: The benchmark question.
        answer_1: First answer text.
        answer_2: Second answer text.
        method_1: Method name for answer_1.
        method_2: Method name for answer_2.
        run_index: Evaluation run index.
        ordering: "original" or "reversed".
        model: Judge model to use.

    Returns:
        Dict formatted for OpenAI Batch API JSONL.
    """
    prompt_template = (PROMPTS_DIR / "winrate.txt").read_text()
    prompt = prompt_template.format(
        question=question,
        answer_1=answer_1,
        answer_2=answer_2,
    )

    custom_id = f"{question_id}++{method_1}++{method_2}++run{run_index}++{ordering}"

    return {
        "custom_id": custom_id,
        "method": "POST",
        "url": "/v1/chat/completions",
        "body": {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "WinRateJudgeResponse",
                    "schema": WinRateJudgeResponse.model_json_schema(),
                },
            },
        },
    }


def build_quantitative_batch_request(
    question_id: str,
    question: str,
    evaluated_answer: str,
    baseline_answer: str,
    method: str,
    baseline_method: str,
    run_index: int,
    model: str = "gpt-4o",
) -> dict:
    """Build a single batch API request for quantitative evaluation.

    Returns a dict in OpenAI Batch API format for batch_upload.
    """
    prompt_template = (PROMPTS_DIR / "quantitative.txt").read_text()
    prompt = prompt_template.format(
        question=question,
        evaluated_answer=evaluated_answer,
        baseline_answer=baseline_answer,
    )

    custom_id = f"{question_id}++{method}++{baseline_method}++run{run_index}"

    return {
        "custom_id": custom_id,
        "method": "POST",
        "url": "/v1/chat/completions",
        "body": {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "QuantitativeJudgeResponse",
                    "schema": QuantitativeJudgeResponse.model_json_schema(),
                },
            },
        },
    }
