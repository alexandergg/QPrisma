# QPrisma Agent Template Guide

This guide defines the reusable baseline for building future LangGraph agents
on Azure AI Foundry from the QPrisma implementation. QPrisma remains the video
agent, but the runtime, metadata, evaluation, Red Teaming, and CI/CD patterns
are intended to be portable.

## What to copy for a new agent

| Layer | Reusable starting point | Replace per agent |
|---|---|---|
| Hosted runtime | `backend/agent/hosted/main.py`, `backend/agent/hosted/telemetry.py`, `backend/agent/hosted/Dockerfile`, `backend/agent/hosted/agent.yaml` | Agent name, graph factory, model deployments, service env vars |
| LangGraph graph | `backend/agent/graphs/video.py` as a structural example | State schema, nodes, tools, prompts, domain routing |
| Responses adapter | Event streaming in `_stream_response_events` | Domain-specific event metadata only |
| Foundry metadata | `.foundry/agent-metadata.yaml` | Project endpoint, agent name, ACR, datasets, manifests, thresholds |
| Evaluations | `backend/evaluation_foundry`, `docs/EVALUATION_GUIDE.md` | Dataset contents, evaluator thresholds, red-team taxonomy |
| GitHub Actions | `.github/workflows/evaluate-agent.yml`, backend/frontend setup actions | Environment names, secrets/variables, optional benchmarks |
| Operations docs | `docs/HOSTED_AGENT.md`, this guide | Agent-specific runbooks and SLOs |

## Recommended folder shape

```text
<agent-root>/
  .foundry/
    agent-metadata.yaml
    datasets/
    evaluators/
    results/
  backend/
    agent/
      graphs/
      hosted/
      state/
      tools/
    evaluation_foundry/
  docs/
    AGENT_TEMPLATE_GUIDE.md
    EVALUATION_GUIDE.md
    HOSTED_AGENT.md
```

Keep `.foundry/agent-metadata.yaml` as the source of truth for project
endpoint, hosted agent name, registry, evaluation lanes, manifests, and result
artifacts. Use GitHub variables/secrets for sensitive values; do not commit
resolved secrets or local dataset cache contents.

## Runtime decisions

QPrisma adopts the official Microsoft hosted-agent conventions where they are
stable:

- `kind: hosted` with `responses` protocol `1.0.0`.
- `DefaultAzureCredential` and managed identity in hosted paths.
- Foundry project OpenAI-compatible endpoint ending in `/openai/v1`.
- Explicit CPU/memory sizing.
- Unbuffered Python logs and Docker health probing.
- OpenTelemetry/App Insights tracing.

QPrisma intentionally keeps a custom Responses/LangGraph adapter instead of
using the official sample runtime directly. The custom adapter streams
LangGraph tool lifecycle events to the caller, which is required for the
frontend UX and should be treated as a regression-protected contract.

## Separating generic from QPrisma-specific code

Reusable:

- Hosted runtime entrypoint and response streaming shape.
- Environment bridge from Foundry-injected variables to app settings.
- Managed-identity model client pattern.
- Safe tracing wrapper and span metadata stamping.
- `.foundry` workspace and artifact conventions.
- Strict hosted-agent version resolution for evaluations.
- Red Teaming preflight, dry-run, diagnostics, and fail-closed gate.
- GitHub Actions structure for eval execution, artifact upload, and final gate.

QPrisma-specific:

- Video/media IDs, frame sampling, transcript retrieval, temporal grounding.
- Neo4j graph schema and video search tools.
- Video-MME benchmarks and media-grounding evaluators.
- Any prompts or thresholds tied to video analysis behavior.

## Evaluation lanes

Every new agent should define these lanes before production traffic:

| Lane | Purpose | Gate default |
|---|---|---|
| Quality | Coherence, relevance, fluency, task adherence | Fail on configured threshold regression |
| Tooling | Intent resolution, tool selection, tool call accuracy, tool success, output utilization | Fail on P0 tool regressions |
| Safety dataset | Batch safety evaluators over curated cases | Fail on policy threshold regression |
| Cloud Red Teaming | Agentic adversarial probing through Foundry | Fail if no real run, non-completed status, zero output items, or missing artifacts |
| Domain benchmark | Optional domain-specific quality suite | Advisory or strict by workflow input |

For Red Teaming, an eval group in Foundry is not enough. A valid run must
produce a run ID, complete successfully, emit output items, and write summary,
request-shape, and output-items artifacts.

## Production-ready checklist

1. Hosted agent can run locally with the same env contract used in Foundry.
2. Docker image uses a non-root user, unbuffered logs, and `/readiness` healthcheck.
3. `agent.yaml` declares `responses` `1.0.0`, explicit CPU/memory, and only required env vars.
4. Deployment resolves a real hosted-agent version and never silently falls back during evals.
5. Managed identity has project-scope `Azure AI User` and required downstream data-plane roles.
6. Traces include conversation/request correlation and agent version metadata.
7. `.foundry/agent-metadata.yaml` declares environments, manifests, datasets, thresholds, and artifacts.
8. Batch evals and Red Team preflight run in GitHub Actions with uploaded artifacts.
9. Red Team gate fails closed for missing run ID, non-completed run, zero items, or missing results.
10. Documentation explains local run, deployment, evaluation, Red Teaming, troubleshooting, and ownership.

## Porting steps

1. Copy the hosted runtime and replace the graph factory with the new
   agent's `create_<agent>_graph()` function.
2. Replace QPrisma-specific state fields and tools with the new agent's
   domain state and tool contract.
3. Update `backend/agent/hosted/agent.yaml`, `scripts/deploy_agent.py`, and
   `.foundry/agent-metadata.yaml` with the new agent name, project endpoint,
   ACR, model deployments, and service env vars.
4. Create the smallest useful evaluation datasets first: safety regression,
   tool routing regression, and one Red Team manifest.
5. Keep Red Teaming optional for PRs but mandatory for scheduled or release
   gates once the Foundry project/region supports it.
6. Remove QPrisma-only benchmarks unless the new agent has an equivalent
   domain benchmark with clear thresholds.

## Notes from the Microsoft reference sample

The Microsoft sample is a clean starter for simple hosted LangGraph agents,
especially for `azd`, basic hosted manifests, model endpoint wiring, and
container health probing. QPrisma should be treated as the richer production
template when an agent needs custom tool-event streaming, evaluation gates,
Red Team diagnostics, metadata/workspace conventions, and domain benchmarks.
