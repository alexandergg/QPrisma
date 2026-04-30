# QPrisma Hosted Agent (Refreshed Preview)

> **Status**: Public preview — Azure AI Foundry hosted agents on the
> **refreshed Responses runtime** (`azure-ai-agentserver-responses`).
> This document supersedes the legacy `HOSTED_AGENT_CONVERTER.md` (deleted).

The QPrisma video agent is a LangGraph `StateGraph` packaged for execution
inside the Azure AI Foundry hosted agents runtime. Foundry owns the
`/responses` HTTP surface, conversation persistence, identity
materialisation, and OpenTelemetry trace ingestion. The container only
ships:

1. The compiled LangGraph (`agent/graphs/video.py`).
2. A thin `ResponsesAgentServerHost` entrypoint (`agent/hosted/main.py`).
3. The Azure AI tracer wired in once at compile-time.

There is **no custom state converter, no Redis-checkpointer, and no
`[QPRISMA_CONTEXT:…]` envelope** anymore.

---

## 1. Architecture

```
┌────────────────────────────────────────────────────────────────────────┐
│ Frontend (Next.js 16) ─────► Backend FastAPI ─────► foundry_agent_client
│                                                          │
│                                                          ▼
│                              Azure AI Foundry  ─────► /responses
│                              (managed runtime)         │
│                                                        ▼
│                                            ResponsesAgentServerHost
│                                                        │
│                                                        ▼
│                                          LangGraph StateGraph (qprisma)
│                                                        │
│                              ┌─────────┬───────────────┼────────────┐
│                              ▼         ▼               ▼            ▼
│                        Foundry      OpenAI         Tools        MemorySaver
│                       Conversations  v1 API     (search,        (in-process
│                       (history)                  analysis, …)    only)
└────────────────────────────────────────────────────────────────────────┘
```

### Components

| Component | Where | Purpose |
|---|---|---|
| `ResponsesAgentServerHost` | `backend/agent/hosted/main.py` | HTTP host (Foundry-managed). One `@app.response_handler` returning `TextResponse`. |
| `_get_graph()` | `backend/agent/hosted/main.py` | Lazy LangGraph singleton, compile-time tracer + tags wiring. |
| `create_video_agent_graph()` | `backend/agent/graphs/video.py` | Pure StateGraph builder. Compiled with `MemorySaver()` per process. |
| Foundry Conversations | Foundry-managed | Single source of truth for user/assistant/tool messages. Replicas reconstruct history via `context.get_history()`. |
| `AzureAIOpenTelemetryTracer` | `backend/agent/hosted/telemetry.py` | Emits LangGraph spans into Foundry's traces store. Bound at compile-time. |
| `ChatOpenAI(base_url=f"{FOUNDRY_PROJECT_ENDPOINT}/openai/v1")` | `backend/services/llm_factory.py` | LLM client — Foundry-scoped OpenAI v1 surface. |

### Hosted vs local dev

| Aspect | Hosted (Foundry) | Local dev / Celery |
|---|---|---|
| Runtime | `azure-ai-agentserver-responses==1.0.0b5` | n/a (LangGraph driven directly) |
| Entrypoint | `agent/hosted/main.py` | FastAPI routes or worker |
| Persistence | Foundry Conversations | `MemorySaver` only |
| Tracer | `AzureAIOpenTelemetryTracer` (compile-time) | None or local OTEL collector |
| LLM | `ChatOpenAI` against Foundry OpenAI v1 | `AzureChatOpenAI` (account-scoped) |
| Container health | Docker `HEALTHCHECK` probes `/readiness` on `PORT` | Local `docker run` can use the same probe |

---

## 2. Identity flow

```
GitHub Actions (OIDC) ──► azd deploy qprisma-video-agent
       │                         │
       │                         ▼
       │            azure.yaml + host: azure.ai.agent
       │                         │
       │                         ▼
       │            backend/agent/hosted/agent.yaml
       │                         │
       │                         ▼
       │            postdeploy hook inspects runtime identity once
       │                         │
       │                         ▼
       │     If identity is already available, assigns downstream RBAC
       │
       └──► On every /responses call:
               Foundry runtime runs container as that managed identity.
              Container uses DefaultAzureCredential to mint tokens for
              ChatOpenAI (Foundry OpenAI v1 surface).
```

**Why this is best-effort**: Foundry can materialise `instance_identity` after
the agent version is already `Active`. Microsoft's hosted-agent sample checks
the identity once after deploy and skips role assignment when the principal is
not yet visible; QPrisma follows the same fast path so registration does not
block for minutes after the agent is active.

If the identity is returned immediately, the `infra/hooks/postdeploy.*` hook
assigns the downstream runtime RBAC roles used by QPrisma. If it is missing,
the workflow continues and logs a warning. Re-run the workflow later or set
`REQUIRE_AGENT_IDENTITY_RBAC=1` only for deployments that must synchronously
assign custom downstream RBAC.

---

## 3. Conversation persistence — Foundry Conversations

