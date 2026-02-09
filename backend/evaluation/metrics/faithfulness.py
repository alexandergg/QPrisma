"""
Faithfulness and hallucination metrics for video RAG evaluation.

Measures whether generated answers are grounded in retrieved evidence:
- Faithfulness Score: fraction of claims supported by retrieved context
- Hallucination detection helpers for downstream LLM judge evaluation
"""


def compute_faithfulness_score(
    total_claims: int,
    supported_claims: int,
) -> float:
    """Compute faithfulness score.

    Faithfulness = |claims supported by retrieved context| / |total claims in answer|

    A high faithfulness score means the answer is well-grounded in evidence.
    A low score indicates potential hallucination.

    Args:
        total_claims: Total number of atomic claims in the generated answer.
        supported_claims: Number of claims supported by the retrieved context.

    Returns:
        Faithfulness score in [0, 1].
    """
    if total_claims <= 0:
        return 1.0  # No claims = vacuously faithful
    return min(supported_claims / total_claims, 1.0)


def compute_hallucination_rate(
    total_claims: int,
    unsupported_claims: int,
) -> float:
    """Compute hallucination rate.

    Hallucination Rate = |unsupported claims| / |total claims|

    Args:
        total_claims: Total number of atomic claims.
        unsupported_claims: Claims not supported by evidence.

    Returns:
        Hallucination rate in [0, 1].
    """
    if total_claims <= 0:
        return 0.0
    return min(unsupported_claims / total_claims, 1.0)


def compute_source_attribution_rate(
    total_claims: int,
    claims_with_timestamps: int,
) -> float:
    """Compute source attribution rate.

    Measures what fraction of claims include verifiable timestamps/sources.

    Args:
        total_claims: Total number of claims.
        claims_with_timestamps: Claims that include a timestamp or source reference.

    Returns:
        Source attribution rate in [0, 1].
    """
    if total_claims <= 0:
        return 0.0
    return min(claims_with_timestamps / total_claims, 1.0)


def aggregate_faithfulness(
    results: list[dict[str, int]],
) -> dict[str, float]:
    """Aggregate faithfulness metrics across multiple questions.

    Args:
        results: List of dicts with keys 'total_claims', 'supported_claims',
                'unsupported_claims', 'claims_with_timestamps'.

    Returns:
        Dict with mean faithfulness_score, hallucination_rate,
        source_attribution_rate.
    """
    if not results:
        return {
            "faithfulness_score": 0.0,
            "hallucination_rate": 0.0,
            "source_attribution_rate": 0.0,
        }

    scores = []
    halluc_rates = []
    attrib_rates = []

    for r in results:
        total = r.get("total_claims", 0)
        supported = r.get("supported_claims", 0)
        unsupported = r.get("unsupported_claims", 0)
        with_ts = r.get("claims_with_timestamps", 0)

        scores.append(compute_faithfulness_score(total, supported))
        halluc_rates.append(compute_hallucination_rate(total, unsupported))
        attrib_rates.append(compute_source_attribution_rate(total, with_ts))

    n = len(results)
    return {
        "faithfulness_score": sum(scores) / n,
        "hallucination_rate": sum(halluc_rates) / n,
        "source_attribution_rate": sum(attrib_rates) / n,
    }
