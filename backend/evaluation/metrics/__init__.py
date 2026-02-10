"""
Evaluation metrics for video understanding.

Modules:
- accuracy: MC accuracy, per-tier, per-task breakdowns
- retrieval: Recall@K, NDCG@K, MRR, Precision@K
- temporal: IoU, R@1@threshold, mIoU, timestamp MAE
- faithfulness: Claim decomposition, faithfulness scoring
- efficiency: Latency, cost, token tracking
"""

from .accuracy import (
    compute_accuracy,
    compute_accuracy_by_duration_tier,
    compute_accuracy_by_group,
)
from .efficiency import EfficiencyTracker
from .faithfulness import compute_faithfulness_score
from .retrieval import (
    context_precision,
    context_recall,
    mean_average_precision,
    mean_reciprocal_rank,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
)
from .temporal import (
    mean_iou,
    recall_at_iou_threshold,
    temporal_iou,
    timestamp_mae,
)

__all__ = [
    "compute_accuracy",
    "compute_accuracy_by_group",
    "compute_accuracy_by_duration_tier",
    "recall_at_k",
    "precision_at_k",
    "ndcg_at_k",
    "mean_reciprocal_rank",
    "mean_average_precision",
    "context_precision",
    "context_recall",
    "temporal_iou",
    "recall_at_iou_threshold",
    "mean_iou",
    "timestamp_mae",
    "compute_faithfulness_score",
    "EfficiencyTracker",
]