Foundry persists every user message, every assistant reply, and every tool
call/output as part of the conversation it manages. The hosted graph never
writes to Redis or PostgreSQL for chat history.

### Reading history inside the agent

```python
@app.response_handler
async def respond(request: CreateResponse, context: ResponseContext):
    history = await context.get_history()  # full conversation snapshot
    state = _build_initial_state(request, history)
    result = await graph.ainvoke(state)
    return TextResponse(text=result["messages"][-1].content)
```

### Why we removed the Redis checkpointer

* Foundry owns history → the agent has no need to checkpoint between
  turns; the next `/responses` call rehydrates from `context.get_history()`.
* `MemorySaver` is still used **inside** a single turn so LangGraph can
  resume node-level state if the graph is re-entered (e.g. after a tool
  call in the same `ainvoke`).
* Redis is still used for Celery, embedding cache, and rate limiting —
  just not for conversation state.

---

## 4. Metadata API — replaces the `[QPRISMA_CONTEXT:…]` envelope

The legacy stack prepended a hand-rolled envelope to every user message:

```
[QPRISMA_CONTEXT: {"media_id": "...", "user_id": "..."}]
What's in this video?
```

The refreshed preview supports a per-message `metadata` field on
`CreateResponse`. Both the frontend and backend now use that:

```python
await client.responses.create(
    input=user_message,
    metadata={
        "media_id": media_id,
        "user_id": user_id,
        "media_ids": media_ids,
    },
    timeout=settings.foundry.request_timeout_seconds,
)
```

Inside the host, `_build_initial_state` reads `request.metadata` and
promotes the supported values to first-class fields on the agent state.
Arbitrary unknown metadata keys are not currently retained on
`state["metadata"]`, but `restore_media_context` no longer parses any
string envelope.

---

## 5. Environment variables

Foundry reserves the `AZURE_AI_*` prefix for its own runtime. We bridge
the Foundry-injected `FOUNDRY_*` variables into the more familiar
`AZURE_AI_*` names at process startup.

| Variable | Required by | Notes |
|---|---|---|
| `FOUNDRY_AGENT_NAME` | `AgentConfig.from_env()` | Foundry-injected. |
| `FOUNDRY_AGENT_VERSION` | `AgentConfig.from_env()` | Foundry-injected. |
| `FOUNDRY_HOSTING_ENVIRONMENT` | `AgentConfig.from_env()` | Foundry-injected. |
| `FOUNDRY_PROJECT_ENDPOINT` | LLM, tracer, history client | Foundry-injected. Bridged to `AZURE_AI_PROJECT_ENDPOINT`. |
| `FOUNDRY_PROJECT_ARM_ID` | Tracer | Foundry-injected. |
| `FOUNDRY_AGENT_SESSION_ID` | History APIs | Foundry-injected. |
| `PORT` | HTTP host | Default `8088`. |
| `AZURE_AI_PROJECT_ENDPOINT` | App code | Required for non-hosted paths; bridged automatically when only `FOUNDRY_PROJECT_ENDPOINT` is set. |
| `FOUNDRY_REQUEST_TIMEOUT_SECONDS` | `foundry_agent_client` | Default `120.0`. Caller-side timeout for `responses.create`. |

Hard-fail (no fallback) if neither `AZURE_AI_PROJECT_ENDPOINT` nor
`FOUNDRY_PROJECT_ENDPOINT` is set. This avoids the silent half-config the
legacy stack tolerated.

---

## 6. Deployment

The default deploy path follows the Microsoft hosted-agent sample pattern:
`azd` owns the hosted-agent registration through `host: azure.ai.agent`, while
QPrisma keeps the custom LangGraph runtime inside the container.

1. **Login** via OIDC (`azure/login@v2`).
2. **Install** Azure Developer CLI plus the `azure.ai.agents` extension declared
   in root `azure.yaml`.
3. **Grant deployer/project access** needed for Foundry deployment and ACR pull.
4. **Resolve runtime configuration** from GitHub variables/secrets and Key Vault,
   then persist it into the active `azd` environment with `azd env set`.
5. **Run** `azd deploy qprisma-video-agent --no-prompt`, which uses:
   - root `azure.yaml`;
   - `backend/agent/hosted/agent.yaml`;
   - `backend/agent/hosted/Dockerfile`;
   - `host: azure.ai.agent`;
   - `docker.remoteBuild: true`;
   - `python -m agent.hosted.main` as startup command.
6. **Run postdeploy hooks** (`infra/hooks/postdeploy.ps1` or `.sh`) that call
   `azd ai agent show`, read `instance_identity.principal_id` once, and assign
   downstream RBAC only when the runtime identity is already visible.
7. **Upload redacted diagnostics** and post a workflow summary.

Re-running the workflow is always safe: every step is idempotent.

`scripts/deploy_agent.py` remains as a Python SDK fallback/diagnostic tool, but
it is no longer the primary GitHub Actions deployment path. Use it only when the
`azd` path is blocked and document the reason in the deployment run.

### Identity and blueprint diagnostics

