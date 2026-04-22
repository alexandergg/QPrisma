"""Deterministic citation parsing for QPrisma evaluator outputs (E2).

Centralizes the regexes used to detect that an agent response cited
**evidence anchored in time** — i.e. timestamps or frame indices that point
back into the source video. Used by:

* ``qprisma.long_context_grounding`` (E1) — turns "did the response cite
  any evidence?" into a deterministic 0/0.5/1.0 score.
* Future evaluators / dashboards that want to compute citation density
  without paying for a judge.

Why deterministic + helper-only (instead of changing the agent's output
schema): keeping the change to a regex over the existing free-form
response means we get a useful long-context grounding signal **without**
modifying the agent contract or the hosted-agent state converter.
A future iteration can layer in retrieval-window verification (compare
parsed timestamps against the actual frames the retriever returned for
that ``media_id``).

Patterns recognised
-------------------
``[mm:ss]`` / ``[hh:mm:ss]``      — bracketed timestamps (preferred)
``(mm:ss)`` / ``(hh:mm:ss)``      — parenthesised timestamps
``mm:ss`` standalone (>= one digit each side, with surrounding boundary)
``frame 1234`` / ``frame #1234``  — frame indices
``t=12.5s`` / ``t=12s``           — t= notation
``at 12 seconds`` / ``at 12s``    — natural-language timestamp

Returned by ``parse_citations`` as a list of normalized dicts so callers can
count, dedupe, or eventually verify against a retrieval window.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

# Bracketed: [mm:ss] or [h:mm:ss] or [hh:mm:ss]
_BRACKET_TS = re.compile(r"\[\s*(\d{1,2}):(\d{2})(?::(\d{2}))?\s*\]")
_PAREN_TS = re.compile(r"\(\s*(\d{1,2}):(\d{2})(?::(\d{2}))?\s*\)")

# Standalone mm:ss / h:mm:ss with word boundaries so we don't catch ratios.
# Requires at least one digit before the colon and exactly two after.
_BARE_TS = re.compile(r"(?<![\d.])(\d{1,2}):(\d{2})(?::(\d{2}))?(?!\d)")

# frame N or frame #N
_FRAME_RE = re.compile(r"\bframe\s*#?\s*(\d{1,7})\b", re.IGNORECASE)

# t=12s, t=12.5s
_TEQ_RE = re.compile(r"\bt\s*=\s*(\d+(?:\.\d+)?)\s*s\b", re.IGNORECASE)

# at 12 seconds, at 12s
_AT_SEC_RE = re.compile(r"\bat\s+(\d+(?:\.\d+)?)\s*(?:s|sec|secs|seconds?)\b", re.IGNORECASE)

# Soft "talks about time but no anchor" — used to award partial credit (0.5)
# for responses that clearly attempt grounding but aren't precise.
_TIME_WORDS = re.compile(
    r"\b(beginning|middle|end|opening|closing|earlier|later|after|before)\b",
    re.IGNORECASE,
)


def _ts_to_seconds(h: str | None, m: str, s: str) -> float:
    return (int(h) * 3600 if h else 0) + int(m) * 60 + int(s)


def parse_citations(response: str | None) -> list[dict]:
    """Extract structured time-anchored citations from ``response``.

    Each returned dict has shape::

        {"kind": "timestamp" | "frame", "seconds": float | None, "frame": int | None,
         "raw": "<matched substring>"}

    The list is **not** deduplicated — callers can dedupe on ``(kind, seconds, frame)``
    if they need to. Order matches appearance in the response.
    """
    if not response:
        return []

    citations: list[dict] = []

    for match in _BRACKET_TS.finditer(response):
        m1, m2, m3 = match.groups()
        # If 3 groups present: h:m:s. Else m:s.
        if m3 is not None:
            seconds = _ts_to_seconds(m1, m2, m3)
        else:
            seconds = _ts_to_seconds(None, m1, m2)
        citations.append(
            {"kind": "timestamp", "seconds": seconds, "frame": None, "raw": match.group(0)}
        )

    for match in _PAREN_TS.finditer(response):
        m1, m2, m3 = match.groups()
        if m3 is not None:
            seconds = _ts_to_seconds(m1, m2, m3)
        else:
            seconds = _ts_to_seconds(None, m1, m2)
        citations.append(
            {"kind": "timestamp", "seconds": seconds, "frame": None, "raw": match.group(0)}
        )

    # Bare mm:ss — only count if not already captured by a bracket/paren overlap.
    captured_spans = [(m.start(), m.end()) for m in _BRACKET_TS.finditer(response)] + [
        (m.start(), m.end()) for m in _PAREN_TS.finditer(response)
    ]

    def _overlaps(s: int, e: int) -> bool:
        return any(not (e <= cs or s >= ce) for cs, ce in captured_spans)

    for match in _BARE_TS.finditer(response):
        if _overlaps(match.start(), match.end()):
            continue
        m1, m2, m3 = match.groups()
        if m3 is not None:
            seconds = _ts_to_seconds(m1, m2, m3)
        else:
            seconds = _ts_to_seconds(None, m1, m2)
        citations.append(
            {"kind": "timestamp", "seconds": seconds, "frame": None, "raw": match.group(0)}
        )

    for match in _FRAME_RE.finditer(response):
        citations.append(
            {
                "kind": "frame",
                "seconds": None,
                "frame": int(match.group(1)),
                "raw": match.group(0),
            }
        )

    for match in _TEQ_RE.finditer(response):
        citations.append(
            {
                "kind": "timestamp",
                "seconds": float(match.group(1)),
                "frame": None,
                "raw": match.group(0),
            }
        )

    for match in _AT_SEC_RE.finditer(response):
        citations.append(
            {
                "kind": "timestamp",
                "seconds": float(match.group(1)),
                "frame": None,
                "raw": match.group(0),
            }
        )

    return citations


def has_soft_time_reference(response: str | None) -> bool:
    """Return True if ``response`` mentions vague temporal anchors.

    Used to award partial credit when the agent gestures at when something
    happened (``"near the end"``) but doesn't drop a precise citation.
    """
    if not response:
        return False
    return _TIME_WORDS.search(response) is not None


def in_window(
    citation: dict, window_start: float, window_end: float, *, fps: float | None = None
) -> bool:
    """Whether a citation's timestamp falls inside ``[window_start, window_end]`` (seconds).

    ``frame``-kind citations are converted via ``fps`` if provided; otherwise they
    are ignored (returns ``False``) — frame counting without fps is meaningless.
    """
    if citation["kind"] == "timestamp" and citation["seconds"] is not None:
        return window_start <= citation["seconds"] <= window_end
    if citation["kind"] == "frame" and citation["frame"] is not None and fps:
        seconds = citation["frame"] / fps
        return window_start <= seconds <= window_end
    return False


def fraction_in_window(
    citations: Iterable[dict],
    window_start: float,
    window_end: float,
    *,
    fps: float | None = None,
) -> float:
    """Fraction of citations that fall inside the retrieval window.

    Returns ``0.0`` if there are no citations (E1 will treat that as the
    "no grounding evidence" branch).
    """
    cites = list(citations)
    if not cites:
        return 0.0
    hits = sum(1 for c in cites if in_window(c, window_start, window_end, fps=fps))
    return hits / len(cites)
