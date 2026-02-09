"""
Information retrieval metrics for video RAG evaluation.

Implements standard IR metrics adapted for video segment retrieval:
- Recall@K, Precision@K, NDCG@K, MRR, MAP
- Context Precision and Context Recall (RAGAS-style, LLM-judged)
"""

import math


def recall_at_k(
    retrieved: list[str],
    relevant: set[str],
    k: int,
) -> float:
    """Recall@K: fraction of relevant items found in top-K.

    Args:
        retrieved: Ordered list of retrieved item IDs.
        relevant: Set of relevant item IDs (ground truth).
        k: Number of top results to consider.

    Returns:
        Recall@K in [0, 1].
    """
    if not relevant:
        return 0.0
    top_k = set(retrieved[:k])
    return len(top_k & relevant) / len(relevant)


def precision_at_k(
    retrieved: list[str],
    relevant: set[str],
    k: int,
) -> float:
    """Precision@K: fraction of top-K results that are relevant.

    Args:
        retrieved: Ordered list of retrieved item IDs.
        relevant: Set of relevant item IDs.
        k: Number of top results to consider.

    Returns:
        Precision@K in [0, 1].
    """
    if k == 0:
        return 0.0
    top_k = retrieved[:k]
    hits = sum(1 for item in top_k if item in relevant)
    return hits / k


def ndcg_at_k(
    retrieved: list[str],
    relevance_scores: dict[str, float],
    k: int,
) -> float:
    """Normalized Discounted Cumulative Gain at K.

    Accounts for graded relevance and position in ranking.

    DCG@K  = sum_{i=1}^{K} (2^{rel_i} - 1) / log2(i + 1)
    NDCG@K = DCG@K / IDCG@K

    Args:
        retrieved: Ordered list of retrieved item IDs.
        relevance_scores: Dict mapping item IDs to relevance scores (0-1 or graded).
        k: Number of top results to consider.

    Returns:
        NDCG@K in [0, 1].
    """
    if not relevance_scores or k == 0:
        return 0.0

    # Compute DCG
    dcg = 0.0
    for i, item in enumerate(retrieved[:k]):
        rel = relevance_scores.get(item, 0.0)
        dcg += (2**rel - 1) / math.log2(i + 2)  # i+2 because i is 0-indexed

    # Compute IDCG (ideal ranking)
    ideal_rels = sorted(relevance_scores.values(), reverse=True)[:k]
    idcg = 0.0
    for i, rel in enumerate(ideal_rels):
        idcg += (2**rel - 1) / math.log2(i + 2)

    return dcg / idcg if idcg > 0 else 0.0


def mean_reciprocal_rank(
    queries_retrieved: list[list[str]],
    queries_relevant: list[set[str]],
) -> float:
    """Mean Reciprocal Rank across multiple queries.

    MRR = (1/|Q|) * sum(1/rank_q) where rank_q is the position
    of the first relevant result for query q.

    Args:
        queries_retrieved: List of retrieved ID lists (one per query).
        queries_relevant: List of relevant ID sets (one per query).

    Returns:
        MRR in [0, 1].
    """
    if not queries_retrieved:
        return 0.0

    rr_sum = 0.0
    for retrieved, relevant in zip(queries_retrieved, queries_relevant):
        rr_sum += _reciprocal_rank(retrieved, relevant)

    return rr_sum / len(queries_retrieved)


def mean_average_precision(
    queries_retrieved: list[list[str]],
    queries_relevant: list[set[str]],
) -> float:
    """Mean Average Precision across multiple queries.

    MAP = (1/|Q|) * sum(AP(q))
    AP(q) = (1/|R_q|) * sum_{k=1}^{n} P(k) * rel(k)

    Args:
        queries_retrieved: List of retrieved ID lists (one per query).
        queries_relevant: List of relevant ID sets (one per query).

    Returns:
        MAP in [0, 1].
    """
    if not queries_retrieved:
        return 0.0

    ap_sum = 0.0
    for retrieved, relevant in zip(queries_retrieved, queries_relevant):
        ap_sum += _average_precision(retrieved, relevant)

    return ap_sum / len(queries_retrieved)


def context_precision(
    retrieved_relevant: list[bool],
) -> float:
    """Context Precision (RAGAS-style).

    Measures whether relevant items are ranked higher in the context.

    Context Precision@K = (1/K) * sum_{k=1}^{K} (Precision@k * v_k)
    where v_k = 1 if item at rank k is relevant.

    Args:
        retrieved_relevant: Ordered list of booleans indicating relevance
                           of each retrieved item (from LLM judge).

    Returns:
        Context precision in [0, 1].
    """
    if not retrieved_relevant:
        return 0.0

    cumulative_hits = 0
    weighted_precision_sum = 0.0

    for i, is_relevant in enumerate(retrieved_relevant):
        if is_relevant:
            cumulative_hits += 1
            precision_at_i = cumulative_hits / (i + 1)
            weighted_precision_sum += precision_at_i

    total_relevant = sum(retrieved_relevant)
    if total_relevant == 0:
        return 0.0

    return weighted_precision_sum / total_relevant


def context_recall(
    ground_truth_claims: list[str],
    claims_supported: list[bool],
) -> float:
    """Context Recall (RAGAS-style).

    Fraction of ground-truth claims that are supported by retrieved context.

    Args:
        ground_truth_claims: List of atomic claims from the ground truth answer.
        claims_supported: Whether each claim is supported by retrieved context
                         (from LLM judge decomposition).

    Returns:
        Context recall in [0, 1].
    """
    if not ground_truth_claims:
        return 0.0
    return sum(claims_supported) / len(ground_truth_claims)


# =============================================================================
# Batch computation helpers
# =============================================================================


def compute_retrieval_metrics(
    retrieved: list[str],
    relevant: set[str],
    relevance_scores: dict[str, float] | None = None,
    k_values: list[int] | None = None,
) -> dict[str, float]:
    """Compute all retrieval metrics for a single query.

    Args:
        retrieved: Ordered list of retrieved item IDs.
        relevant: Set of relevant item IDs.
        relevance_scores: Optional graded relevance scores.
        k_values: K values to compute metrics at. Defaults to [1, 5, 10, 20].

    Returns:
        Dict with all metric values.
    """
    if k_values is None:
        k_values = [1, 5, 10, 20]

    if relevance_scores is None:
        relevance_scores = {item: 1.0 for item in relevant}

    metrics = {}
    for k in k_values:
        metrics[f"recall@{k}"] = recall_at_k(retrieved, relevant, k)
        metrics[f"precision@{k}"] = precision_at_k(retrieved, relevant, k)
        metrics[f"ndcg@{k}"] = ndcg_at_k(retrieved, relevance_scores, k)

    metrics["mrr"] = _reciprocal_rank(retrieved, relevant)
    metrics["ap"] = _average_precision(retrieved, relevant)

    return metrics


# =============================================================================
# Internal helpers
# =============================================================================


def _reciprocal_rank(retrieved: list[str], relevant: set[str]) -> float:
    """Reciprocal rank for a single query."""
    for i, item in enumerate(retrieved):
        if item in relevant:
            return 1.0 / (i + 1)
    return 0.0


def _average_precision(retrieved: list[str], relevant: set[str]) -> float:
    """Average precision for a single query."""
    if not relevant:
        return 0.0
    hits = 0
    precision_sum = 0.0
    for i, item in enumerate(retrieved):
        if item in relevant:
            hits += 1
            precision_sum += hits / (i + 1)
    return precision_sum / len(relevant)
