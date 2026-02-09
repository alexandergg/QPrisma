# QPrisma Evaluation Plan: Long-Context Video Understanding

## 1. Executive Summary

This document defines a comprehensive evaluation framework for QPrisma's long-context video understanding capabilities. It is informed by the VideoRAG (HKUDS) evaluation methodology while substantially extending it to cover retrieval quality, temporal grounding, hallucination detection, ablation analysis, and efficiency — areas VideoRAG does not address.

### QPrisma's Core Innovations to Evaluate

| # | Innovation | Evaluation Target |
|---|-----------|-------------------|
| 1 | Hierarchical Knowledge Graph (Video→Chapter→Scene→Frame) | Does multi-level decomposition reduce accuracy degradation on long videos? |
| 2 | Matryoshka Two-Pass Vector Search (512d→3072d) | Same retrieval quality at 15-20x speed? |
| 3 | Multi-Signal Hybrid Scoring (vector + fulltext + graph + temporal) | Improvement over pure vector similarity? |
| 4 | Multimodal Unified Graph (visual + audio + entities) | Benefit of fusing modalities in one KG? |
| 5 | Adaptive Token Budgeting (entropy-based) | Cost reduction without quality loss? |
| 6 | LLM-Enhanced Re-ranking | Precision improvement on ambiguous queries? |
| 7 | ReAct Agent with 16 tools | Iterative reasoning vs. single-shot RAG? |

---

## 2. Learning from VideoRAG's Evaluation

### What VideoRAG Does (Their Approach)

VideoRAG evaluates on a **custom "LongerVideos" benchmark** (164 videos, 602 questions, ~135 hours) using **purely LLM-as-Judge** evaluation (GPT-4o-mini) across 5 qualitative dimensions:

| Dimension | Definition |
|-----------|-----------|
| Comprehensiveness | Detail coverage of all question aspects |
| Empowerment | Helps reader understand and judge the topic |
| Trustworthiness | Credibility and alignment with common knowledge |
| Depth | In-depth analysis vs. surface-level information |
| Density | Relevant information without redundancy |

**Two protocols:**
- **Win-Rate** (pairwise A/B with position debiasing) for RAG baselines
- **Quantitative 1-5 scoring** relative to NaiveRAG for video understanding methods

Both run **5 times** via OpenAI Batch API for statistical reliability.

### VideoRAG's Strengths (We Adopt)

| Pattern | How We Use It |
|---------|---------------|
| LLM-as-Judge with structured Pydantic output | Same approach, but use GPT-4o (stronger judge) |
| Position debiasing in pairwise comparisons | Same — run both orderings, aggregate |
| 5x repeated evaluation runs | Same — report mean ± std |
| Domain-stratified reporting | Same — report per video category |
| Batch API for evaluation | Same — cost-efficient at scale |
| Pre-generated answers stored as files | Same — reproducible evaluation artifacts |

### VideoRAG's Gaps (We Fill)

| Gap | QPrisma's Addition | Why It Matters |
|-----|-------------------|----------------|
| No standard benchmarks | Video-MME, MLVU, HourVideo | Community-comparable results |
| Machine-generated questions only | Human-authored + machine QA pairs | Higher-quality evaluation signal |
| No retrieval evaluation | Recall@K, NDCG@K, MRR, Context P/R | Isolates search from generation quality |
| No temporal grounding | IoU, R@1@0.5, timestamp MAE | Critical for video understanding |
| No hallucination detection | Faithfulness score, temporal hallucination rate | Trustworthiness beyond self-reported |
| No ablation study | 9 QPrisma configurations | Quantifies each innovation's value |
| No efficiency analysis | Latency, cost/query, tokens/query | Production readiness |
| No duration scaling | Accuracy vs. video length curves | Core long-context claim |
| No needle-in-a-haystack | V-NIAH at 5-120 min | Stress test for retrieval |
| Single weak judge (4o-mini) | GPT-4o judge + inter-judge agreement | Stronger evaluation signal |

---

## 3. Benchmarks & Datasets

### 3.1 Standard Benchmarks (Community Comparison)

