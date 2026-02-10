"""
Temporal grounding metrics for video understanding evaluation.

Evaluates how accurately a system can localize events in time:
- IoU: Intersection over Union of predicted vs. ground-truth segments
- R@1@threshold: Recall at IoU thresholds (0.3, 0.5, 0.7)
- mIoU: Mean IoU across all predictions
- Timestamp MAE: Mean absolute error for point-in-time predictions
"""


def temporal_iou(
    predicted: tuple[float, float],
    ground_truth: tuple[float, float],
) -> float:
    """Intersection over Union for temporal segments.

    IoU = |P ∩ G| / |P ∪ G|

    Args:
        predicted: (start, end) in seconds.
        ground_truth: (start, end) in seconds.

    Returns:
        IoU in [0, 1].
    """
    p_start, p_end = predicted
    g_start, g_end = ground_truth

    # Intersection
    inter_start = max(p_start, g_start)
    inter_end = min(p_end, g_end)
    intersection = max(0.0, inter_end - inter_start)

    # Union
    p_duration = max(0.0, p_end - p_start)
    g_duration = max(0.0, g_end - g_start)
    union = p_duration + g_duration - intersection

    if union <= 0:
        return 0.0
    return intersection / union


def recall_at_iou_threshold(
    predictions: list[tuple[float, float]],
    ground_truths: list[tuple[float, float]],
    threshold: float = 0.5,
) -> float:
    """Recall@1 at a given IoU threshold.

    R@1@m = |{queries where IoU >= m}| / |{total queries}|

    Args:
        predictions: List of predicted segments (start, end).
        ground_truths: List of ground-truth segments (start, end).
        threshold: IoU threshold (standard: 0.3, 0.5, 0.7).

    Returns:
        Recall in [0, 1].
    """
    if not predictions or not ground_truths:
        return 0.0

    if len(predictions) != len(ground_truths):
        raise ValueError(
            f"predictions and ground_truths must have the same length, "
            f"got {len(predictions)} and {len(ground_truths)}"
        )

    hits = sum(
        1
        for pred, gt in zip(predictions, ground_truths)
        if temporal_iou(pred, gt) >= threshold
    )
    return hits / len(predictions)


def mean_iou(
    predictions: list[tuple[float, float]],
    ground_truths: list[tuple[float, float]],
) -> float:
    """Mean IoU across all prediction-ground truth pairs.

    mIoU = (1/N) * sum(IoU_i)

    Args:
        predictions: List of predicted segments.
        ground_truths: List of ground-truth segments.

    Returns:
        Mean IoU in [0, 1].
    """
    if not predictions:
        return 0.0

    if len(predictions) != len(ground_truths):
        raise ValueError(
            f"predictions and ground_truths must have the same length, "
            f"got {len(predictions)} and {len(ground_truths)}"
        )

    total_iou = sum(
        temporal_iou(pred, gt)
        for pred, gt in zip(predictions, ground_truths)
    )
    return total_iou / len(predictions)


def timestamp_mae(
    predicted_timestamps: list[float],
    ground_truth_timestamps: list[float],
) -> float:
    """Mean Absolute Error for point-in-time predictions.

    MAE = (1/N) * sum(|predicted_i - gt_i|)

    Args:
        predicted_timestamps: List of predicted timestamps (seconds).
        ground_truth_timestamps: List of ground-truth timestamps (seconds).

    Returns:
        MAE in seconds. Returns 0.0 if no predictions are provided
        (indicating no data to evaluate, not perfect accuracy).
    """
    if not predicted_timestamps:
        return 0.0

    if len(predicted_timestamps) != len(ground_truth_timestamps):
        raise ValueError(
            f"predicted and ground_truth timestamps must have the same length, "
            f"got {len(predicted_timestamps)} and {len(ground_truth_timestamps)}"
        )

    total_error = sum(
        abs(pred - gt)
        for pred, gt in zip(predicted_timestamps, ground_truth_timestamps)
    )
    return total_error / len(predicted_timestamps)


def compute_temporal_metrics(
    predictions: list[tuple[float, float]],
    ground_truths: list[tuple[float, float]],
    iou_thresholds: list[float] | None = None,
) -> dict[str, float]:
    """Compute all temporal grounding metrics.

    Args:
        predictions: List of predicted segments (start, end).
        ground_truths: List of ground-truth segments (start, end).
        iou_thresholds: IoU thresholds for R@1. Defaults to [0.3, 0.5, 0.7].

    Returns:
        Dict with all temporal metric values.
    """
    if iou_thresholds is None:
        iou_thresholds = [0.3, 0.5, 0.7]

    metrics: dict[str, float] = {
        "mean_iou": mean_iou(predictions, ground_truths),
    }

    for threshold in iou_thresholds:
        key = f"r1@iou={threshold}"
        metrics[key] = recall_at_iou_threshold(predictions, ground_truths, threshold)

    # Timestamp MAE from segment midpoints
    pred_midpoints = [(s + e) / 2 for s, e in predictions]
    gt_midpoints = [(s + e) / 2 for s, e in ground_truths]
    metrics["timestamp_mae"] = timestamp_mae(pred_midpoints, gt_midpoints)

    return metrics
