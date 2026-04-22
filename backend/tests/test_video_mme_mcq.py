"""Unit tests for the deterministic Video-MME MCQ evaluator (``qprisma.video_mme_mcq``).

These cover the pure-Python ``score`` / ``extract_letter`` helpers — no network,
no Foundry SDK required. The same logic is mirrored verbatim in the
``CODE_TEXT`` blob registered server-side, so equivalent behavior is asserted
by parity here.
"""

from __future__ import annotations

import pytest

from evaluation_foundry.evaluators import video_mme_mcq


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        ("A", "A"),
        ("B", "B"),
        ("C", "C"),
        ("D", "D"),
        ("Answer: A", "A"),
        ("The best answer is: D.", "D"),
        ("(C)", "C"),
        ("  B  ", "B"),
        ("I think the answer is A or maybe B", "A"),
        ("ABCD", None),  # no word-boundary letter
        ("", None),
        (None, None),
        ("E", None),
        ("a", None),  # case-sensitive: agent must respond with uppercase
    ],
)
def test_extract_letter(response: str | None, expected: str | None) -> None:
    assert video_mme_mcq.extract_letter(response) == expected


@pytest.mark.parametrize(
    ("response", "ground_truth", "expected"),
    [
        ("A", "A", 1.0),
        ("Answer: B", "B", 1.0),
        ("The best answer is: D.", "D", 1.0),
        ("A", "B", 0.0),
        ("", "C", 0.0),
        (None, "C", 0.0),
        ("C", "", 0.0),
        ("C", None, 0.0),
        ("c", "C", 0.0),  # lowercase agent answer doesn't count (verbatim Video-MME prompt)
        ("  D  ", "d", 1.0),  # ground truth is normalized via .upper()
    ],
)
def test_score(response: str | None, ground_truth: str | None, expected: float) -> None:
    assert video_mme_mcq.score(response, ground_truth) == expected


def test_code_text_runs_in_isolation() -> None:
    """The ``code_text`` blob registered with Foundry must be self-contained."""
    code_text = video_mme_mcq.CODE_DEFINITION_KWARGS["code_text"]
    namespace: dict[str, object] = {}
    exec(code_text, namespace)  # noqa: S102 — executing our own trusted code blob registered with Foundry
    evaluate = namespace["evaluate"]
    assert evaluate(response="Answer: B", ground_truth="B") == {"accuracy": 1.0}
    assert evaluate(response="A", ground_truth="B") == {"accuracy": 0.0}
    assert evaluate(response="", ground_truth="A") == {"accuracy": 0.0}
    assert evaluate(response="A", ground_truth="") == {"accuracy": 0.0}


def test_metric_is_primary_and_in_range() -> None:
    metric = video_mme_mcq.CODE_DEFINITION_KWARGS["metric"]
    assert metric["min_value"] == 0.0
    assert metric["max_value"] == 1.0
    assert metric["is_primary"] is True
    assert metric["desirable_direction"] == "increase"