| Benchmark | Venue | Videos | QA Pairs | Max Length | Task Type | Why |
|-----------|-------|--------|----------|------------|-----------|-----|
| **Video-MME** | CVPR 2025 | 900 | 2,700 | 1 hr | MC | Gold standard; 3 duration tiers show degradation |
| **MLVU** | CVPR 2025 | ~2K | 3,102 | 2 hr | MC + Open | 9 task types; needle QA, action count/order |
| **HourVideo** | NeurIPS 2024 | 500 | 12,976 | 2 hr | MC (5-way) | Hardest: 85% human vs. 37% best model |

**Evaluation protocol**: Follow each benchmark's official evaluation protocol for comparability. Report per-task and per-duration results.

### 3.2 QPrisma-Bench (Internal, VideoRAG-Style + Extensions)

Inspired by VideoRAG's LongerVideos but with human curation and richer annotation:

**Video Corpus**: 50 videos, 30 min – 2 hours each

| Domain | Collections | Videos | Duration |
|--------|-------------|--------|----------|
| Lectures/Tutorials | 6 | 18 | ~20 hr |
| Documentaries | 4 | 12 | ~15 hr |
| Meetings/Presentations | 5 | 10 | ~12 hr |
| Entertainment/Film | 3 | 6 | ~10 hr |
| Surveillance/Egocentric | 2 | 4 | ~5 hr |

**Question Design**: 950 QA pairs across 10 categories

| Category | Count | Source | Description |
|----------|-------|--------|-------------|
| Needle-in-Haystack | 200 | Human | Find specific detail in 30-60 min video |
| Cross-Segment Reasoning | 150 | Human | Connect info from 2+ distant segments |
| Entity Tracking | 100 | Human | Track person/object across video |
| Temporal Ordering | 100 | Human + LLM | Order events correctly |
| Multi-Hop Graph | 100 | Human | Requires graph traversal (entity→scene→chapter) |
| Multimodal Fusion | 100 | Human | Requires both visual + audio evidence |
| Summarization | 50 | LLM-generated | Chapter/video-level summaries |
| Highlight Detection | 50 | Human | Identify key moments |
| OCR/Text Retrieval | 50 | Human | Find on-screen text |
| Speaker Attribution | 50 | Human | "What did person X say about Y?" |