The Foundry portal fields **Entra agent identity** and **Entra agent blueprint**
are expected to be populated by the official hosted-agent path when the service
returns those metadata fields. A deployed version reaching `active` is still the
runtime readiness signal; missing identity/blueprint metadata should not block
deployment unless `REQUIRE_AGENT_IDENTITY_RBAC=true`.

For troubleshooting, use:

```powershell
python scripts\inspect_foundry_agent.py --output .foundry\results\hosted-agent-inspection.json
```

The script reads `.foundry/agent-metadata.yaml`, calls the Foundry data plane,
and writes only allowlisted/redacted fields. Do not print raw `azd ai agent show`
or REST payloads in CI logs because Foundry responses can include plaintext
environment variables.

---

## 7. Production template contract

QPrisma keeps the custom Responses/LangGraph adapter because it streams the
tool lifecycle expected by the frontend: `on_tool_start`, arguments,
`on_tool_end`, token deltas, and final fallback text. Future agents can use
the official Microsoft sample runtime for simple text-only agents, but agents
that need live tool telemetry should start from this adapter.

The production baseline for new hosted agents is:

| Area | QPrisma template default |
|---|---|
| Protocol | `responses` `1.0.0` in `backend/agent/hosted/agent.yaml` |
| Compute | Explicit Foundry tier (`cpu: "2"`, `memory: 4Gi`) mirrored in root `azure.yaml` and the hosted manifest |
| Container | Multi-stage image, non-root user, unbuffered logs, `/readiness` Docker `HEALTHCHECK` |
| Identity | `DefaultAzureCredential`, managed identity, no local auth/key fallback in hosted paths |
| Endpoint | Project-routed Foundry OpenAI v1 endpoint (`<projectEndpoint>/openai/v1`) |
| Tracing | `AzureAIOpenTelemetryTracer` with `agent_id`, wrapped by `SafeAzureAIOpenTelemetryTracer` |
| Metadata | `.foundry/agent-metadata.yaml` is the source of truth for endpoint, agent, manifests, datasets, and artifacts |
| Evaluations | Strict agent-version resolution, Red Team preflight, request-shape artifact, output-items JSONL, and fail-closed gates |

### Microsoft sample patterns adopted

From `Azure-Samples/foundry-hosted-langchain-demos`, QPrisma adopts the
canonical hosted-agent pieces that are stable and reusable:

- `kind: hosted` and `responses` `1.0.0` manifest shape.
- Root `azure.yaml` with `host: azure.ai.agent` and the `azure.ai.agents`
  extension.
- `azd deploy qprisma-video-agent` as the primary deployment command.
- Explicit CPU/memory sizing.
- `DefaultAzureCredential` and Foundry project OpenAI-compatible endpoint.
- Unbuffered Python container logs and Docker health probing.
- App Insights / OpenTelemetry as the preferred observability path.
- Postdeploy hooks that inspect runtime identity once and assign RBAC
  best-effort.

QPrisma intentionally does **not** replace its custom runtime with the sample
runtime because the sample does not cover the frontend-visible LangGraph tool
event stream, Red Team gates, Video-MME benchmarks, or the `.foundry` metadata
workspace.

---

## 8. Trade-offs and known issues

* **`langchain-azure-ai==1.1.0b1` upstream bug** — input normalisation
  occasionally trips on `'list' object has no attribute 'get'`. We keep a
  `SafeAzureAIOpenTelemetryTracer` wrapper that defends against this; it
  will be removed when upstream ships the fix.
* **`azure-identity==1.26.0b2`** is beta because the refreshed
  `azure-ai-agentserver-responses` wheel pins it transitively. Will GA
  with the next preview drop.
* **Cloud Red Teaming is service-contract sensitive** — keep the preflight,
  SDK version logging, request-shape artifact, and output-items gate. A
  Foundry eval group alone is not proof that an adversarial run executed.
* **Identity / blueprint metadata is service-owned** — the `azd` path aligns
  with the official deployment contract, but the portal fields still depend on
  what Foundry returns for the hosted version. Use the redacted inspection
  script for evidence before escalating.
* **Bearer token TTL beyond 1h** — the SDK refreshes credentials in-process
  but long-running `ainvoke` calls (>1h) may need explicit refresh. Not
  in scope for the current preview.

---

## 9. References

* Refreshed preview reference: <https://github.com/microsoft-foundry/foundry-samples/tree/main/samples/python/hosted-agents/langgraph>
* Foundry hosted agents docs: <https://learn.microsoft.com/azure/foundry/agents/hosted-agents>
* QPrisma agent template guide: `docs/AGENT_TEMPLATE_GUIDE.md`
* QPrisma evaluation guide: `docs/EVALUATION_GUIDE.md`
* QPrisma `azd` deploy config: `azure.yaml`
* QPrisma safe inspection script: `scripts/inspect_foundry_agent.py`
* QPrisma SDK fallback deploy script: `scripts/deploy_agent.py`
* QPrisma purge script: `scripts/purge_agent_versions.py`
