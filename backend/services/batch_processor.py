"""
Azure OpenAI Batch Processing Service

Uses Azure OpenAI Global Batch deployments for 50% cost savings.
All vision analysis goes through Batch API.
"""

import json
import logging
import os
import tempfile
import time
from typing import Any

from openai import AzureOpenAI

logger = logging.getLogger(__name__)


class BatchProcessor:
    """
    Procesa análisis de frames usando Azure OpenAI Global Batch API.

    Beneficios:
    - 50% más barato que API regular
    - Sin rate limits restrictivos
    - Ideal para procesamiento de video
    
    Requiere:
    - Un deployment tipo "Global Batch" en Azure OpenAI Studio
    - Variable AZURE_OPENAI_DEPLOYMENT_GPT_BATCH configurada
    """

    # Pricing (batch = 50% of regular)
    COST_PER_1K_INPUT = 0.0025   # $2.50 per 1M input tokens
    COST_PER_1K_OUTPUT = 0.01    # $10.00 per 1M output tokens
    
    # Estimates
    AVG_INPUT_TOKENS_PER_FRAME = 1000
    AVG_OUTPUT_TOKENS_PER_FRAME = 150

    def __init__(self, openai_client: AzureOpenAI):
        self.client = openai_client
        
        # Global Batch deployment (required)
        self.gpt_deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT_GPT_BATCH")
        if not self.gpt_deployment:
            logger.warning(
                "AZURE_OPENAI_DEPLOYMENT_GPT_BATCH not set. "
                "Create a 'Global Batch' deployment in Azure OpenAI Studio."
            )
            # Fallback to standard deployment
            self.gpt_deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT_GPT", "gpt-4o")
        
        self.embedding_deployment = os.getenv(
            "AZURE_OPENAI_DEPLOYMENT_EMBEDDING", "text-embedding-3-large"
        )

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

    def create_vision_batch_requests(
        self, frames_data: list[dict], custom_prompt: str | None = None
    ) -> list[dict]:
        """
        Crea requests en formato JSONL para batch processing.

        Args:
            frames_data: Lista de frames con image_base64
            custom_prompt: Prompt personalizado

        Returns:
            Lista de requests en formato batch API
        """
        default_prompt = """You are analyzing frame #{frame_number} at timestamp {timestamp}s of a video. Provide a comprehensive analysis optimized for semantic search and RAG retrieval.

## SCENE DESCRIPTION
Describe the overall scene: setting (indoor/outdoor), environment type, lighting conditions, visual style, and atmosphere.

## PEOPLE & CHARACTERS  
For each person visible:
- Physical appearance (age range, gender, clothing, distinguishing features)
- Position and posture in frame
- Facial expression and apparent emotion
- Role if apparent (presenter, interviewer, audience, etc.)
- Name if displayed (from name tags, lower-thirds, or introduced)

## ON-SCREEN TEXT (OCR) - CRITICAL
Transcribe ALL visible text exactly as shown:
- Slide titles, bullet points, and body text
- Lower-thirds, name captions, titles
- UI elements, buttons, menus (for screen recordings)
- Signs, labels, logos with text
- Watermarks or timestamps
Use quotation marks for exact text.

## VISUAL ELEMENTS
- Key objects and their spatial arrangement
- Products, devices, or technical equipment shown
- Brand logos, company names, product names
- Charts, graphs, diagrams - describe what they show
- Animations or visual effects

## ACTIONS & NARRATIVE
- What is happening in this exact moment
- Specific action verbs (presenting, demonstrating, explaining, comparing, introducing)
- Is this a transition, introduction, key point, or conclusion?
- Body language and gestures that convey meaning

## TOPICS & CONCEPTS
List 3-5 key topics or concepts this frame relates to (e.g., "cloud computing", "product launch", "quarterly results", "technical demo")

## SEARCHABLE KEYWORDS
Provide 8-12 keywords/phrases someone might use to find this moment:
- Include proper nouns (people, companies, products)
- Technical terms mentioned or shown
- Action descriptions ("showing demo", "explaining chart")
- Topic keywords

## POTENTIAL QUESTIONS THIS ANSWERS
List 2-3 questions this frame could help answer:
- e.g., "What is [product name]?", "Who presented about [topic]?", "When was [feature] demonstrated?"

Be thorough but factual. Include both obvious and subtle details. Prioritize information that would help users find this specific moment."""

        requests = []
        for idx, frame_data in enumerate(frames_data):
            # Replace placeholders with actual values for each frame
            prompt_text = custom_prompt or default_prompt
            prompt_text = prompt_text.replace("{frame_number}", str(frame_data.get('frame_number', idx)))
            prompt_text = prompt_text.replace("{timestamp}", str(frame_data.get('timestamp', 0)))
            
            request = {
                "custom_id": f"frame_{frame_data.get('frame_number', idx)}",
                "method": "POST",
                "url": "/chat/completions",
                "body": {
                    "model": self.gpt_deployment,
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": prompt_text},
                                {
                                    "type": "image_url",
                                    "image_url": {
                                        "url": f"data:image/jpeg;base64,{frame_data['image_base64']}"
                                    },
                                },
                            ],
                        }
                    ],
                    "max_tokens": 900,
                },
            }
            requests.append(request)

        return requests

    def submit_batch_job(
        self, requests: list[dict], description: str = "Video frame analysis"
    ) -> str:
        """
        Envía un batch job a Azure OpenAI.

        Returns:
            batch_id del job creado
        """
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            for request in requests:
                f.write(json.dumps(request) + "\n")
            temp_path = f.name

        try:
            logger.info(f"Uploading batch file ({len(requests)} requests)...")
            with open(temp_path, "rb") as f:
                batch_file = self.client.files.create(file=f, purpose="batch")

            logger.info(f"Creating batch job with file {batch_file.id}...")
            batch = self.client.batches.create(
                input_file_id=batch_file.id,
                endpoint="/chat/completions",
                completion_window="24h",
                metadata={"description": description},
            )

            logger.info(f"Batch job created: {batch.id} ({batch.request_counts.total} requests)")
            return batch.id

        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)

    def check_batch_status(self, batch_id: str) -> dict:
        """Verifica el estado de un batch job."""
        batch = self.client.batches.retrieve(batch_id)

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

    def wait_for_batch_completion(
        self, batch_id: str, check_interval: int = 30, max_wait_time: int = 3600
    ) -> bool:
        """
        Espera a que un batch job complete.

        Returns:
            True si completó exitosamente
        """
        logger.info(f"Waiting for batch {batch_id} to complete...")
        start_time = time.time()

        while True:
            elapsed = time.time() - start_time

            if elapsed > max_wait_time:
                logger.error(f"Batch timeout after {max_wait_time}s")
                return False

            status_info = self.check_batch_status(batch_id)
            status = status_info["status"]
            completed = status_info["request_counts"]["completed"]
            total = status_info["request_counts"]["total"]

            logger.info(f"Batch status: {status} ({completed}/{total}) - {elapsed:.0f}s elapsed")

            if status == "completed":
                logger.info("Batch completed successfully")
                return True
            elif status in ["failed", "expired", "cancelled"]:
                logger.error(f"Batch failed with status: {status}")
                return False

            time.sleep(check_interval)

    def get_batch_results(self, batch_id: str) -> list[dict]:
        """Obtiene los resultados de un batch job completado."""
        batch = self.client.batches.retrieve(batch_id)

        if batch.status != "completed":
            raise ValueError(f"Batch not completed: {batch.status}")

        if not batch.output_file_id:
            raise ValueError("No output file available")

        logger.info("Downloading batch results...")
        file_response = self.client.files.content(batch.output_file_id)

        results = []
        for line in file_response.text.strip().split("\n"):
            if line:
                results.append(json.loads(line))

        logger.info(f"Retrieved {len(results)} results")
        return results

    def parse_vision_results(self, results: list[dict]) -> dict[str, dict]:
        """Parsea resultados de análisis de visión."""
        parsed = {}

        for result in results:
            custom_id = result.get("custom_id")

            if result.get("response", {}).get("status_code") == 200:
                body = result["response"]["body"]
                content = body["choices"][0]["message"]["content"]
                tokens = body.get("usage", {}).get("total_tokens", 0)

                parsed[custom_id] = {
                    "analysis": content,
                    "tokens_used": tokens,
                    "success": True,
                }
            else:
                parsed[custom_id] = {
                    "analysis": None,
                    "tokens_used": 0,
                    "success": False,
                    "error": result.get("error", {}).get("message", "Unknown error"),
                }

        return parsed

    def cancel_batch(self, batch_id: str):
        """Cancela un batch job en progreso."""
        self.client.batches.cancel(batch_id)
        logger.info(f"Batch {batch_id} cancelled")