**Annotation Protocol**:
- 3 human annotators per question (inter-annotator agreement via Fleiss' kappa)
- Ground-truth includes: correct answer, relevant timestamp ranges, relevant KG nodes
- Open-ended questions include reference answers for LLM judge comparison

### 3.3 Needle-in-a-Haystack Test Set (Synthetic)

| Duration Tier | Videos | Needles/Video | Questions |
|---------------|--------|---------------|-----------|
| 5 min | 50 | 3 (early/mid/late) | 150 |
| 15 min | 50 | 3 | 150 |
| 30 min | 50 | 3 | 150 |
| 60 min | 50 | 3 | 150 |
| 120 min | 50 | 3 | 150 |
| **Total** | **250** | | **750** |

Insert distinctive visual/audio "needle" facts at controlled temporal positions. Ask factual questions targeting each needle.

---

## 4. Methods to Compare

### 4.1 External Baselines

| Method | Category | Description | Compare On |
|--------|----------|-------------|------------|
| **GPT-4o (native)** | End-to-End VLM | Upload video frames directly | All benchmarks |
| **Gemini 1.5 Pro** | End-to-End VLM | Native 1M token context | All benchmarks |
| **VideoAgent** | Agent-Based | Iterative frame selection (8 frames avg) | All benchmarks |
| **Video-RAG** | RAG (text) | Auxiliary text retrieval + VLM | QPrisma-Bench |
| **NaiveRAG** | RAG (baseline) | Uniform text chunks + embedding retrieval | QPrisma-Bench |
| **GraphRAG** | RAG (graph) | Microsoft GraphRAG (local + global) | QPrisma-Bench |
| **LightRAG** | RAG (hybrid) | Lightweight dual-level retrieval | QPrisma-Bench |

### 4.2 QPrisma Configurations (Ablation)

| Config | What Changes | Tests Value Of |
|--------|-------------|----------------|
| **QPrisma-Full** | Complete pipeline | All innovations combined |
| **QPrisma-Flat** | No hierarchy (flat frame embeddings only) | Hierarchical decomposition |
| **QPrisma-SinglePass** | Full 3072d only (no Matryoshka coarse pass) | Two-pass search efficiency |
| **QPrisma-VectorOnly** | Vector similarity only (no fulltext/graph/temporal) | Multi-signal hybrid scoring |
| **QPrisma-NoRerank** | No LLM re-ranking | LLM re-ranking value |
| **QPrisma-VisualOnly** | Visual frames only (no audio/transcript) | Multimodal fusion |
| **QPrisma-AudioOnly** | Transcript only (no visual frames) | Visual vs. audio contribution |
| **QPrisma-NoAgent** | Single-shot RAG (no ReAct loop) | Agentic iterative reasoning |
| **QPrisma-FixedTokens** | Fixed 600 tokens/frame (no adaptive budgeting) | Adaptive token budgeting |

---

## 5. Evaluation Metrics

### 5.1 Answer Quality (VideoRAG-Style + Extensions)

**LLM-as-Judge (Adopted from VideoRAG, strengthened)**:

| Dimension | Definition | Scale |
|-----------|-----------|-------|
| Comprehensiveness | Coverage of all question aspects | 1-5 |
| Empowerment | Helps reader understand and judge | 1-5 |
| Trustworthiness | Credibility and factual alignment | 1-5 |
| Depth | In-depth analysis vs. surface-level | 1-5 |
| Density | Signal-to-noise ratio | 1-5 |
| **Temporal Specificity** (new) | Includes accurate timestamps and temporal context | 1-5 |
| **Source Grounding** (new) | Claims backed by identifiable video evidence | 1-5 |

**Protocol** (following VideoRAG):
- Judge model: **GPT-4o** (not 4o-mini — stronger evaluation signal)
- **5 independent runs**, report mean ± std
- **Pydantic structured output** for valid JSON enforcement
- **Position debiasing** on pairwise comparisons (both orderings)
- Answers stored as `answer_{query_id}.md` for reproducibility

**Two evaluation modes** (adopted from VideoRAG):
1. **Win-Rate** (pairwise): QPrisma vs. each RAG baseline
2. **Quantitative 1-5** (absolute): All methods scored relative to NaiveRAG

**MC Accuracy** (for standard benchmarks): correct / total, stratified by:
- Video duration tier (short / medium / long)
- Task category (per benchmark's taxonomy)

### 5.2 Retrieval Quality (New — VideoRAG doesn't measure this)

| Metric | Formula | What It Measures |
|--------|---------|------------------|
| Recall@K (K=1,5,10,20) | \|relevant ∩ top-K\| / \|relevant\| | Coverage |
| Precision@K | \|relevant ∩ top-K\| / K | Signal-to-noise |
| NDCG@K | DCG@K / IDCG@K | Ranking quality |
| MRR | 1/\|Q\| × Σ(1/rank_q) | First relevant result position |
| Context Precision | Relevant retrieved / total retrieved (LLM-judged) | Noise in RAG context |
| Context Recall | GT claims covered by context / total GT claims (LLM-judged) | Completeness |

### 5.3 Temporal Grounding (New)

| Metric | Description |
|--------|-------------|
| IoU | Overlap between predicted and ground-truth time segments |
| R@1 at IoU=0.3/0.5/0.7 | Fraction of queries where IoU ≥ threshold |
| mIoU | Mean IoU across all predictions |
| Timestamp MAE | Mean absolute error of point-in-time predictions (seconds) |

### 5.4 Faithfulness & Hallucination (New)

| Metric | Method |
|--------|--------|
| Faithfulness Score | Claims in answer supported by retrieved context / total claims |
| Object Hallucination Rate | % of answers mentioning non-existent entities |
| Temporal Hallucination Rate | % of answers with wrong timestamps or ordering |
| Cross-Segment Confusion | % of answers attributing info to wrong segment |
| Source Attribution Rate | % of claims with valid timestamp citations |

### 5.5 Efficiency & Cost (New)

| Metric | Unit |
|--------|------|
| Indexing Latency | sec / min of video |
| Query Latency (P50/P95/P99) | milliseconds |
| Retrieval Latency | milliseconds |
| Indexing Cost | $ / min of video |
| Query Cost | $ / query |
| Tokens Processed | tokens / query |
| Storage Overhead | MB / min of video |

---

## 6. Evaluation Pipeline Architecture

### 6.1 Pipeline Structure (Adapted from VideoRAG's 4-Step Pattern)

```
backend/evaluation/
├── benchmarks/
│   ├── video_mme_loader.py        # Load Video-MME format
│   ├── mlvu_loader.py             # Load MLVU format
│   ├── hour_video_loader.py       # Load HourVideo format
│   └── qprisma_bench_loader.py    # Load QPrisma-Bench
│
├── answer_generation/
│   ├── generate_answers.py        # Run each method, save answer_{id}.md
│   ├── configs/                   # Per-method configurations
│   │   ├── qprisma_full.yaml
│   │   ├── qprisma_flat.yaml
│   │   ├── qprisma_noagent.yaml
│   │   ├── naive_rag.yaml
│   │   ├── gpt4o_native.yaml
│   │   └── ...
│   └── answers/                   # Pre-generated answers (artifacts)
│       ├── qprisma_full/answer_001.md
│       ├── naive_rag/answer_001.md
│       └── ...
│
├── judges/
│   ├── winrate_judge.py           # Pairwise A/B (VideoRAG-style)
│   ├── quantitative_judge.py      # 1-5 scoring (VideoRAG-style)
│   ├── retrieval_judge.py         # Context Precision/Recall
│   ├── faithfulness_judge.py      # Claim verification
│   └── prompts/
│       ├── winrate_prompt.txt
│       ├── quantitative_prompt.txt
│       ├── retrieval_prompt.txt
│       └── faithfulness_prompt.txt
│
├── metrics/
│   ├── accuracy.py                # MC accuracy, per-tier
│   ├── retrieval.py               # Recall@K, NDCG, MRR
│   ├── temporal.py                # IoU, R@1, mIoU, MAE
│   ├── hallucination.py           # Object/temporal/cross-segment
│   └── efficiency.py              # Latency, cost, tokens
│
├── batch_pipeline/                # VideoRAG-inspired batch evaluation
│   ├── batch_upload.py            # Step 1: Submit to OpenAI Batch API
│   ├── batch_download.py          # Step 2: Retrieve results
│   ├── batch_parse.py             # Step 3: Validate + retry malformed
│   └── batch_calculate.py         # Step 4: Aggregate scores
│
├── analysis/
│   ├── ablation.py                # Compare QPrisma configurations
│   ├── degradation_curve.py       # Accuracy vs. video duration
│   ├── pareto.py                  # Cost-quality frontier
│   ├── needle_haystack.py         # V-NIAH analysis
│   └── significance.py            # Statistical tests (paired t-test, bootstrap CI)
│
├── visualization/
│   ├── charts.py                  # Generate all plots
│   └── tables.py                  # Generate LaTeX/markdown tables
│
└── run_evaluation.py              # Master orchestrator
```

### 6.2 Batch Evaluation Protocol (Following VideoRAG)

```
Step 1: batch_upload.py
  - For each (question, method_answer, baseline_answer):
    - Construct judge prompt with Pydantic response_format
    - Create both orderings (position debiasing)
    - Submit to OpenAI Batch API (gpt-4o)
    - Repeat 5 times (run_time = 5)

Step 2: batch_download.py
  - Poll for batch completion
  - Download result files

Step 3: batch_parse.py
  - Validate each response against schema
  - Re-request malformed responses synchronously
  - Multi-threaded processing of 5 result files

Step 4: batch_calculate.py
  - Aggregate by: domain, question category, video duration tier
  - Compute: mean ± std across 5 runs
  - For win-rate: combine original + reversed orderings
  - Output: JSON results + formatted tables
```

---

## 7. Hypotheses & Expected Results

### H1: Hierarchical KG reduces degradation on long videos
- **Test**: QPrisma-Full vs. QPrisma-Flat accuracy across duration tiers
- **Expected**: QPrisma-Full maintains >80% of short-video accuracy at 60+ min; Flat drops >30%
- **Mechanism**: Scene/chapter embeddings provide coarse localization before frame search

### H2: Matryoshka two-pass achieves equivalent quality at 15-20x speed
- **Test**: NDCG@10 for QPrisma-Full vs. QPrisma-SinglePass
- **Expected**: <1% NDCG difference, 15-20x retrieval latency reduction
- **Mechanism**: 512d coarse filters to top-100; 3072d refines within that set

### H3: Multi-signal hybrid scoring outperforms vector-only
- **Test**: NDCG@10, Recall@5 for QPrisma-Full vs. QPrisma-VectorOnly
- **Expected**: 8-15% improvement in NDCG@10
- **Mechanism**: Graph proximity + temporal scoring + fulltext complement vector similarity

### H4: Multimodal fusion beats unimodal
- **Test**: QPrisma-Full vs. -VisualOnly vs. -AudioOnly on QPrisma-Bench
- **Expected**: Full > VisualOnly > AudioOnly by 5-10% each
- **Mechanism**: Visual captures what's shown; audio captures what's said

### H5: ReAct agent outperforms single-shot RAG
- **Test**: QPrisma-Full vs. QPrisma-NoAgent on complex questions (multi-hop, cross-segment)
- **Expected**: 10-20% improvement on complex categories
- **Mechanism**: Iterative tool use enables multi-step reasoning

### H6: LLM re-ranking improves precision
- **Test**: Precision@5 for QPrisma-Full vs. QPrisma-NoRerank
- **Expected**: 10-15% improvement
- **Mechanism**: LLM understands nuance that embedding distance misses

### H7: QPrisma achieves Pareto-optimal cost-quality
- **Test**: Position on (accuracy, cost/query) frontier
- **Expected**: Within 5% of Gemini 1.5 Pro at 60-70% lower per-query cost
- **Mechanism**: Pre-indexed KG + targeted retrieval vs. full-video-per-query

---

## 8. Results Presentation

### 8.1 Main Results Table (VideoRAG Format — Win-Rate)

```
QPrisma-Full Win-Rate vs. RAG Baselines (GPT-4o Judge, 5 runs)

                 Comp.  Empow. Trust. Depth  Dens.  T-Spec. S-Grnd. Overall
vs. NaiveRAG     -%     -%     -%     -%     -%     -%      -%      -%
vs. GraphRAG-L   -%     -%     -%     -%     -%     -%      -%      -%
vs. GraphRAG-G   -%     -%     -%     -%     -%     -%      -%      -%
vs. LightRAG     -%     -%     -%     -%     -%     -%      -%      -%
vs. Video-RAG    -%     -%     -%     -%     -%     -%      -%      -%
```

### 8.2 Quantitative Scoring (VideoRAG Format)

```
Quantitative Scores Relative to NaiveRAG (1-5 scale, 5 runs)

                 Comp.  Empow. Trust. Depth  Dens.  T-Spec. S-Grnd. Overall
QPrisma-Full     -±-    -±-    -±-    -±-    -±-    -±-     -±-     -±-
QPrisma-NoAgent  -±-    -±-    -±-    -±-    -±-    -±-     -±-     -±-
VideoAgent       -±-    -±-    -±-    -±-    -±-    -±-     -±-     -±-
GPT-4o (native)  -±-    -±-    -±-    -±-    -±-    -±-     -±-     -±-
Gemini 1.5 Pro   -±-    -±-    -±-    -±-    -±-    -±-     -±-     -±-
```

### 8.3 Standard Benchmark Results

```
MC Accuracy (%) by Video Duration Tier

                  Video-MME            MLVU              HourVideo
                Short Med  Long All   Short Med Long All  All (5-way)
GPT-4o          --   --   --   --    --   --   --   --   --
Gemini 1.5 Pro  --   --   --   --    --   --   --   --   37.3
VideoAgent      --   --   --   --    --   --   --   --   --
QPrisma-Full    --   --   --   --    --   --   --   --   --
QPrisma-NoAgent --   --   --   --    --   --   --   --   --
Human           --   --   --   --    --   --   --   --   85.0
```

### 8.4 Retrieval Quality (QPrisma Configurations)

```
                 Recall@5  NDCG@10  MRR   Ctx-Prec  Ctx-Recall  Retr-Lat(ms)
QPrisma-Full     --        --       --    --        --          150-300
QPrisma-Flat     --        --       --    --        --          --
QPrisma-VecOnly  --        --       --    --        --          --
QPrisma-1Pass    --        --       --    --        --          2000-5000
QPrisma-NoRerank --        --       --    --        --          --
```

### 8.5 Degradation Curve (Key Visualization)

```
Accuracy (%)
100 ┤
 90 ┤  ·
 80 ┤   ·─────── QPrisma-Full (gradual)
 70 ┤    ·
 60 ┤     ·───── Gemini 1.5 Pro
 50 ┤      ·
 40 ┤       ·─── GPT-4o native
 30 ┤        ·
 20 ┤──────────── Random baseline (5-way)
    └──┬──┬──┬──┬──┬──
      5  15 30 60 120 min
      Video Duration →
```

### 8.6 Pareto Frontier (Cost vs. Quality)

```
Accuracy
 90% ┤        ● Gemini (high cost, high acc)
     │
 80% ┤  ★ QPrisma-Full (low cost, competitive acc)
     │
 70% ┤      ○ GPT-4o native
     │
 60% ┤  △ Video-RAG
     │
 50% ┤  □ VideoAgent
     │
 40% ┤
     └──┬──────┬──────┬──────┬──
      $0.01  $0.05  $0.20  $1.00
      Cost per Query →
```

### 8.7 Needle-in-a-Haystack Heatmap

```
                 Needle Position
              Early   Middle   Late
5 min         --%     --%      --%
15 min        --%     --%      --%
30 min        --%     --%      --%
60 min        --%     --%      --%
120 min       --%     --%      --%

(Higher is better. Color: green=90%+, yellow=70-89%, red=<70%)
```

---

## 9. Implementation Timeline

### Phase 0: Evaluation Infrastructure (Week 1-2)
- [ ] Create `backend/evaluation/` module structure
- [ ] Implement batch pipeline (upload/download/parse/calculate)
- [ ] Build metric computation library (retrieval, temporal, faithfulness)
- [ ] Implement judge prompts with Pydantic structured output
- [ ] Set up GPT-4o judge with position debiasing

### Phase 1: QPrisma-Bench Construction (Week 2-4)
- [ ] Curate 50 videos across 5 domains
- [ ] Generate 950 QA pairs (700 human + 250 LLM-generated)
- [ ] Annotate ground-truth segments per question (3 annotators)
- [ ] Compute inter-annotator agreement (Fleiss' kappa ≥ 0.7)
- [ ] Build V-NIAH test set (250 videos × 3 needles)

### Phase 2: Baseline Implementation (Week 3-5)
- [ ] Implement QPrisma ablation configurations
- [ ] Set up GPT-4o native evaluation pipeline
- [ ] Set up Gemini 1.5 Pro evaluation pipeline
- [ ] Implement NaiveRAG, GraphRAG, LightRAG baselines
- [ ] Implement VideoAgent baseline

### Phase 3: Evaluation Execution (Week 5-8)
- [ ] Index all benchmark videos through QPrisma pipeline
- [ ] Generate answers for all methods × all benchmarks
- [ ] Run retrieval evaluation (all QPrisma configs × QPrisma-Bench)
- [ ] Run LLM-as-Judge evaluation (5 runs, batch API)
- [ ] Run standard benchmark evaluation (Video-MME, MLVU, HourVideo)
- [ ] Run V-NIAH stress test
- [ ] Collect efficiency metrics (latency, cost, tokens)

### Phase 4: Analysis & Reporting (Week 8-10)
- [ ] Statistical significance tests (paired t-test, bootstrap CI, p < 0.05)
- [ ] Generate degradation curves, Pareto frontiers, ablation charts
- [ ] Compile results into paper-ready tables and figures
- [ ] Write evaluation report with findings and improvement roadmap

---

## 10. Open Questions for Future Work

1. **Dynamic re-indexing**: Update KG when queries reveal gaps in initial analysis
2. **Active frame re-analysis**: Agent re-analyzes frames with query-specific prompts
3. **Cross-video reasoning**: Answer questions spanning multiple videos
4. **Streaming evaluation**: Test hierarchical pipeline in real-time streaming mode
5. **Domain-specific embeddings**: Fine-tune embeddings for specific video domains
6. **Learned re-ranking**: Replace GPT-4o re-ranker with fine-tuned cross-encoder (10x faster)
7. **Human evaluation**: Supplement LLM judge with human evaluation on subset (100 questions)
