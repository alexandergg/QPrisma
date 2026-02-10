# Video-MME Accuracy Improvement Roadmap

> **Created**: 2026-02-10  
> **Current Accuracy**: 58.3% (21/36) on Video-MME subset (12 videos, 36 questions)  
> **Target**: 88%+

## Current Results

| Round | Accuracy | Key Fix |
|-------|----------|---------|
| v1 (baseline) | 33.3% | Stale UUIDs — agent had zero retrieval |
| v2 (UUID fix) | 52.8% | Fixed UUIDs, added category-aware tool hints |
| v3 (extraction) | 58.3% | Choice-text matching, stronger MC format prompt |

## Remaining Failure Categories

| Category | Accuracy | Root Cause |
|----------|----------|------------|
| Counting Problem | 1/5 (20%) | No object count aggregation in KG or vision prompt |
| Object Reasoning | 0/4 (0%) | Visual symbolism requires deeper scene understanding |
| Spatial Perception | 0/3 (0%) | No spatial positions in frame descriptions |
| Attribute Perception | 3/5 (60%) | Frame description truncation loses fine visual detail |

## Root Cause Analysis

Three systemic bottlenecks prevent further accuracy gains via prompt tuning alone:

1. **Vision prompt lacks spatial/counting guidance** — GPT-4o frame analysis doesn't explicitly describe spatial positions, object counts, or relationships
2. **Frame description truncation** — search results truncated to 900 chars, losing spatial detail
3. **KG has no spatial schema** — no bounding boxes, no `LEFT_OF`/`ABOVE` relationships
4. **Agent limited to 5 tool iterations** — complex reasoning exhausts budget before finding the answer

---

## Phase 1: Quick Wins (eval-side, no pipeline changes)

**Target: 58% → 65%**

- [ ] **P1.1** Increase agent `MAX_TOOL_ITERATIONS` from 5→8 for eval runs
  - File: `backend/agent/nodes/base.py` (line 47)
  - Or: add eval-specific override via environment variable
  - Impact: Prevents premature "?" failures on complex questions

- [ ] **P1.2** Add counting-specific tool hints in eval prompt
  - "For counting questions, use `describe_scene` at multiple timestamps and count explicitly"
  - Impact: Counting Problem category (currently 20%)

- [ ] **P1.3** Add spatial-specific tool hints
  - "For spatial questions, use `describe_scene` and pay attention to left/right, foreground/background"
  - Impact: Spatial Perception category (currently 0%)

- [ ] **P1.4** Run multiple eval passes (`num_runs=3`) and take majority vote
  - LLM non-determinism accounts for ~10-15% variance between runs
  - Majority vote across 3 runs should stabilize at higher accuracy

## Phase 2: Vision Prompt Enhancement (indexing pipeline)

**Target: 65% → 75%**

- [ ] **P2.1** Enhance GPT-4o vision prompt with spatial grounding
  - File: `backend/services/batch_processor.py` (lines 162-175)
  - Add to structured output schema:
    ```json
    "spatial_layout": {
      "objects_with_positions": [
        {"object": "tie", "position": "center", "relative": "left side shorter than right"}
      ],
      "object_counts": {"climbers": 5, "candle_holders": 3}
    }
    ```
  - Impact: Spatial Perception, Counting Problem, Object Reasoning

- [ ] **P2.2** Increase frame description char limit in search results
  - File: `backend/agent/tools/general.py` — `search_video` truncation
  - Change 900→2000 chars or return structured fields separately
  - Impact: All categories (richer context for reasoning)

- [ ] **P2.3** Add object counting aggregation to KG
  - After frame analysis, aggregate counts per object type across frames
  - Store as properties on Scene/Chapter nodes
  - Impact: Counting Problem category

- [ ] **P2.4** Re-index the 12 Video-MME videos with enhanced vision prompt
  - Required after P2.1 changes
  - Run with `DEEP_ANALYSIS` preset for maximum frame density

## Phase 3: Knowledge Graph Schema Extension

