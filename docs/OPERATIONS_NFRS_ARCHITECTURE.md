# QPrisma Operations, NFRs, and Architecture Trade-offs

This document translates the QPrisma implementation into an operational architecture view aligned with non-functional requirements.

## Scope

This view focuses on:

- reliability
- scalability
- performance
- security
- cost optimization
- operational excellence
- maintainability

It is intended to complement the functional architecture documents by explaining how the workload behaves under real operating constraints.

## Related artifacts

- Platform deployment: `docs/INFRASTRUCTURE.md`
- Portfolio index: `docs/ARCHITECTURE_PORTFOLIO.md`
- Azure deployment diagram: `docs/assets/architecture/azure-architecture.svg`
- Ingestion flow: `docs/VIDEO_INGESTION_ARCHITECTURE.md`
- Hosted retrieval flow: `docs/HOSTED_AGENT_RETRIEVAL_ARCHITECTURE.md`

## NFR summary

QPrisma is architected as an Azure-native distributed workload with different runtime profiles:

- low-latency interactive traffic in the frontend and API
- bursty long-running compute in the worker tier
- stateful data and graph backends
- AI-dependent calls whose latency and cost must be controlled explicitly

Because of that shape, the most important NFRs are not generic uptime statements. They are workload-specific concerns about queueing, scaling, retrieval latency, observability, and cost control.

## 1. Reliability

### Current architectural strengths

- Decoupled API and worker tiers prevent long-running processing from blocking user-facing requests.
- Raw media is durably stored before heavy processing begins.
- Health checks and deployment safety mechanisms exist in the delivery workflows.
- The agent runtime includes bounded iteration and graceful degradation behavior.
- Search can fall back to keyword-oriented behavior when richer signals are constrained by time budget.

### Main reliability risks

- AI platform dependencies can become a partial system bottleneck.
- Polyglot persistence increases the number of components that can degrade independently.
- Long-running ingestion jobs are sensitive to external service throttling and temporary failures.

### Architecture interpretation

QPrisma is more resilient than a monolithic synchronous pipeline, but its reliability depends heavily on maintaining clean boundaries between interactive, queued, and stateful workloads.

## 2. Scalability

### Scale dimensions

QPrisma has at least four different scaling axes:

| Dimension | Primary scaling mechanism |
|---|---|
| Frontend traffic | Azure Container Apps replica scaling |
| API request volume | Azure Container Apps replica scaling |
| Background processing load | KEDA-driven worker scaling from queue depth |
| Retrieval complexity | Candidate capping, bounded tool loops, prompt budget discipline |

### Important point for architects

This is not a workload where "just add more replicas" solves every problem. Some scale issues are compute-bound, some are model-bound, and some are data-shape-bound.

## 3. Performance

### Performance-critical paths

The workload has three distinct latency-sensitive paths:

1. upload and job creation
2. interactive retrieval and answer generation
3. background ingestion completion time

### Performance choices already visible in the architecture

- asynchronous background processing for ingestion
- parallel visual/audio work where practical
- Azure OpenAI Batch API for image-analysis cost and throughput efficiency
- selective tool binding in the hosted agent
- bounded hybrid search with a pipeline time budget
- caching and transient acceleration through Redis

### Performance trade-off

QPrisma chooses better downstream answer quality by doing more work at ingestion time. This increases processing duration per asset but reduces retrieval-time burden.

## 4. Security as an operational NFR

Security in QPrisma is not only a control-plane concern. It shapes operations:

- Entra ID affects how incidents are triaged and attributed
- Key Vault affects runtime configuration management
- managed identity affects how Azure access failures manifest
- user-aware retrieval scoping affects correctness and tenant isolation

This is why security should be reviewed as both an architecture view and an operational requirement.

## 5. Cost optimization

### Current cost-aware patterns

- Azure OpenAI Batch API usage for frame analysis
- workload separation so expensive worker compute does not force the API tier to scale the same way
- Redis used for transient speedups instead of overusing expensive repeated calls
- selective context rehydration to reduce token pressure in agent prompts

### Main cost drivers

| Cost driver | Why it matters |
|---|---|
| Vision and text model calls | Direct AI usage cost during ingestion and retrieval |
| Worker runtime | Long-running media processing and enrichment |
| Neo4j and relational persistence | Stateful platform cost |
| Blob storage growth | Raw and derived asset retention |
| Cross-service observability | Logs and telemetry volume |

### Solution Architect interpretation

QPrisma cost optimization depends on designing for **precomputation**, **bounded retrieval**, and **queue-aware scaling**, not only on choosing cheaper SKUs.

## 6. Operational excellence

### Positive operational patterns

- Infrastructure as Code with Bicep
- path-filtered CI/CD workflows
- container health checks
- rolling deployment and rollback behavior
- centralized documentation for infrastructure and backend architecture

### Areas that matter most in operations reviews

- tracing user request to hosted-agent execution
- correlating ingestion job state with worker logs
- isolating search slowness to embedding, graph, or model stages
- validating secret and identity access changes during deployments

## 7. Observability

QPrisma includes multiple observability surfaces:

- Azure Monitor and Log Analytics
- application logging
- worker progress state updates
- WebSocket progress notifications
- telemetry attributes attached to conversations and users in agent flows

### Architecture recommendation

For operations reviews, always separate observability into:

- user journey visibility
- pipeline stage visibility
- platform health visibility
- deployment visibility

That makes troubleshooting materially faster.

## 8. Maintainability

### Maintainability strengths

- route/service separation in the backend
- centralized configuration through typed settings
- dedicated architecture and infrastructure documentation
- decomposition of agent responsibilities across nodes and tool domains

### Maintainability trade-offs

- multiple stores and services raise the learning curve
- AI orchestration logic can drift from documentation if not reviewed regularly
- diagram portfolios require active curation to stay accurate

## 9. Key trade-offs

| Architectural choice | Benefit | Cost |
|---|---|---|
| Rich ingestion-time enrichment | Better retrieval quality and faster question answering | Higher ingestion cost and complexity |
| Hosted agent plus LangGraph | Better orchestration capability | More runtime moving parts |
| Polyglot persistence | Better domain fit per storage engine | More operational surface area |
| Azure-native managed services | Faster platform maturity | Cross-service dependency management |
| Queue-based worker model | Better elasticity and user responsiveness | More distributed tracing and failure handling work |

## 10. Runbook-oriented failure domains

When QPrisma is operated professionally, incidents usually fall into one of these domains:

| Failure domain | First review focus |
|---|---|
| Upload/initiation failures | API auth, Blob connectivity, metadata writes |
| Jobs stuck in queue | Redis/Celery health, KEDA scaling, worker availability |
| Slow ingestion | model quotas, batch execution, frame volume, audio duration |
| Weak retrieval quality | graph indexing quality, embedding quality, query interpretation, reranking |
| Hosted agent failure | Foundry connectivity, context propagation, tool routing, prompt budget |
| Deployment regression | workflow logs, container health, config drift, secret resolution |

## 11. How to use this document in a review

Use this document to drive architecture conversations such as:

1. Which NFRs are most business-critical for QPrisma?
2. Which dependencies are hardest to scale or troubleshoot?
3. Where is the biggest latency budget consumed today?
4. Which trade-offs are deliberate versus accidental?
5. Which parts of the system are most expensive to operate at scale?

## How to present this professionally

For a Solution Architect audience, present NFRs in this order:

1. **reliability model**
2. **scaling model**
3. **latency and throughput model**
4. **security operating model**
5. **cost drivers and optimizations**
6. **observability and runbook readiness**

That sequence ties technology choices back to operational behavior instead of listing abstract quality attributes.
