# QPrisma Evaluation Benchmarks Reference

## Available Configs

| Config | File | Description |
|--------|------|-------------|
| `custom_eval` | `evaluation/configs/custom_eval.json` | 30 MC questions on Ignite Keynote, QPrisma vs Direct Search, no batch API |
| `quick_test` | `evaluation/configs/quick_test.json` | Video-MME subset, QPrisma vs Naive RAG |
| `video_mme_full` | `evaluation/configs/video_mme_full.json` | Full Video-MME benchmark |
| `mlvu_full` | `evaluation/configs/mlvu_full.json` | Full MLVU benchmark |
| `ablation_study` | `evaluation/configs/ablation_study.json` | 8 QPrisma variants + naive-rag baseline |

## Custom QPrisma Benchmark

**Location**: `data/benchmarks/qprisma_first_eval/benchmark.json`
**Video**: Microsoft Ignite 2024 Keynote (2.5 hours, already indexed)
**Questions**: 30 multiple-choice (10 easy + 20 harder)

### Question Categories

| Category | Count | Description |
|----------|-------|-------------|
| `topic_understanding` | 2 | Theme identification |
| `visual_perception` | 3 | Stage, lighting, audience |
| `content_recognition` | 4 | Products, features, demos |
| `entity_recognition` | 4 | Speakers, companies |
| `temporal_understanding` | 2 | Duration, timing |
| `temporal_reasoning` | 4 | Sequence ordering, before/after |
| `multi_hop_reasoning` | 4 | Cross-modal evidence, chain reasoning |
| `needle_in_haystack` | 3 | Specific brief mentions |
| `negation_reasoning` | 4 | What did NOT happen, false premises |

## Method Registry

### QPrisma Variants (Ablation)

| Method Name | Description |
|-------------|-------------|
| `qprisma-full` | Complete pipeline: agent + KG + reranking + all modalities |
| `qprisma-noagent` | Single-shot RAG (bypass ReAct loop) |
| `qprisma-flat` | Flat embeddings, vector-only scoring, no graph/temporal |
| `qprisma-vectoronly` | Vector similarity only, no reranking, no expansion |
| `qprisma-norerank` | Full pipeline minus LLM re-ranking |
| `qprisma-visualonly` | Visual frames only, no audio/transcript |
| `qprisma-audioonly` | Transcript only, no visual frames |
| `qprisma-fixedtokens` | Half context budget (50k tokens vs 100k default) |

### Baselines

| Method Name | Description |
|-------------|-------------|
| `naive-rag` | Naive RAG baseline (uniform frames + single LLM call) |
| `uniform-8` | 8 uniform frames + GPT-4o |
| `uniform-16` | 16 uniform frames + GPT-4o |
| `uniform-32` | 32 uniform frames + GPT-4o |
| `openai-gpt-4o` | Direct GPT-4o with video frames |
| `gemini-1.5-pro` | Gemini 1.5 Pro with native video |

### API-Based Methods (run_first_eval.py)

| Method Name | Description |
|-------------|-------------|
| `qprisma-full` (APIChatAdapter) | Calls `/chat/agent` endpoint for full agent pipeline |
| `direct-search` (DirectSearchAdapter) | Calls `/search` + `/chat` for naive RAG |

## Evaluation Metrics

### Accuracy Metrics
- **MC Accuracy**: Correct choice / total questions
- **Accuracy by Category**: Grouped by question category
- **Accuracy by Duration Tier**: Short / Medium / Long / Very Long

### Retrieval Metrics
- **Recall@k**: Fraction of relevant items in top-k
- **nDCG@k**: Normalized discounted cumulative gain
- **MRR**: Mean reciprocal rank
- **Context Precision/Recall**: RAG context quality

### Temporal Metrics
- **Mean IoU**: Intersection over union of predicted vs ground truth segments
- **R1@{0.3,0.5,0.7}**: Recall at IoU thresholds
- **Timestamp MAE**: Mean absolute error of timestamps

### Faithfulness Metrics
- **Faithfulness Score**: Answer grounded in retrieved context
- **Hallucination Rate**: Claims not supported by evidence

### Efficiency Metrics
- **Latency**: Mean, P50, P95 response time
- **Tool Calls**: Average agent tool invocations
- **Token Usage**: Total tokens consumed
- **Cost**: Estimated API cost per question

### LLM Judge Metrics (7 dimensions)
- Comprehensiveness, Empowerment, Trustworthiness, Depth, Density
- Temporal Specificity (QPrisma extension)
- Source Grounding (QPrisma extension)

## External Benchmark Setup

### Video-MME

1. **Download benchmark data**:
```bash
cd backend
python -m evaluation.scripts.download_benchmarks --benchmark video_mme
```

2. **Download video files** (manual):
Follow the manifest at `data/benchmarks/video_mme/manifest.json` to download videos from their sources. Place them in `data/benchmarks/video_mme/videos/`.

3. **Index videos into QPrisma**:
```bash
python -m evaluation.scripts.index_videos --benchmark video_mme --video-dir data/benchmarks/video_mme/videos
```

4. **Run evaluation**:
```bash
python -m evaluation.run_evaluation --config evaluation/configs/video_mme_full.json
```

### MLVU

1. **Download benchmark data**:
```bash
cd backend
python -m evaluation.scripts.download_benchmarks --benchmark mlvu
```

2. **Download video files** (manual):
Follow the manifest at `data/benchmarks/mlvu/manifest.json`. Place videos in `data/benchmarks/mlvu/videos/`.

3. **Index videos**:
```bash
python -m evaluation.scripts.index_videos --benchmark mlvu --video-dir data/benchmarks/mlvu/videos
```

4. **Run evaluation**:
```bash
python -m evaluation.run_evaluation --config evaluation/configs/mlvu_full.json
```

## Creating Custom Configs

Config files follow the `EvalConfig` Pydantic schema defined in `evaluation/models/eval_schemas.py`.

```json
{
  "benchmarks": [
    {
      "name": "my_benchmark",
      "data_path": "data/benchmarks/my_benchmark/questions.json",
      "video_dir": "data/benchmarks/my_benchmark/videos",
      "task_type": "multiple_choice",
      "has_temporal_annotations": false
    }
  ],
  "methods": [
    {"name": "qprisma-full", "display_name": "QPrisma", "is_baseline": false},
    {"name": "naive-rag", "display_name": "Baseline", "is_baseline": true}
  ],
  "baseline_method": "naive-rag",
  "judge_model": "gpt-4o",
  "num_runs": 1,
  "use_batch_api": false,
  "output_dir": "evaluation/results/my_benchmark"
}
```

Benchmark data files should be JSON arrays of objects matching the `BenchmarkEntry` schema:
```json
[
  {
    "question_id": "q1",
    "video_id": "uuid-here",
    "question": "What is shown?",
    "choices": ["A", "B", "C", "D"],
    "correct_answer": "B",
    "category": "visual_perception",
    "domain": "technology",
    "duration_tier": "long",
    "video_duration_seconds": 3600.0,
    "benchmark": "my_benchmark"
  }
]
```
