"""
Evaluation framework for QPrisma long-context video understanding.

Provides benchmarking, metrics computation, LLM-as-judge evaluation,
and batch evaluation pipelines for comparing QPrisma against baselines.
"""

from evaluation.models.eval_schemas import BenchmarkEntry, EvalResult
from evaluation.runner import EvaluationRunner

__all__ = [
    "BenchmarkEntry",
    "EvalResult",
    "EvaluationRunner",
]
