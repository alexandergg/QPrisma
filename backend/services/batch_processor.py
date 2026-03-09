"""
Azure OpenAI Batch Processing Service

Uses Azure OpenAI Global Batch deployments for 50% cost savings.
All vision analysis goes through Batch API.
"""

import asyncio
import json
import logging
import os
import tempfile
import time
from typing import Any

import aiofiles
from openai import APIConnectionError, APIError, AsyncAzureOpenAI, AzureOpenAI, RateLimitError

from core.config import settings

logger = logging.getLogger(__name__)


class BatchProcessor:
    """
    Process frame analysis using Azure OpenAI Global Batch API.

    Benefits:
    - 50% cheaper than regular API
    - No restrictive rate limits
    - Ideal for video processing

    Requires:
    - A "Global Batch" deployment in Azure OpenAI Studio
    - AZURE_OPENAI_DEPLOYMENT_GPT_BATCH environment variable configured
    """

    # Pricing (batch = 50% of regular)
    COST_PER_1K_INPUT = 0.0025  # $2.50 per 1M input tokens
    COST_PER_1K_OUTPUT = 0.01  # $10.00 per 1M output tokens

    # Estimates
    AVG_INPUT_TOKENS_PER_FRAME = 1000
    AVG_OUTPUT_TOKENS_PER_FRAME = 150

    def __init__(self, openai_client: AzureOpenAI | AsyncAzureOpenAI):
        self.client = openai_client

        # Global Batch deployment (required)
        self.gpt_deployment = settings.azure.openai_deployment_gpt_batch
        if not self.gpt_deployment:
            logger.warning(
                "AZURE_OPENAI_DEPLOYMENT_GPT_BATCH not set. "
                "Create a 'Global Batch' deployment in Azure OpenAI Studio."
            )
            # Fallback to standard deployment
            self.gpt_deployment = settings.azure.openai_deployment_gpt

        self.embedding_deployment = settings.azure.openai_deployment_embedding

    def estimate_cost(self, frame_count: int) -> dict[str, float]:
        """Estimate batch processing cost."""
        input_tokens = frame_count * self.AVG_INPUT_TOKENS_PER_FRAME
        output_tokens = frame_count * self.AVG_OUTPUT_TOKENS_PER_FRAME

        input_cost = (input_tokens / 1000) * self.COST_PER_1K_INPUT
        output_cost = (output_tokens / 1000) * self.COST_PER_1K_OUTPUT

        return {
            "estimated_tokens": input_tokens + output_tokens,
            "estimated_cost_usd": round(input_cost + output_cost, 4),
            "savings_vs_regular_usd": round(input_cost + output_cost, 4),  # 50% savings
        }

    # Structured JSON schema for vision analysis output
    FRAME_ANALYSIS_SCHEMA = {
        "type": "json_schema",
        "json_schema": {
            "name": "frame_analysis",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    "scene_description": {
                        "type": "object",
                        "properties": {
                            "setting": {"type": "string"},
                            "lighting": {"type": "string"},
                            "atmosphere": {"type": "string"},
                            "visual_style": {"type": "string"},
                        },
                        "required": ["setting", "lighting", "atmosphere", "visual_style"],
                        "additionalProperties": False,
                    },
                    "people": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "description": {"type": "string"},
                                "role": {"type": "string"},
                                "emotion": {"type": "string"},
                                "name": {"type": ["string", "null"]},
                            },
                            "required": ["description", "role", "emotion", "name"],
                            "additionalProperties": False,
                        },
                    },
                    "ocr_text": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "visual_elements": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "actions": {"type": "string"},
                    "topics": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "keywords": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "questions_answered": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "required": [
                    "scene_description",
                    "people",
                    "ocr_text",
                    "visual_elements",
                    "actions",
                    "topics",
                    "keywords",
                    "questions_answered",
                ],
                "additionalProperties": False,
            },
        },
    }

    def create_vision_batch_requests(
        self, frames_data: list[dict], custom_prompt: str | None = None
    ) -> list[dict]:
        """
        Create requests in JSONL format for batch processing.

        Uses structured JSON output (response_format) for reliable parsing,
        lower token usage, and direct mapping to Knowledge Graph entities.

        Args:
            frames_data: List of frames with image_base64.
            custom_prompt: Custom prompt (disables structured output).

        Returns:
            List of requests in batch API format.
        """
        default_prompt = """You are analyzing frame #{frame_number} at timestamp {timestamp}s of a video. Provide a comprehensive analysis optimized for semantic search and RAG retrieval.

Analyze the frame and return a JSON object with these fields:

- scene_description: Object with setting (indoor/outdoor, environment type), lighting (conditions), atmosphere (mood, energy), visual_style (cinematic, casual, professional, etc.)
- people: Array of people visible. For each: description (appearance, age range, gender, clothing), role (presenter, interviewer, audience, etc.), emotion (facial expression, apparent mood), name (from name tags/lower-thirds, or null)
- ocr_text: Array of ALL visible text exactly as shown — slide titles, bullet points, UI elements, signs, labels, watermarks. Use exact quotes.
- visual_elements: Array of key objects, products, devices, brand logos, charts/graphs, animations
- actions: String describing what is happening — use specific verbs (presenting, demonstrating, explaining, comparing)
- topics: Array of 3-5 key topics/concepts (e.g., "cloud computing", "product launch")
- keywords: Array of 8-12 searchable keywords/phrases including proper nouns, technical terms, action descriptions
- questions_answered: Array of 2-3 questions this frame helps answer

Be thorough but factual. Prioritize information that would help users find this specific moment."""

        requests = []
        for idx, frame_data in enumerate(frames_data):
            prompt_text = custom_prompt or default_prompt
            frame_num = frame_data.get("frame_number", idx)
            timestamp = frame_data.get("timestamp", 0)
            prompt_text = prompt_text.replace("{frame_number}", str(frame_num))
            prompt_text = prompt_text.replace("{timestamp}", str(timestamp))

            body: dict[str, Any] = {
                "model": self.gpt_deployment,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt_text},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:{frame_data.get('media_type', 'image/jpeg')};base64,{frame_data['image_base64']}"
                                },
                            },
                        ],
                    }
                ],
                "max_completion_tokens": frame_data.get("max_tokens", 900),
            }

            # Use structured output only with default prompt (custom prompts
            # may not match the schema)
            if custom_prompt is None:
                body["response_format"] = self.FRAME_ANALYSIS_SCHEMA

            request = {
                "custom_id": f"frame_{frame_data.get('frame_number', idx)}",
                "method": "POST",
                "url": "/chat/completions",
                "body": body,
            }
            requests.append(request)

        return requests

    async def submit_batch_job(
        self, requests: list[dict[str, Any]], description: str = "Video frame analysis"
    ) -> str:
        """
        Submit a batch job to Azure OpenAI.

        Args:
            requests: List of requests in batch API format.
            description: Batch job description.

        Returns:
            batch_id of the created job.

        Raises:
            APIError: If there is an API error.
            OSError: If there is an error writing the temporary file.
        """
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            for request in requests:
                f.write(json.dumps(request) + "\n")
            temp_path = f.name

        try:
            logger.info(f"Uploading batch file ({len(requests)} requests)")
            async with aiofiles.open(temp_path, "rb") as f:
                file_content = await f.read()

            batch_file = await self.client.files.create(
                file=(os.path.basename(temp_path), file_content), purpose="batch"
            )

            logger.info(f"Creating batch job with file {batch_file.id}")
            batch = await self.client.batches.create(
                input_file_id=batch_file.id,
                endpoint="/chat/completions",
                completion_window="24h",
                metadata={"description": description},
            )

            logger.info(f"Batch job created: {batch.id} ({batch.request_counts.total} requests)")
            return batch.id

        except (APIError, APIConnectionError, RateLimitError) as e:
            logger.error(f"OpenAI API error submitting batch: {e}")
            raise
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)

    async def check_batch_status(self, batch_id: str) -> dict[str, Any]:
        """
        Check the status of a batch job.

        Args:
            batch_id: Batch job ID.

        Returns:
            Dictionary with batch status.
        """
        batch = await self.client.batches.retrieve(batch_id)

        return {
            "id": batch.id,
            "status": batch.status,
            "created_at": batch.created_at,
            "completed_at": batch.completed_at,
            "request_counts": {
                "total": batch.request_counts.total,
                "completed": batch.request_counts.completed,
                "failed": batch.request_counts.failed,
            },
        }

    async def wait_for_batch_completion(
        self, batch_id: str, check_interval: int = 10, max_wait_time: int = 3600
    ) -> bool:
        """
        Wait for a batch job to complete with exponential backoff.

        Args:
            batch_id: Batch job ID.
            check_interval: Initial check interval in seconds.
            max_wait_time: Maximum wait time in seconds.

        Returns:
            True if completed successfully, False if failed or timed out.
        """
        logger.info(f"Waiting for batch {batch_id} to complete")
        start_time = time.time()
        current_interval = float(check_interval)
        max_interval = 120.0  # Cap at 2 minutes between polls
        backoff_factor = 1.5

        while True:
            elapsed = time.time() - start_time

            if elapsed > max_wait_time:
                logger.error(f"Batch timeout after {max_wait_time}s")
                return False

            try:
                status_info = await self.check_batch_status(batch_id)
            except (APIError, APIConnectionError) as e:
                logger.warning(f"Error checking batch status: {e}, retrying...")
                await asyncio.sleep(current_interval)
                current_interval = min(current_interval * backoff_factor, max_interval)
                continue

            status = status_info["status"]
            completed = status_info["request_counts"]["completed"]
            total = status_info["request_counts"]["total"]

            logger.info(
                f"Batch status: {status} ({completed}/{total}) "
                f"- {elapsed:.0f}s elapsed, next check in {current_interval:.0f}s"
            )

            if status == "completed":
                logger.info("Batch completed successfully")
                return True
            elif status in ["failed", "expired", "cancelled"]:
                logger.error(f"Batch failed with status: {status}")
                return False

            await asyncio.sleep(current_interval)
            current_interval = min(current_interval * backoff_factor, max_interval)

    async def get_batch_results(self, batch_id: str) -> list[dict[str, Any]]:
        """
        Get results from a completed batch job.

        Args:
            batch_id: Batch job ID.

        Returns:
            List of batch results.

        Raises:
            ValueError: If the batch is not completed or there is no output file.
        """
        batch = await self.client.batches.retrieve(batch_id)

        if batch.status != "completed":
            raise ValueError(f"Batch not completed: {batch.status}")

        if not batch.output_file_id:
            raise ValueError("No output file available")

        logger.info("Downloading batch results")
        file_response = await self.client.files.content(batch.output_file_id)

        results: list[dict[str, Any]] = []
        for line in file_response.text.strip().split("\n"):
            if line:
                results.append(json.loads(line))

        logger.info(f"Retrieved {len(results)} results")
        return results

    def parse_vision_results(self, results: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        """
        Parse vision analysis results.

        Handles both structured JSON output (response_format) and plain text
        responses (custom prompts). For JSON responses, the analysis field
        contains both the parsed dict and a flattened text version for embeddings.

        Args:
            results: List of batch API results.

        Returns:
            Dictionary mapping custom_id to parsed results.
        """
        parsed: dict[str, dict[str, Any]] = {}

        for result in results:
            custom_id = result.get("custom_id")

            if result.get("response", {}).get("status_code") == 200:
                body = result["response"]["body"]
                content = body["choices"][0]["message"]["content"]
                tokens = body.get("usage", {}).get("total_tokens", 0)

                # Try parsing as structured JSON, fall back to plain text
                analysis_structured = None
                analysis_text = content
                try:
                    analysis_structured = json.loads(content)
                    # Build a flattened text version for embedding generation
                    analysis_text = self._structured_to_text(analysis_structured)
                except (json.JSONDecodeError, TypeError):
                    pass  # Plain text response (custom prompt)

                parsed[custom_id] = {
                    "analysis": analysis_text,
                    "analysis_structured": analysis_structured,
                    "tokens_used": tokens,
                    "success": True,
                }
            else:
                parsed[custom_id] = {
                    "analysis": None,
                    "analysis_structured": None,
                    "tokens_used": 0,
                    "success": False,
                    "error": result.get("error", {}).get("message", "Unknown error"),
                }

        return parsed

    @staticmethod
    def _structured_to_text(data: dict[str, Any]) -> str:
        """
        Flatten structured JSON analysis into text for embedding generation.

        Converts the JSON schema output into a coherent text representation
        that produces high-quality embeddings for semantic search.
        """
        parts: list[str] = []

        scene = data.get("scene_description", {})
        if scene:
            parts.append(
                f"Scene: {scene.get('setting', '')}. "
                f"Lighting: {scene.get('lighting', '')}. "
                f"Atmosphere: {scene.get('atmosphere', '')}. "
                f"Style: {scene.get('visual_style', '')}."
            )

        people = data.get("people", [])
        if people:
            for person in people:
                name = person.get("name") or "Unknown"
                parts.append(
                    f"Person: {name} — {person.get('description', '')}. "
                    f"Role: {person.get('role', '')}. Emotion: {person.get('emotion', '')}."
                )

        ocr = data.get("ocr_text", [])
        if ocr:
            parts.append(f"On-screen text: {'; '.join(ocr)}")

        elements = data.get("visual_elements", [])
        if elements:
            parts.append(f"Visual elements: {', '.join(elements)}")

        actions = data.get("actions", "")
        if actions:
            parts.append(f"Actions: {actions}")

        topics = data.get("topics", [])
        if topics:
            parts.append(f"Topics: {', '.join(topics)}")

        keywords = data.get("keywords", [])
        if keywords:
            parts.append(f"Keywords: {', '.join(keywords)}")

        questions = data.get("questions_answered", [])
        if questions:
            parts.append(f"Questions answered: {'; '.join(questions)}")

        return " ".join(parts)

    async def cancel_batch(self, batch_id: str):
        """Cancel a batch job in progress."""
        await self.client.batches.cancel(batch_id)
        logger.info(f"Batch {batch_id} cancelled")
