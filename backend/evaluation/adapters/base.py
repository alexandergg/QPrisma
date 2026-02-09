"""
Base adapter interface for evaluation methods.

All method adapters (QPrisma, baselines) implement this interface
so the evaluation runner can treat them uniformly.
"""

import re
from abc import ABC, abstractmethod

from evaluation.models.eval_schemas import BenchmarkEntry, EvalResult


class BaseMethodAdapter(ABC):
    """Abstract base class for evaluation method adapters."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique method identifier (e.g., 'qprisma-full')."""
        ...

    @property
    @abstractmethod
    def display_name(self) -> str:
        """Human-readable method name."""
        ...

    @abstractmethod
    async def generate_answer(
        self,
        entry: BenchmarkEntry,
        video_path: str | None = None,
    ) -> EvalResult:
        """Generate an answer for a single benchmark question.

        Args:
            entry: Benchmark question with metadata.
            video_path: Path to the video file (if needed).

        Returns:
            EvalResult with the generated answer and metadata.
        """
        ...

    async def setup(self) -> None:
        """Optional setup before evaluation run (e.g., index videos)."""
        pass

    async def teardown(self) -> None:
        """Optional cleanup after evaluation run."""
        pass

    def extract_mc_choice(self, answer: str, choices: list[str] | None) -> str | None:
        """Extract the MC choice letter from a free-form answer.

        Handles various response formats:
        - "A" / "B" / "C" / "D"
        - "(A)" / "(B)"
        - "The answer is A"
        - Full choice text match
        """
        if not choices:
            return None

        answer = answer.strip()
        # Strip markdown bold/italic for cleaner matching
        clean = re.sub(r"\*{1,2}([^*]+)\*{1,2}", r"\1", answer)

        # Direct letter match
        for letter in ["A", "B", "C", "D"]:
            if clean.upper() == letter or clean.upper() == f"({letter})":
                return letter

        # Pattern: "The answer is X" or "Answer: X" or "Answer X"
        pattern = r"(?:answer\s*(?:is|:)?\s*)([A-D])\b"
        match = re.search(pattern, clean, re.IGNORECASE)
        if match:
            return match.group(1).upper()

        # Pattern: starts with letter followed by period/parenthesis/dash/space
        pattern = r"^([A-D])[\.\)\s\-\u2013\u2014]"
        match = re.match(pattern, clean.strip(), re.IGNORECASE)
        if match:
            return match.group(1).upper()

        # Pattern: bold letter at start "**A**" or "**B.**"
        pattern = r"^\*{1,2}([A-D])[\.\)]*\*{1,2}"
        match = re.match(pattern, answer.strip(), re.IGNORECASE)
        if match:
            return match.group(1).upper()

        # Full text match against choices (require minimum 10 chars to avoid false positives)
        answer_lower = clean.lower().strip()
        for i, choice in enumerate(choices):
            choice_text = choice.strip()
            # Remove letter prefix if present (e.g., "A. apples" -> "apples")
            clean_choice = re.sub(r"^[A-D][\.\)\s]+", "", choice_text).strip()
            if (
                answer_lower == choice_text.lower()
                or answer_lower == clean_choice.lower()
                or (len(clean_choice) >= 10 and clean_choice.lower() in answer_lower[:200])
            ):
                return chr(ord("A") + i)

        return None

    def extract_timestamps(self, answer: str) -> list[float]:
        """Extract timestamps mentioned in the answer.

        Handles formats: [MM:SS], [H:MM:SS], MM:SS, at Xs, timestamp Xs
        """
        timestamps = []

        # [H:MM:SS] or [MM:SS]
        for match in re.finditer(r"\[?(\d+):(\d{2}):(\d{2})\]?", answer):
            h, m, s = int(match.group(1)), int(match.group(2)), int(match.group(3))
            timestamps.append(h * 3600 + m * 60 + s)

        for match in re.finditer(r"\[?(\d{1,2}):(\d{2})\]?", answer):
            m, s = int(match.group(1)), int(match.group(2))
            ts = m * 60 + s
            if ts not in timestamps:  # Avoid duplicates from H:MM:SS captures
                timestamps.append(ts)

        # "at Xs" or "timestamp Xs"
        for match in re.finditer(r"(?:at|timestamp)\s+(\d+(?:\.\d+)?)\s*s", answer, re.I):
            timestamps.append(float(match.group(1)))

        return sorted(set(timestamps))
