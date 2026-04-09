---
name: qprisma-evaluation
description: Run QPrisma Video-MME benchmark evaluation against a remote API deployment.
---

# QPrisma Evaluation Skill

Use this skill to run Azure AI Foundry evaluation against the QPrisma hosted agent.

## Overview

QPrisma's agent (`qprisma-video-agent`) is evaluated using the `microsoft/ai-agent-evals`
GitHub Action with built-in and custom evaluators.

## CI/CD Workflow

The evaluation runs automatically via `.github/workflows/evaluate-agent.yml`:
- **After deploy**: Triggers after `Deploy Hosted Agent` succeeds
- **Weekly**: Monday 06:00 UTC for regression monitoring
- **Manual**: `workflow_dispatch` with optional version override

## Local Commands

### Generate evaluation data (dry-run)

```bash
cd backend
python -m evaluation_foundry.generate_eval_data --dry-run
```

### Generate with real media IDs

```bash
cd backend
export EVAL_MEDIA_ID_1=<uuid>
export EVAL_MEDIA_ID_2=<uuid>
export EVAL_USER_ID=<entra-oid>
python -m evaluation_foundry.generate_eval_data --output-dir ./eval-output
```

### Register custom evaluators (dry-run)

```bash
cd backend
python -m evaluation_foundry.register_evaluators --dry-run
```

### Resolve agent version

```bash
export AZURE_AI_PROJECT_ENDPOINT=https://aif-qprisma-dev.services.ai.azure.com/api/projects/aif-qprisma-dev-project
python scripts/resolve_agent_version.py
```

## GitHub Variables & Secrets

| Variable/Secret | Type | Description |
|-----------------|------|-------------|
| `EVAL_MEDIA_ID_1` | Variable | UUID of test video 1 (already indexed) |
| `EVAL_MEDIA_ID_2` | Variable | UUID of test video 2 (already indexed) |
| `EVAL_USER_ID` | Secret | Entra Object ID of the user who uploaded the videos |
| `FOUNDRY_PROJECT_ENDPOINT` | Variable | AI Foundry project endpoint URL |

## Evaluators

### Built-in (Azure AI Foundry)
- **Quality**: Coherence, Fluency, Response Completeness
- **RAG**: Groundedness, Relevance
- **Agent**: Task Adherence, Task Completion, Tool Call Accuracy, Tool Selection
- **Safety**: Violence, Hate/Unfairness, Sexual, Self-Harm, Indirect Attack

### Custom (QPrisma-specific)
- **Temporal Specificity**: Evaluates timestamp/temporal reference quality (1-5 scale)
- **Source Grounding**: Evaluates video evidence citation quality (1-5 scale)
