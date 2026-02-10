"""
Pydantic models for the QPrisma evaluation framework.

Defines schemas for benchmark entries, judge responses, evaluation results,
and configuration. Judge response schemas use Literal types for structured
output enforcement via OpenAI's response_format (following VideoRAG pattern).
"""

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


# =============================================================================
# Enums
# =============================================================================


class DurationTier(str, Enum):
    """Video duration tiers for stratified evaluation."""

    SHORT = "short"  # < 2 min
    MEDIUM = "medium"  # 2-15 min
    LONG = "long"  # 15-60 min
    VERY_LONG = "very_long"  # > 60 min


class EvalDimension(str, Enum):
    """Evaluation dimensions (VideoRAG 5 + QPrisma 2 extensions)."""

    COMPREHENSIVENESS = "Comprehensiveness"
    EMPOWERMENT = "Empowerment"
    TRUSTWORTHINESS = "Trustworthiness"
    DEPTH = "Depth"
    DENSITY = "Density"
    TEMPORAL_SPECIFICITY = "Temporal Specificity"  # QPrisma extension
    SOURCE_GROUNDING = "Source Grounding"  # QPrisma extension
    OVERALL = "Overall"


# =============================================================================
# Benchmark Entry
# =============================================================================


class BenchmarkEntry(BaseModel):
    """A single benchmark question with metadata."""

    question_id: str = Field(description="Unique question identifier")
    video_id: str = Field(description="Video this question refers to")
    question: str = Field(description="The question text")
    choices: list[str] | None = Field(
        default=None, description="MC choices (None for open-ended)"
    )
    correct_answer: str | None = Field(
        default=None, description="Ground truth answer or correct choice index"
    )
    ground_truth_segments: list[tuple[float, float]] | None = Field(
        default=None, description="Relevant time segments [(start, end), ...]"
    )
    category: str | None = Field(default=None, description="Task category")
    domain: str | None = Field(default=None, description="Video domain")
    duration_tier: DurationTier | None = Field(
        default=None, description="Video duration tier"
    )
    video_duration_seconds: float | None = Field(
        default=None, description="Video duration in seconds"
    )
    benchmark: str = Field(description="Source benchmark name")
    metadata: dict[str, str | int | float | bool | None] | None = Field(
        default=None, description="Additional metadata"
    )

    @field_validator("question_id")
    @classmethod
    def validate_question_id(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("question_id cannot be empty")
        return v.strip()

    @field_validator("video_duration_seconds")
    @classmethod
    def validate_duration(cls, v: float | None) -> float | None:
        if v is not None and v <= 0:
            raise ValueError("video_duration_seconds must be positive")
        return v


# =============================================================================
# Judge Response Schemas (Pydantic structured output for OpenAI)
# =============================================================================


class DimensionWinner(BaseModel):
    """Win-rate judge output for one dimension."""

    winner: Literal["Answer 1", "Answer 2"] = Field(
        description="Which answer is better for this dimension"
    )
    explanation: str = Field(description="Brief explanation of the choice")


class WinRateJudgeResponse(BaseModel):
    """Full win-rate judge response (pairwise A/B comparison).

    Used with OpenAI's response_format for structured output enforcement.
    Follows VideoRAG's schema with QPrisma extensions.
    """

    comprehensiveness: DimensionWinner = Field(alias="Comprehensiveness")
    empowerment: DimensionWinner = Field(alias="Empowerment")
    trustworthiness: DimensionWinner = Field(alias="Trustworthiness")
    depth: DimensionWinner = Field(alias="Depth")
    density: DimensionWinner = Field(alias="Density")
    temporal_specificity: DimensionWinner = Field(alias="Temporal Specificity")
    source_grounding: DimensionWinner = Field(alias="Source Grounding")
    overall_winner: DimensionWinner = Field(alias="Overall Winner")

    model_config = ConfigDict(populate_by_name=True)


class DimensionScore(BaseModel):
    """Quantitative judge output for one dimension."""

    score: Literal[1, 2, 3, 4, 5] = Field(
        description="Score from 1 (much worse) to 5 (much better) vs baseline"
    )
    explanation: str = Field(description="Brief explanation of the score")


class QuantitativeJudgeResponse(BaseModel):
    """Full quantitative judge response (1-5 scoring vs baseline).

    Used with OpenAI's response_format for structured output enforcement.
    """

    comprehensiveness: DimensionScore = Field(alias="Comprehensiveness")
    empowerment: DimensionScore = Field(alias="Empowerment")
    trustworthiness: DimensionScore = Field(alias="Trustworthiness")
    depth: DimensionScore = Field(alias="Depth")
    density: DimensionScore = Field(alias="Density")
    temporal_specificity: DimensionScore = Field(alias="Temporal Specificity")
    source_grounding: DimensionScore = Field(alias="Source Grounding")
    overall_score: DimensionScore = Field(alias="Overall Score")

    model_config = ConfigDict(populate_by_name=True)


class JudgeResponse(BaseModel):
    """Wrapper for a single judge evaluation result."""

    question_id: str
    run_index: int = Field(description="Which of the N evaluation runs (0-indexed)")
    ordering: Literal["original", "reversed"] = Field(
        default="original", description="Answer ordering for position debiasing"
    )
    method_a: str = Field(description="Name of method producing Answer 1")
    method_b: str = Field(description="Name of method producing Answer 2")
    winrate_response: WinRateJudgeResponse | None = None
    quantitative_response: QuantitativeJudgeResponse | None = None
    judge_model: str = Field(default="gpt-4o")
    raw_response: str | None = Field(
        default=None, description="Raw JSON from judge for debugging"
    )


# =============================================================================
# Evaluation Results
# =============================================================================


class EvalResult(BaseModel):
    """Result for a single question from a single method."""

    question_id: str
    method: str = Field(description="Method name (e.g., 'qprisma-full')")
    answer: str = Field(description="Generated answer text")
    predicted_choice: str | None = Field(
        default=None, description="For MC: predicted choice index/letter"
    )
    predicted_timestamps: list[float] | None = Field(
        default=None, description="Timestamps mentioned in the answer"
    )
    predicted_segments: list[tuple[float, float]] | None = Field(
        default=None, description="Predicted time segments"
    )
    retrieved_nodes: list[str] | None = Field(
        default=None, description="KG node IDs used in retrieval"
    )
    retrieved_context: str | None = Field(
        default=None, description="RAG context fed to the LLM"
    )
    latency_ms: float | None = Field(
        default=None, description="End-to-end response time"
    )
    retrieval_latency_ms: float | None = Field(
        default=None, description="Retrieval-only time"
    )
    tokens_used: int | None = Field(default=None, description="Total tokens consumed")
    cost_usd: float | None = Field(default=None, description="Estimated API cost")
    tool_calls: int | None = Field(
        default=None, description="Number of agent tool calls"
    )
    error: str | None = Field(
        default=None, description="Error message if answer generation failed"
    )
    metadata: dict[str, str | int | float | list | None] | None = None


class DimensionAggregation(BaseModel):
    """Aggregated scores for a single evaluation dimension."""

    mean: float = Field(description="Mean score across all questions")
    std: float = Field(description="Standard deviation of scores")
    min: float = Field(description="Minimum score observed")
    max: float = Field(description="Maximum score observed")
    n: int = Field(description="Number of questions evaluated")


class AggregatedResults(BaseModel):
    """Aggregated evaluation results for one method on one benchmark."""

    method: str
    benchmark: str
    total_questions: int

    # MC accuracy (if applicable)
    accuracy: float | None = None
    accuracy_by_tier: dict[str, float] | None = None
    accuracy_by_category: dict[str, float] | None = None

    # LLM judge scores (quantitative, aggregated across N runs)
    dimension_scores: dict[str, DimensionAggregation] | None = None

    # Win-rates (against a specific comparator)
    win_rates: dict[str, dict[str, float]] | None = Field(
        default=None, description="win_rates[comparator][dimension] = win%"
    )

    # Retrieval metrics
    recall_at_k: dict[int, float] | None = None  # {5: 0.82, 10: 0.91, ...}
    ndcg_at_k: dict[int, float] | None = None
    mrr: float | None = None
    context_precision: float | None = None
    context_recall: float | None = None

    # Temporal metrics
    mean_iou: float | None = None
    r1_at_03: float | None = None
    r1_at_05: float | None = None
    r1_at_07: float | None = None
    timestamp_mae: float | None = None

    # Faithfulness
    faithfulness_score: float | None = None
    hallucination_rate: float | None = None

    # Efficiency
    avg_latency_ms: float | None = None
    p95_latency_ms: float | None = None
    avg_cost_usd: float | None = None
    avg_tokens: float | None = None


# =============================================================================
# Configuration
# =============================================================================


class MethodConfig(BaseModel):
    """Configuration for an evaluation method/system."""

    name: str = Field(description="Method identifier (e.g., 'qprisma-full')")
    display_name: str = Field(description="Human-readable name")
    description: str | None = None
    is_baseline: bool = Field(default=False, description="Whether this is a baseline")
    config: dict[str, str | int | float | bool | None] | None = Field(
        default=None, description="Method-specific configuration"
    )


class BenchmarkConfig(BaseModel):
    """Configuration for a benchmark dataset."""

    name: str = Field(description="Benchmark identifier")
    data_path: str = Field(description="Path to benchmark data")
    video_dir: str = Field(description="Path to video files")
    task_type: Literal["multiple_choice", "open_ended", "mixed"] = "mixed"
    has_temporal_annotations: bool = False
    domains: list[str] | None = None


class EvalConfig(BaseModel):
    """Top-level evaluation configuration."""

    benchmarks: list[BenchmarkConfig]
    methods: list[MethodConfig]
    baseline_method: str = Field(
        default="naive_rag",
        description="Baseline method for quantitative scoring",
    )
    judge_model: str = Field(default="gpt-4o")
    num_runs: int = Field(default=5, description="Number of evaluation runs")
    use_position_debiasing: bool = Field(default=True)
    use_batch_api: bool = Field(
        default=True, description="Use OpenAI Batch API for cost savings"
    )
    output_dir: str = Field(default="evaluation/results")
    max_concurrent_judges: int = Field(default=10)
