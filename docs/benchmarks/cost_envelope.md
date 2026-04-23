# Benchmark cost envelope

Estimates for what each benchmark run costs (tokens + storage + wall-clock)
so we can decide cadence — per-PR vs nightly vs weekly. Numbers are **planning
estimates only**; replace with measured values after the first full nightly
run completes.

## Video-MME

### Per-row cost

| Component | Estimate | Notes |
|---|---|---|
| Agent input tokens | ~3,000 | MCQ prompt + retrieved context (frames metadata, captions, graph hits) |
| Agent output tokens | ~10 | Single-letter answer (`A`/`B`/`C`/`D`) per Video-MME prompt template |
| Tool call overhead | ~2,000 | Average across `search_*`, `analyze_*`, hybrid retrieval |
| Judge tokens (deterministic path) | 0 | `qprisma.video_mme_mcq` is deterministic regex on the agent answer; **no judge call** in the code-based path |
| Judge tokens (prompt fallback) | ~200 in / ~5 out | Only if SDK lacks `CodeBasedEvaluatorDefinition` and we use the prompt-judge fallback |
| Storage write | 0 | Agent reads from the warm Postgres/Neo4j/Redis state; no new artifacts persisted per row |

### Per-run totals

- **Smoke (V0+V3.5)**: 5 videos × ~3 questions × 2 subtitle modes ≈ **30 rows**.
  - Token cost: ~30 × 5,000 ≈ **150K tokens** total (effectively free).
  - Wall-clock: ~3-5 min including agent calls + Foundry post-processing.
- **PR run (default `--limit 50`)**: 50 rows × 2 modes ≈ **100 rows**.
  - Token cost: ~500K tokens. **<$2** at GPT-4o rates.
  - Wall-clock: ~10-15 min.
- **Nightly full run**: 2,700 questions × 2 subtitle modes ≈ **5,400 rows**.
  - Token cost: ~27M tokens. **~$50-80** per nightly at GPT-4o rates (rough
    order of magnitude; actual depends on the agent's average context size).
  - Wall-clock: ~2-4 h on the current `microsoft/ai-agent-evals` concurrency.

### One-time ingest cost

- Disk: ~900 mp4 files in `data/datasets/_private/video_mme/` — ~250-400 GB
  depending on resolution. Not committed; one-time download from HuggingFace.
- Blob: ~250-400 GB stored under benchmark `media_id`s. Cleanup query in the
  plan (`DELETE FROM media WHERE user_id='user_7541242e88e3' AND benchmark_name IS NOT NULL`).
- Celery processing: equivalent to ~900 customer uploads. Run once, off-hours.

## Quarterly red-team (E3)

| Component | Estimate | Notes |
|---|---|---|
| Per-strategy attack turns | ~5 turns × ~200 tokens in/out | From `num_turns: 5` in the manifest |
| Strategies × risk categories | 3 × 1 = 3 attack streams | Per `qprisma_quarterly_v1.yaml` |
| Total tokens / quarterly run | ~3K turns × ~400 tokens ≈ **1.2M tokens** | Includes Foundry-side judge for prohibited-actions classification |
| Wall-clock | ~30-60 min | Bounded by `timeout_seconds: 3600` |
| Cadence | Quarterly | Stable manifest; bump suffix on changes |

## Cadence recommendation

| Benchmark | PR | Nightly | Quarterly |
|---|---|---|---|
| Video-MME (`--limit 50`) | ✅ | — | — |
| Video-MME full | — | ✅ | — |
| Quarterly red-team | — | — | ✅ |
| `qprisma.long_context_grounding` | ✅ (rides on existing eval) | ✅ (rides on Video-MME nightly) | — |

Promote any of these to a different cadence only after the cost numbers above
are replaced with measured values from at least one full run.

## Out of scope

VideoRAG / LongerVideos win-rate (Phase 3) — costs not estimated until the
phase is unblocked.
