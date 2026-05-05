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

The evaluation runs manually via `.github/workflows/evaluate-agent.yml`:
- **Manual**: `workflow_dispatch` with optional version override
- Optional `run-redteam=true` launches the **cloud Foundry AI Red Teaming** job

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
export EVAL_USER_ID=<runtime-user-id>
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

### Run cloud red-team locally

```bash
cd backend
export AZURE_AI_PROJECT_ENDPOINT=https://aif-qprisma-dev.services.ai.azure.com/api/projects/aif-qprisma-dev-project
export AZURE_AI_MODEL_DEPLOYMENT_NAME=gpt-5.5
python -m evaluation_foundry.redteam_eval \
  --agent-id qprisma-video-agent:<version> \
  --endpoint "$AZURE_AI_PROJECT_ENDPOINT" \
  --model-deployment "$AZURE_AI_MODEL_DEPLOYMENT_NAME" \
  --strategies base64,flip,indirect_jailbreak \
  --risk-categories prohibited_actions \
  --output ./redteam-results.json
```

## GitHub Variables & Secrets

| Variable/Secret | Type | Description |
|-----------------|------|-------------|
| `EVAL_MEDIA_ID_1` | Variable | UUID of test video 1 (already indexed) |
| `EVAL_MEDIA_ID_2` | Variable | UUID of test video 2 (already indexed) |
| `EVAL_USER_ID` | Secret | Current runtime user ID recognized by the hosted agent |
| `FOUNDRY_PROJECT_ENDPOINT` | Variable | AI Foundry project endpoint URL |
| `AZURE_OPENAI_DEPLOYMENT_GPT` | Variable | Foundry/OpenAI deployment used by task-adherence in cloud red-team |

## Cloud red-team prerequisites

- Foundry project in a region that supports cloud red teaming
- **Azure AI User** role on the Foundry project
- Hosted agent deployed in that same Foundry project
- This workflow uses the **cloud Foundry Agent red-team path**, not the local PyRIT `azure.ai.evaluation.red_team.RedTeam` runner

## Evaluators

### Built-in (Azure AI Foundry)
- **Quality**: Coherence, Fluency, Response Completeness
- **RAG**: Groundedness, Relevance
- **Agent**: Task Adherence, Task Completion, Tool Call Accuracy, Tool Selection
- **Safety**: Violence, Hate/Unfairness, Sexual, Self-Harm, Indirect Attack

### Custom (QPrisma-specific)
- **Temporal Specificity**: Evaluates timestamp/temporal reference quality (1-5 scale)
- **Source Grounding**: Evaluates video evidence citation quality (1-5 scale)
