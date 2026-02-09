"""
Baseline method adapters for evaluation.

Provides:
- UniformBaselineAdapter: Uniform frame sampling + GPT-4o single-shot QA
- NaiveRAGAdapter: Simple chunk + embed + retrieve + generate
- ExternalAPIAdapter: Wrapper for GPT-4o native / Gemini 1.5 Pro
"""

import logging
import time

from evaluation.adapters.base import BaseMethodAdapter
from evaluation.models.eval_schemas import BenchmarkEntry, EvalResult

logger = logging.getLogger(__name__)


class UniformBaselineAdapter(BaseMethodAdapter):
    """Uniform frame sampling + GPT-4o single-shot QA.

    Samples N evenly-spaced frames from the video, sends them as images
    to GPT-4o along with the question, and returns the response.
    """

    def __init__(
        self,
        num_frames: int = 16,
        model: str = "gpt-4o",
    ):
        self.num_frames = num_frames
        self.model = model
        self._client = None

    @property
    def name(self) -> str:
        return f"uniform-{self.num_frames}"

    @property
    def display_name(self) -> str:
        return f"Uniform Sampling ({self.num_frames} frames)"

    async def setup(self) -> None:
        from openai import AsyncOpenAI

        self._client = AsyncOpenAI()

    async def generate_answer(
        self,
        entry: BenchmarkEntry,
        video_path: str | None = None,
    ) -> EvalResult:
        """Extract N frames uniformly and send to GPT-4o with the question."""
        if self._client is None:
            await self.setup()

        start_time = time.perf_counter()
        answer_text = ""
        tokens_used = 0

        try:
            # Extract frames
            frames_b64 = await self._extract_frames(video_path)

            # Build vision message
            query = self._build_query(entry)
            content = [{"type": "text", "text": query}]
            for frame in frames_b64:
                content.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{frame}"},
                })

            response = await self._client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": content}],
                max_tokens=1000,
            )

            answer_text = response.choices[0].message.content or ""
            tokens_used = response.usage.total_tokens if response.usage else 0

        except Exception as e:
            logger.error("Uniform baseline error on %s: %s", entry.question_id, e)
            answer_text = f"Error: {e}"

        latency_ms = (time.perf_counter() - start_time) * 1000

        return EvalResult(
            question_id=entry.question_id,
            method=self.name,
            answer=answer_text,
            predicted_choice=self.extract_mc_choice(answer_text, entry.choices),
            predicted_timestamps=self.extract_timestamps(answer_text),
            latency_ms=latency_ms,
            tokens_used=tokens_used,
        )

    async def _extract_frames(self, video_path: str | None) -> list[str]:
        """Extract N evenly-spaced frames as base64 JPEG strings."""
        if not video_path:
            return []

        import base64
        import subprocess
        import tempfile
        from pathlib import Path

        frames = []
        with tempfile.TemporaryDirectory() as tmpdir:
            # Use FFmpeg to extract N frames
            cmd = [
                "ffmpeg", "-i", video_path,
                "-vf", f"select=not(mod(n\\,{max(1, self._get_interval(video_path))})),scale=720:-1",
                "-frames:v", str(self.num_frames),
                "-vsync", "vfr",
                "-q:v", "5",
                f"{tmpdir}/frame_%04d.jpg",
                "-y", "-loglevel", "error",
            ]
            subprocess.run(cmd, check=True, timeout=60)

            # Read frames as base64
            for frame_path in sorted(Path(tmpdir).glob("frame_*.jpg")):
                with open(frame_path, "rb") as f:
                    frames.append(base64.b64encode(f.read()).decode())

        return frames[:self.num_frames]

    def _get_interval(self, video_path: str) -> int:
        """Estimate frame interval for uniform sampling."""
        # Rough estimate: assume 30fps, 60s video = 1800 frames
        # interval = total_frames / num_frames
        try:
            import subprocess

            result = subprocess.run(
                ["ffprobe", "-v", "error", "-count_frames",
                 "-select_streams", "v:0",
                 "-show_entries", "stream=nb_read_frames",
                 "-of", "csv=p=0", video_path],
                capture_output=True, text=True, timeout=30,
            )
            total_frames = int(result.stdout.strip())
            return max(1, total_frames // self.num_frames)
        except Exception:
            return 30  # Default: every 30th frame (~1fps)

    def _build_query(self, entry: BenchmarkEntry) -> str:
        """Build query with MC choices."""
        query = entry.question
        if entry.choices:
            query += "\n\nChoices:\n"
            for i, c in enumerate(entry.choices):
                letter = chr(ord("A") + i)
                if not c.strip().startswith(f"{letter}."):
                    query += f"{letter}. {c}\n"
                else:
                    query += f"{c}\n"
            query += "\nAnswer with just the letter (A/B/C/D)."
        return query


class NaiveRAGAdapter(BaseMethodAdapter):
    """Simple chunk + embed + retrieve + generate baseline.

    Chunks the video transcript into fixed-size segments, embeds them,
    retrieves the top-K most similar to the query, and generates an answer.
    This is the standard RAG baseline (following VideoRAG's NaiveRAG).
    """

    def __init__(
        self,
        chunk_size: int = 500,
        top_k: int = 5,
        model: str = "gpt-4o",
    ):
        self.chunk_size = chunk_size
        self.top_k = top_k
        self.model = model
        self._client = None
        self._embeddings_cache: dict[str, list[tuple[str, list[float]]]] = {}

    @property
    def name(self) -> str:
        return "naive-rag"

    @property
    def display_name(self) -> str:
        return "Naive RAG"

    async def setup(self) -> None:
        from openai import AsyncOpenAI

        self._client = AsyncOpenAI()

    async def generate_answer(
        self,
        entry: BenchmarkEntry,
        video_path: str | None = None,
    ) -> EvalResult:
        """Retrieve relevant chunks and generate answer."""
        if self._client is None:
            await self.setup()

        start_time = time.perf_counter()
        answer_text = ""
        tokens_used = 0

        try:
            # Get or build chunk index for this video
            chunks = await self._get_video_chunks(entry.video_id, video_path)

            # Retrieve top-K chunks by embedding similarity
            relevant = await self._retrieve(entry.question, chunks)

            # Generate answer from retrieved context
            context = "\n\n".join([c[0] for c in relevant])
            query = self._build_query(entry)

            response = await self._client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "Answer using ONLY the provided context. "
                        "For MC questions, state the letter.",
                    },
                    {
                        "role": "user",
                        "content": f"Context:\n{context}\n\nQuestion: {query}",
                    },
                ],
                max_tokens=1000,
            )
            answer_text = response.choices[0].message.content or ""
            tokens_used = response.usage.total_tokens if response.usage else 0

        except Exception as e:
            logger.error("NaiveRAG error on %s: %s", entry.question_id, e)
            answer_text = f"Error: {e}"

        latency_ms = (time.perf_counter() - start_time) * 1000

        return EvalResult(
            question_id=entry.question_id,
            method=self.name,
            answer=answer_text,
            predicted_choice=self.extract_mc_choice(answer_text, entry.choices),
            predicted_timestamps=self.extract_timestamps(answer_text),
            latency_ms=latency_ms,
            tokens_used=tokens_used,
        )

    async def _get_video_chunks(
        self, video_id: str, video_path: str | None
    ) -> list[tuple[str, list[float]]]:
        """Get or build text chunks with embeddings for a video."""
        if video_id in self._embeddings_cache:
            return self._embeddings_cache[video_id]

        # Try to get transcript from QPrisma's KG
        chunks_with_embeddings = []
        try:
            from services.knowledge_graph import get_knowledge_graph_service

            kg = get_knowledge_graph_service()
            transcripts = await kg.get_video_transcripts(video_id)

            if transcripts:
                # Chunk transcripts
                full_text = " ".join(t.get("text", "") for t in transcripts)
                text_chunks = self._chunk_text(full_text)

                # Embed chunks
                for chunk in text_chunks:
                    emb_resp = await self._client.embeddings.create(
                        model="text-embedding-3-large",
                        input=chunk,
                    )
                    chunks_with_embeddings.append(
                        (chunk, emb_resp.data[0].embedding)
                    )
        except Exception as e:
            logger.warning("Failed to get transcripts for %s: %s", video_id, e)

        self._embeddings_cache[video_id] = chunks_with_embeddings
        return chunks_with_embeddings

    async def _retrieve(
        self,
        query: str,
        chunks: list[tuple[str, list[float]]],
    ) -> list[tuple[str, list[float]]]:
        """Retrieve top-K chunks by cosine similarity."""
        if not chunks:
            return []

        # Embed the query
        q_resp = await self._client.embeddings.create(
            model="text-embedding-3-large",
            input=query,
        )
        q_emb = q_resp.data[0].embedding

        # Score and sort
        scored = []
        for chunk_text, chunk_emb in chunks:
            sim = self._cosine_similarity(q_emb, chunk_emb)
            scored.append((sim, chunk_text, chunk_emb))

        scored.sort(reverse=True)
        return [(text, emb) for _, text, emb in scored[: self.top_k]]

    def _chunk_text(self, text: str) -> list[str]:
        """Split text into fixed-size chunks with overlap."""
        words = text.split()
        chunk_words = self.chunk_size // 4  # ~4 chars per word
        overlap = chunk_words // 5
        chunks = []
        i = 0
        while i < len(words):
            chunk = " ".join(words[i : i + chunk_words])
            if chunk.strip():
                chunks.append(chunk)
            i += chunk_words - overlap
        return chunks

    @staticmethod
    def _cosine_similarity(a: list[float], b: list[float]) -> float:
        """Compute cosine similarity between two vectors."""
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = sum(x * x for x in a) ** 0.5
        norm_b = sum(x * x for x in b) ** 0.5
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)

    def _build_query(self, entry: BenchmarkEntry) -> str:
        query = entry.question
        if entry.choices:
            query += "\n\nChoices:\n"
            for i, c in enumerate(entry.choices):
                letter = chr(ord("A") + i)
                if not c.strip().startswith(f"{letter}."):
                    query += f"{letter}. {c}\n"
                else:
                    query += f"{c}\n"
            query += "\nAnswer with just the letter (A/B/C/D)."
        return query