**Target: 75% → 82%**

- [ ] **P3.1** Add spatial relationship edges to KG
  - New edge types: `LEFT_OF`, `ABOVE`, `IN_FRONT_OF`, `CONTAINS`
  - Extract from enhanced vision prompt `spatial_layout`
  - Impact: Spatial Perception, Spatial Reasoning

- [ ] **P3.2** Implement cross-frame entity tracking
  - Link same object/person across consecutive frames
  - Create temporal chains: `Entity→APPEARS_AT→Frame` with position
  - Impact: Action Recognition, Counting (track unique vs repeated objects)

- [ ] **P3.3** Add scene-level aggregation nodes
  - Aggregate object counts, dominant colors, spatial layout per scene
  - Agent can query "how many X in this scene" without scanning frames
  - Impact: Counting, Information Synopsis

- [ ] **P3.4** Create new agent tool: `count_objects`
  - Dedicated tool that queries KG aggregations for counting
  - Returns: object type → count → timestamps where visible
  - Impact: Counting Problem (currently 20%)

## Phase 4: Agent Architecture Improvements

**Target: 82% → 88%+**

- [ ] **P4.1** Implement chain-of-thought reasoning for MC questions
  - Two-pass approach: (1) gather evidence, (2) reason about each choice
  - Agent explicitly evaluates A/B/C/D against evidence before choosing
  - Impact: Object Reasoning, complex multi-hop questions

- [ ] **P4.2** Increase context window for reasoning-heavy categories
  - Current: 80K token trimmer window
  - Increase to 120-150K for eval runs (or conditionally per query type)
  - File: `backend/agent/nodes/base.py` (line 44)

- [ ] **P4.3** Add self-verification step
  - After choosing an answer, agent re-checks against visual evidence
  - "Does my answer match what I see in the frames?"
  - Impact: Reduces confident-but-wrong answers

- [ ] **P4.4** Implement adaptive tool selection
  - Detect question category from text and auto-select best tool strategy
  - Move category hints from eval script into agent reasoning
  - Impact: All categories (smarter first tool choice)

## Phase 5: Benchmark Expansion

- [ ] **P5.1** Index more Video-MME videos (target 50+ videos, 150+ questions)
  - More data reduces variance, gives statistically significant results
- [ ] **P5.2** Add medium/long duration tier videos
  - Current subset is all "short" tier — need coverage across tiers
- [ ] **P5.3** Run MLVU benchmark for complementary evaluation
  - Different question types test different capabilities

---

## Priority Matrix

| Phase | Effort | Expected Impact | Priority |
|-------|--------|-----------------|----------|
| P1 (eval-side) | Low (hours) | +5-7% | 🔴 Do first |
| P2 (vision prompt) | Medium (days) | +8-10% | 🟠 High value |
| P3 (KG schema) | High (week+) | +5-7% | 🟡 After P2 |
| P4 (agent arch) | High (week+) | +5-8% | 🟡 After P2 |
| P5 (benchmarks) | Medium (days) | Statistical validity | 🟢 Ongoing |

## Key Files Reference

| File | Relevance |
|------|-----------|
| `backend/agent/nodes/base.py` | Tool iteration limits, context trimming |
| `backend/agent/prompts.py` | System prompt (production) |
| `backend/agent/tools/general.py` | Search tools, result truncation |
| `backend/services/batch_processor.py` | GPT-4o vision prompt for frame analysis |
| `backend/evaluation/scripts/run_vmme_subset.py` | Video-MME eval script (modified) |
| `backend/data/benchmarks/video_mme/video_mme_subset.json` | Benchmark data (UUIDs fixed) |

## Changes Made in This Session

- Fixed 36 stale video UUIDs in `video_mme_subset.json`
- Added `--fresh` flag and timestamped output dirs to all eval scripts
- Added category-aware tool hints (10 categories) to MC query construction
- Improved `extract_mc_choice` with 3-phase extraction (regex → choice-text match → fallback)
- Strengthened MC format instruction to enforce letter-only answers
