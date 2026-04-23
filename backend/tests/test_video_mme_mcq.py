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
    exec(  # noqa: S102 - executing trusted evaluator code definition for isolation testing
        code_text, namespace
    )
    grade = namespace["grade"]
    assert grade(response="Answer: B", ground_truth="B") == {"accuracy": 1.0}
    assert grade(response="A", ground_truth="B") == {"accuracy": 0.0}
    assert grade(response="", ground_truth="A") == {"accuracy": 0.0}
    assert grade(response="A", ground_truth="") == {"accuracy": 0.0}


def test_code_text_exposes_top_level_grade_function() -> None:
    """Foundry's PythonGrader requires the entry point to be named ``grade``.

    Regression test for the production failure ``Invalid grader source:
    top-level grade() function not found in source``. Compiling and exec'ing
    ``CODE_TEXT`` here mirrors what Foundry does server-side, so a future rename
    away from ``grade`` will be caught at unit-test time instead of after
    re-registration in Foundry.
    """
    code_text = video_mme_mcq.CODE_DEFINITION_KWARGS["code_text"]
    compiled = compile(code_text, "<evaluator>", "exec")
    namespace: dict[str, object] = {}
    exec(compiled, namespace)  # noqa: S102 - trusted in-repo evaluator source
    assert "grade" in namespace, (
        "CODE_TEXT must expose a top-level `grade` function — Foundry's "
        "python_grader rejects sources without it."
    )
    assert callable(namespace["grade"])
    # A wrong name (e.g. ``evaluate``) must NOT be left lying around: Foundry
    # only inspects ``grade`` and would silently ignore the rest.
    assert (
        "evaluate" not in namespace
    ), "Found stale `evaluate` symbol — rename to `grade` and remove the alias."


def test_evaluator_version_is_bumped_when_code_changes() -> None:
    """``EVALUATOR_VERSION`` must change whenever ``CODE_TEXT`` changes.

    ``register_evaluators._register_code_or_prompt_evaluator`` treats Foundry's
    "already exists" response as a no-op success, so a stale version keeps
    serving the previous ``code_text``. Anyone editing ``CODE_TEXT`` MUST also
    bump ``EVALUATOR_VERSION`` to force Foundry to publish a new revision.

    This test pins the current version so a CODE_TEXT change without a version
    bump trips the assertion. When intentionally bumping, update both this
    pinned value and ``EVALUATOR_VERSION`` in lockstep.
    """
    assert (
        video_mme_mcq.EVALUATOR_VERSION == "5"
    ), "If you changed CODE_TEXT, bump EVALUATOR_VERSION and update this test."


def test_metric_is_primary_and_in_range() -> None:
    metric = video_mme_mcq.CODE_DEFINITION_KWARGS["metric"]
    assert metric["min_value"] == 0.0
    assert metric["max_value"] == 1.0
    assert metric["is_primary"] is True
    assert metric["desirable_direction"] == "increase"
