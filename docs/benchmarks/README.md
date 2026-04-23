# QPrisma Benchmarks

Headline benchmark numbers for each QPrisma release. Numbers below are populated
by the GitHub Actions workflows in `.github/workflows/` (Video-MME and the
quarterly red-team) and by the `qprisma.long_context_grounding` evaluator.

> **Status:** scaffolding. Real numbers land here after the first full Video-MME
> nightly run completes against the deployed `qprisma-video-agent`. Until then,
> values are marked `TBD` and example placeholders illustrate the shape.

## Headline numbers (per release)

| Release | Date | `video_mme_overall` | `video_mme_long` | `qprisma.long_context_grounding` | `qprisma.source_grounding` |
|---|---|---|---|---|---|
| _example_ | _2026-04-20_ | _0.71_ | _0.58_ | _0.82_ | _0.77_ |
| current | TBD | TBD | TBD | TBD | TBD |

**How to read these:**

- `video_mme_overall` — accuracy on the full 2,700-question Video-MME set (mean
  of `with_subtitles` and `without_subtitles`). Comparable to the public Video-MME
  leaderboard. Source: the latest published `qprisma.video_mme_mcq` evaluator
  revision in the Foundry catalog.
- `video_mme_long` — accuracy on the long-duration bucket only. This is the
  primary signal for QPrisma's long-context retrieval pipeline (Neo4j +
  hierarchical context + hybrid search).
- `qprisma.long_context_grounding` — fraction of agent answers that cite at
  least one precise frame/timestamp anchor that lies inside the retrieved
  context window. 0.0 = no temporal anchor; 0.5 = soft temporal language only;
  1.0 = at least one in-window precise anchor. Source: E1 evaluator
  (`backend/evaluation_foundry/evaluators/long_context_grounding.py`).
- `qprisma.source_grounding` — existing prompt-judge evaluator. Listed here for
  trend tracking next to the new long-context metric.

> VideoRAG / LongerVideos win-rate is **out of scope** for this dashboard for
> now (Phase 3 skipped). Re-add the column if Phase 3 is unblocked.

## How to update this file

This file is updated **manually** at release time, not on every PR:

1. After a successful nightly Video-MME run on `main`, open the workflow
   summary and copy the four headline numbers (`video_mme_overall`,
   `video_mme_long`, plus the `long_context_grounding` and `source_grounding`
   means from the cluster-analysis CSV).
2. Append a row to the table above with the release tag and date.
3. Commit under `docs/benchmarks/` so the change is tied to the release.

Do **not** rewrite history — each row is the canonical record for that release.

## Related

- Evaluator wiring: `backend/evaluation_foundry/register_evaluators.py`
- Foundry data emission: `backend/evaluation_foundry/benchmarks/video_mme/emit_foundry_data.py`
- Workflow: `.github/workflows/evaluate-agent.yml` (job `evaluate-video-mme`)
- Cost envelope: [`cost_envelope.md`](./cost_envelope.md)
- Full evaluation guide: [`../EVALUATION_GUIDE.md`](../EVALUATION_GUIDE.md)
