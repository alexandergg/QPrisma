"""Unit tests for ``qprisma.long_context_grounding`` (E1) and the shared
citation parser (E2)."""

from __future__ import annotations

import pytest

from evaluation_foundry.evaluators import long_context_grounding
from evaluation_foundry.evaluators._citation_parsing import (
    fraction_in_window,
    has_soft_time_reference,
    in_window,
    parse_citations,
)

# ---------------------------------------------------------------------------
# parse_citations
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected_seconds"),
    [
        ("As shown at [01:23] the speaker pauses.", [83.0]),
        ("Around (00:42) the camera pans.", [42.0]),
        ("Time 1:02:03 marks the climax.", [3723.0]),
        ("Mentioned at 12:34 in the recording.", [754.0]),
        ("The frame is t=12.5s.", [12.5]),
        ("Look at the speaker at 90 seconds.", [90.0]),
    ],
)
def test_parse_citations_extracts_timestamps(text: str, expected_seconds: list[float]) -> None:
    cites = parse_citations(text)
    assert [c["seconds"] for c in cites] == expected_seconds


def test_parse_citations_extracts_frames() -> None:
    cites = parse_citations("See frame 1234 and Frame #5678 for the gesture.")
    assert [c["frame"] for c in cites] == [1234, 5678]
    assert all(c["kind"] == "frame" for c in cites)


def test_parse_citations_no_double_count_bracket_and_bare() -> None:
    """A bracketed [01:23] should not also be counted as bare 01:23."""
    cites = parse_citations("Look at [01:23].")
    assert len(cites) == 1
    assert cites[0]["seconds"] == 83.0


@pytest.mark.parametrize(
    "text",
    [
        "",
        None,
        "No timestamps anywhere here.",
        "Pi is roughly 3.14159 — no time.",
        "Score was 1:0 in the match.",  # 1:0 is single-digit-after-colon, not mm:ss
    ],
)
def test_parse_citations_empty(text: str | None) -> None:
    assert parse_citations(text) == []


def test_parse_citations_handles_multiple() -> None:
    cites = parse_citations(
        "Speaker introduces topic at [00:30], references prior point (1:15), "
        "and concludes at t=180s with frame 9000."
    )
    assert len(cites) == 4
    kinds = sorted(c["kind"] for c in cites)
    assert kinds == ["frame", "timestamp", "timestamp", "timestamp"]


# ---------------------------------------------------------------------------
# has_soft_time_reference
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("This happens near the end of the video.", True),
        ("The opening segment shows a logo.", True),
        ("Earlier she explains the method.", True),
        ("It is shown.", False),
        ("", False),
        (None, False),
    ],
)
def test_has_soft_time_reference(text: str | None, expected: bool) -> None:
    assert has_soft_time_reference(text) is expected


# ---------------------------------------------------------------------------
# in_window / fraction_in_window
# ---------------------------------------------------------------------------


def test_in_window_timestamp() -> None:
    cite = {"kind": "timestamp", "seconds": 42.0, "frame": None, "raw": "[00:42]"}
    assert in_window(cite, 30.0, 60.0) is True
    assert in_window(cite, 0.0, 30.0) is False


def test_in_window_frame_requires_fps() -> None:
    cite = {"kind": "frame", "seconds": None, "frame": 600, "raw": "frame 600"}
    assert in_window(cite, 19.0, 21.0, fps=30.0) is True  # 600/30 = 20s
    assert in_window(cite, 19.0, 21.0) is False  # no fps -> can't convert


def test_fraction_in_window() -> None:
    cites = [
        {"kind": "timestamp", "seconds": 10.0, "frame": None, "raw": "[00:10]"},
        {"kind": "timestamp", "seconds": 50.0, "frame": None, "raw": "[00:50]"},
        {"kind": "timestamp", "seconds": 100.0, "frame": None, "raw": "[01:40]"},
    ]
    assert fraction_in_window(cites, 0.0, 60.0) == pytest.approx(2 / 3)
    assert fraction_in_window([], 0.0, 60.0) == 0.0


# ---------------------------------------------------------------------------
# long_context_grounding.score
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        ("The speaker pauses at [01:23].", 1.0),
        ("See frame 4500 for the gesture.", 1.0),
        ("Visible at t=12.5s in the recording.", 1.0),
        ("Note the moment at 90 seconds.", 1.0),
        ("This happens near the end of the video.", 0.5),
        ("Earlier in the video she explains.", 0.5),
        ("The answer is C because it explains the topic.", 0.0),
        ("", 0.0),
        (None, 0.0),
    ],
)
def test_long_context_grounding_score(response: str | None, expected: float) -> None:
    assert long_context_grounding.score(response) == expected


def test_code_text_is_self_contained() -> None:
    """The CODE_TEXT registered server-side must execute in a fresh namespace."""
    namespace: dict = {}
    exec(long_context_grounding.CODE_TEXT, namespace)  # noqa: S102 — testing inlined runtime code
    evaluate = namespace["evaluate"]
    assert evaluate("Look at [00:30].") == {"long_context_grounding": 1.0}
    assert evaluate("It happens near the end.") == {"long_context_grounding": 0.5}
    assert evaluate("Just an answer.") == {"long_context_grounding": 0.0}


def test_code_definition_kwargs_shape() -> None:
    kwargs = long_context_grounding.CODE_DEFINITION_KWARGS
    assert kwargs["metric_name"] == "long_context_grounding"
    assert kwargs["metric"]["min_value"] == 0.0
    assert kwargs["metric"]["max_value"] == 1.0
    assert kwargs["data_schema"]["response"] == {"type": "string"}
