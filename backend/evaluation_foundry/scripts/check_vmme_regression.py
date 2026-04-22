"""Advisory regression check for Video-MME ``accuracy_long`` (V5).

This script is intentionally lightweight and **never blocks CI**. It emits a
``::warning::`` annotation and writes a row to ``$GITHUB_STEP_SUMMARY`` when
the current ``accuracy_long`` is more than ``--threshold`` (default 0.03)
below the rolling median of the last ``--window`` runs (default 7).

Inputs
------
``--current-accuracy-long FLOAT`` *(or)* ``--results-dir PATH``
    Provide one. When ``--results-dir`` is given, the script best-effort scans
    common ai-agent-evals output filenames and extracts the per-bucket
    ``accuracy_long`` (mean of per-row scores tagged ``duration_bucket==long``
    on ``qprisma.video_mme_mcq``). If no parseable result is found the script
    writes an info row to the step summary and exits 0 (advisory).

``--history PATH``
    JSON file with shape ``{"runs": [{"accuracy_long": 0.42, ...}, ...]}``.
    Missing/empty file is treated as "no baseline yet" and exits cleanly.

``--window INT`` (default 7)
    Number of most-recent runs to compute the rolling median over.

``--threshold FLOAT`` (default 0.03)
    Drop tolerance vs rolling median (3pp default; matches plan V5).

``--append`` (flag)
    If set, appends the current value to the history file (creating it if
    needed). Useful to keep the history file growing without an extra step.

The script always exits 0 (advisory). Use ``--strict`` to exit 1 on regression.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import statistics
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__.split("\n", maxsplit=1)[0])
    p.add_argument("--current-accuracy-long", type=float, default=None)
    p.add_argument("--results-dir", type=Path, default=None)
    p.add_argument("--history", type=Path, required=True)
    p.add_argument("--window", type=int, default=7)
    p.add_argument("--threshold", type=float, default=0.03)
    p.add_argument("--append", action="store_true")
    p.add_argument("--strict", action="store_true")
    p.add_argument("--sha", default="")
    return p


def _discover_accuracy_long(results_dir: Path) -> float | None:
    """Best-effort scan of ai-agent-evals output for ``accuracy_long``.

    The action's exact output schema isn't pinned in this repo; we look for any
    JSON file under ``results_dir`` and try a few known shapes:

    1. Per-row records with ``metadata.duration_bucket == "long"`` and a
       numeric ``qprisma.video_mme_mcq`` (or ``score``) field — mean those.
    2. Aggregated summary objects with an ``accuracy_long`` key.

    Returns ``None`` if nothing parseable is found.
    """
    if not results_dir.exists():
        return None

    candidates = sorted(results_dir.rglob("*.json")) + sorted(results_dir.rglob("*.jsonl"))
    long_scores: list[float] = []
    summary_value: float | None = None

    for path in candidates:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue

        # Try JSONL first (one record per line)
        rows: list[dict] = []
        if path.suffix == ".jsonl":
            for line in text.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(obj, dict):
                    rows.append(obj)
        else:
            try:
                obj = json.loads(text)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, list):
                rows = [r for r in obj if isinstance(r, dict)]
            elif isinstance(obj, dict):
                # Aggregate summary?
                for key in ("accuracy_long", "qprisma.video_mme_mcq.accuracy_long"):
                    if key in obj and isinstance(obj[key], int | float):
                        summary_value = float(obj[key])
                        break
                # Or a wrapper around per-row results
                for key in ("results", "rows", "records"):
                    if isinstance(obj.get(key), list):
                        rows = [r for r in obj[key] if isinstance(r, dict)]
                        break

        for row in rows:
            md = row.get("metadata") or row.get("inputs") or {}
            bucket = md.get("duration_bucket") if isinstance(md, dict) else None
            if bucket != "long":
                continue
            score = (
                row.get("qprisma.video_mme_mcq")
                or row.get("score")
                or (row.get("scores") or {}).get("qprisma.video_mme_mcq")
            )
            if isinstance(score, int | float):
                long_scores.append(float(score))

    if long_scores:
        return sum(long_scores) / len(long_scores)
    return summary_value


def _load_history(path: Path) -> list[dict]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        logger.warning("History file %s is not valid JSON; starting fresh.", path)
        return []
    runs = data.get("runs", []) if isinstance(data, dict) else []
    return [r for r in runs if isinstance(r, dict) and "accuracy_long" in r]


def _write_step_summary(text: str) -> None:
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary:
        return
    with Path(summary).open("a", encoding="utf-8") as f:
        f.write(text)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = _build_parser().parse_args(argv)

    current = args.current_accuracy_long
    if current is None and args.results_dir is not None:
        current = _discover_accuracy_long(args.results_dir)
        if current is None:
            logger.info("No parseable accuracy_long under %s; skipping.", args.results_dir)
            _write_step_summary(
                "### Video-MME regression check\n"
                f"- Skipped: no parseable `accuracy_long` found under `{args.results_dir}`.\n"
                "- Action results may still be available in the Foundry portal.\n"
            )
            return 0
    if current is None:
        logger.error("Provide either --current-accuracy-long or --results-dir.")
        return 0  # advisory: don't fail CI on misconfiguration
    current = float(current)

    history = _load_history(args.history)
    recent = history[-args.window :] if history else []
    values = [float(r["accuracy_long"]) for r in recent]

    if not values:
        logger.info("No baseline yet (history empty); skipping regression check.")
        _write_step_summary(
            f"### Video-MME regression check\n"
            f"- Current `accuracy_long`: **{current:.4f}**\n"
            f"- Baseline: _none yet_ (cold start)\n"
        )
    else:
        median = statistics.median(values)
        drop = median - current
        regressed = drop > args.threshold
        verdict = "❌ regression" if regressed else "✅ within tolerance"
        logger.info(
            "current=%.4f median(last %d)=%.4f drop=%.4f threshold=%.4f -> %s",
            current,
            len(values),
            median,
            drop,
            args.threshold,
            verdict,
        )
        _write_step_summary(
            f"### Video-MME regression check\n"
            f"- Current `accuracy_long`: **{current:.4f}**\n"
            f"- Rolling median (last {len(values)} runs): **{median:.4f}**\n"
            f"- Drop: **{drop:+.4f}** (threshold: {args.threshold:.4f})\n"
            f"- Verdict: **{verdict}**\n"
        )
        if regressed:
            print(  # noqa: T201 - GitHub Actions annotation
                f"::warning title=Video-MME regression::accuracy_long dropped "
                f"{drop:.4f} below the rolling median of the last {len(values)} runs "
                f"(current={current:.4f}, median={median:.4f}, threshold={args.threshold:.4f})"
            )
            if args.strict:
                return 1

    if args.append:
        args.history.parent.mkdir(parents=True, exist_ok=True)
        runs = history + [{"accuracy_long": current, "sha": args.sha}]
        args.history.write_text(json.dumps({"runs": runs}, indent=2))
        logger.info("Appended current run to %s (total runs: %d).", args.history, len(runs))

    return 0


if __name__ == "__main__":
    sys.exit(main())