class ExternalAPIAdapter(BaseMethodAdapter):
    """Wrapper for external API-based video understanding (GPT-4o, Gemini).

    Sends video frames directly to the API without any preprocessing
    or RAG pipeline — pure end-to-end video understanding.
    """

    def __init__(
        self,
        provider: str = "openai",
        model: str = "gpt-4o",
        num_frames: int = 32,
    ):
        """
        Args:
            provider: 'openai' or 'gemini'.
            model: Model identifier.
            num_frames: Number of frames to sample.
        """
        self.provider = provider
        self.model = model
        self.num_frames = num_frames
        self._client = None

    @property
    def name(self) -> str:
        return f"{self.provider}-{self.model}"

    @property
    def display_name(self) -> str:
        return f"{self.provider.title()} {self.model}"

    async def setup(self) -> None:
        if self.provider == "openai":
            from openai import AsyncOpenAI

            self._client = AsyncOpenAI()
        elif self.provider == "gemini":
            # Gemini setup would go here
            logger.info("Gemini adapter: using Google AI SDK")
        else:
            raise ValueError(f"Unknown provider: {self.provider}")

    async def generate_answer(
        self,
        entry: BenchmarkEntry,
        video_path: str | None = None,
    ) -> EvalResult:
        """Send video frames + question directly to the API."""
        if self._client is None:
            await self.setup()

        start_time = time.perf_counter()
        answer_text = ""
        tokens_used = 0

        try:
            if self.provider == "openai":
                answer_text, tokens_used = await self._call_openai(entry, video_path)
            elif self.provider == "gemini":
                answer_text, tokens_used = await self._call_gemini(entry, video_path)
        except Exception as e:
            logger.error("%s error on %s: %s", self.name, entry.question_id, e)
            answer_text = f"Error: {e}"

        latency_ms = (time.perf_counter() - start_time) * 1000

        return EvalResult(
            question_id=entry.question_id,
            method=self.name,
            answer=answer_text,
            predicted_choice=self.extract_mc_choice(answer_text, entry.choices),
            predicted_timestamps=self.extract_timestamps(answer_text),
            latency_ms=latency_ms,
            tokens_used=tokens_used,
        )

    async def _call_openai(
        self, entry: BenchmarkEntry, video_path: str | None
    ) -> tuple[str, int]:
        """Call OpenAI GPT-4o with video frames."""
        # Reuse UniformBaselineAdapter's frame extraction
        uniform = UniformBaselineAdapter(num_frames=self.num_frames, model=self.model)
        uniform._client = self._client
        result = await uniform.generate_answer(entry, video_path)
        return result.answer, result.tokens_used or 0

    async def _call_gemini(
        self, entry: BenchmarkEntry, video_path: str | None
    ) -> tuple[str, int]:
        """Call Gemini with video file."""
        # Placeholder — Gemini supports direct video upload
        logger.warning("Gemini adapter not yet implemented")
        return "Gemini not implemented", 0
