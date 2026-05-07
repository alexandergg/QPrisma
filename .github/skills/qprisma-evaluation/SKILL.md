---
name: qprisma-evaluation
description: Run, prepare, or debug QPrisma Video-MME and Azure AI Foundry hosted-agent evaluation against a remote deployment.
---

# QPrisma Evaluation Skill

Use this skill to run Azure AI Foundry evaluation, Video-MME benchmark workflows, cloud red-team
checks, or evaluation data generation for the QPrisma hosted agent.

## Required reads

1. `AGENTS.md`
2. `.github/workflows/evaluate-agent.yml`
3. `.github/workflows/benchmark-video-mme.yml`
4. `backend/evaluation_foundry/`
5. `scripts/resolve_agent_version.py`
6. Hosted-agent docs such as `docs/HOSTED_AGENT.md` when deployment context matters

## Overview

QPrisma's hosted agent (`qprisma-video-agent`) is evaluated using Azure AI Foundry evaluation flows,
including `microsoft/ai-agent-evals`, built-in evaluators, custom evaluators, and optional cloud
red-team checks.

## Prerequisites

- Deployed hosted agent in the target Azure AI Foundry project.
- Valid `FOUNDRY_PROJECT_ENDPOINT`.
- Runtime user/media IDs for video-scoped evaluation data.
- Azure identity with access to the Foundry project.
- Redacted environment values in logs, docs, PRs, and artifacts.

## CI/CD workflow

The evaluation runs manually via `.github/workflows/evaluate-agent.yml`:

- `workflow_dispatch` with optional agent version override.
- Optional `run-redteam=true` launches the cloud Foundry AI Red Teaming job.

## Local commands

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
export AZURE_AI_PROJECT_ENDPOINT=https://<foundry-account>.services.ai.azure.com/api/projects/<project-name>
python scripts/resolve_agent_version.py
```

### Run cloud red-team locally

```bash
cd backend
export AZURE_AI_PROJECT_ENDPOINT=https://<foundry-account>.services.ai.azure.com/api/projects/<project-name>
export AZURE_AI_MODEL_DEPLOYMENT_NAME=gpt-5.5
python -m evaluation_foundry.redteam_eval \
  --agent-id qprisma-video-agent:<version> \
  --endpoint "$AZURE_AI_PROJECT_ENDPOINT" \
  --model-deployment "$AZURE_AI_MODEL_DEPLOYMENT_NAME" \
  --strategies base64,flip,indirect_jailbreak \
  --risk-categories prohibited_actions \
  --output ./redteam-results.json
```

## GitHub variables and secrets

| Variable/Secret | Type | Description |
| --- | --- | --- |
| `EVAL_MEDIA_ID_1` | Variable | UUID of test video 1 already indexed |
| `EVAL_MEDIA_ID_2` | Variable | UUID of test video 2 already indexed |
| `EVAL_USER_ID` | Secret | Current runtime user ID recognized by the hosted agent |
| `FOUNDRY_PROJECT_ENDPOINT` | Variable | AI Foundry project endpoint URL |
| `AZURE_OPENAI_DEPLOYMENT_GPT` | Variable | Foundry/OpenAI deployment used by task-adherence and red-team checks |

## Evaluators

### Built-in
- Quality: Coherence, Fluency, Response Completeness
- RAG: Groundedness, Relevance
- Agent: Task Adherence, Task Completion, Tool Call Accuracy, Tool Selection
- Safety: Violence, Hate/Unfairness, Sexual, Self-Harm, Indirect Attack

### Custom QPrisma-specific
- Temporal Specificity: timestamp and temporal reference quality
- Source Grounding: video evidence citation quality

## Guardrails

- Start with dry-run data/evaluator commands before cloud jobs.
- Do not log raw prompts, transcripts, private media IDs, user IDs, tenant IDs, tokens, or raw Foundry
  payloads.
- If a workflow is known broken or blocked by hosted-agent API migration, report the exact blocker and
  do not claim benchmark coverage.
- Separate model quality failures from infrastructure/configuration failures.
- Preserve evaluation data contracts when changing metadata, conversation IDs, or hosted-agent
  request shape.

## Proof gates

- Dry-run data generation before committing evaluation data or workflow assumptions.
- Agent version resolution before remote evaluation.
- Red-team and benchmark outputs must include artifact path or workflow run URL when available.

## Output format

```markdown
### Evaluation target
- Endpoint:
- Agent version:
- Dataset/media:

### Commands or workflow
- ...

### Results
- Scores:
- Failures:
- Artifacts:

### Follow-up
- ...
```
