# QPrisma Hosted Agent Retrieval Architecture

This document explains how QPrisma routes a user question into the hosted agent runtime, restores the right video context, performs hybrid retrieval, and produces a grounded answer.

## Scope

This view focuses on:

- request entry and context injection
- hosted agent invocation through Azure AI Foundry
- LangGraph state transitions
- tool routing and retrieval orchestration
- prompt-time context assembly
- streaming and response shaping

For lower-level code references, see `docs/BACKEND_ARCHITECTURE.md`, `backend/agent/nodes/video_nodes.py`, `backend/agent/nodes/base.py`, and `backend/services/foundry_agent_client.py`.

## Related artifacts

- Published diagram asset: `docs/assets/architecture/agent-search-rag-flow.svg`
- Portfolio index: `docs/ARCHITECTURE_PORTFOLIO.md`
- Technical deep dive: `docs/ARCHITECTURE.md`
- Agent runtime overview: `docs/BACKEND_ARCHITECTURE.md`

![QPrisma hosted agent retrieval diagram](assets/architecture/agent-search-rag-flow.svg)

## Architecture summary

QPrisma uses a hosted agent model built on Azure AI Foundry plus a LangGraph-based video agent.

At a high level, the retrieval path looks like this:

1. the frontend sends a question and selected media context
2. the API layer authenticates the user and forwards the request to the hosted agent client
3. the client injects QPrisma-specific media metadata into the message payload
4. the hosted agent runtime executes the LangGraph workflow
5. the graph dynamically selects tools and assembles context
6. retrieval combines vector, full-text, graph, and temporal signals
7. the final answer is returned with grounding-oriented structure

## 1. Request entry and context injection

The primary simple entry point is `POST /chat/agent`.

The request is handled by the backend and forwarded to `FoundryAgentClient`, which binds the OpenAI client to the hosted agent's dedicated Azure AI Foundry endpoint and uses the Responses API with a Foundry conversation ID for continuity.

### QPrisma-specific context pattern

QPrisma prepends a lightweight metadata block to the user message:

`[QPRISMA_CONTEXT:{...}]`

This metadata can include:

- `media_id`
- `media_ids`
- `user_id`
- `session_id`

### Why this pattern matters

The hosted agent needs video context that is not naturally present in a plain natural-language prompt. Injecting context as structured metadata allows the request to remain self-describing when it crosses the boundary into the hosted runtime.

## 2. Restoring the correct media context

Inside the LangGraph workflow, `restore_media_context` is the first critical node.

It resolves effective video context in priority order:

1. request configuration
2. context extracted from the message payload
3. previously checkpointed state

It also removes the QPRISMA context marker from the human-visible message stream so internal metadata does not leak into the prompt sent to the model.

### Multi-video mode

When multiple media IDs are present, the node also resolves human-readable video titles so the system prompt can refer to the selected assets explicitly.

### Architecturally important detail

This is a strong example of defense-in-depth for AI systems:

- the system does not trust only one carrier of context
- it keeps a fallback chain
- it strips internal transport metadata before model invocation

## 3. LangGraph runtime model

The video agent is a cyclic StateGraph rather than a one-shot prompt wrapper.

The dominant runtime nodes are:

| Node | Responsibility |
|---|---|
| `restore_media_context` | Recover and normalize media context |
| `call_model` | Build the system prompt, bind tools, and invoke the model |
| `should_continue` | Decide whether to execute tools, end, or degrade gracefully |
| `tools` | Execute the selected tool calls |
| `update_context` | Persist compact context from tool results |
| `error_handler` | Produce the best possible answer from accumulated partial results |

### Runtime safeguards

The graph uses explicit iteration and degradation limits:

- default max tool iterations: 10
- warning threshold before that limit: 7
- error threshold for graceful degradation when partial results exist

This is important because agent architectures fail less often when bounded by deterministic controls.

## 4. Dynamic tool selection

QPrisma does not bind every tool to every request indiscriminately.

When video context is available, `call_model` extracts the latest human query and selects a focused subset of search-related tools, capped at a small number of relevant candidates.

### Why this matters

Dynamic tool binding improves:

- latency
- model focus
- tool-call precision
- prompt size discipline

This is an example of **agent orchestration as architecture**, not just as prompt engineering.

## 5. Tool domains

The hosted retrieval experience is powered by several tool families:

| Domain | Example responsibilities |
|---|---|
| Search | Hybrid search over graph, vector, and transcript-style content |
| Entity | Entity lookup, timeline, network exploration |
| Context | Scene, chapter, summary, and video-structure retrieval |
| Analysis | Related content, comparison, and multi-hop reasoning |
| Highlight | Key moments, clip suggestions, highlight-oriented interactions |
| Multi-video | Cross-video search and comparison |

Each tool returns structured payloads rather than throwing uncontrolled runtime exceptions. That pattern is important because it keeps the agent loop predictable under partial failure.

## 6. Hybrid retrieval strategy

QPrisma retrieval is not a single vector search call. It is a fusion pipeline implemented in `GraphSearchService`.

### Core signals

The current retrieval pipeline combines:

- vector similarity
- full-text relevance
- graph connectivity
- temporal proximity

The sync search pipeline is governed by a total time budget and executes inside a thread to avoid blocking the async event loop with synchronous Neo4j work.

### Important runtime characteristics

- query embeddings are generated before the sync search pipeline
- candidate sets are capped to avoid explosion
- graph expansion can be skipped when the budget is nearly exhausted
- reranking can use context-aware signals
- keyword fallback is available when some search paths time out

### Architectural meaning

From a Solution Architect perspective, QPrisma retrieval is best described as **hybrid GraphRAG with temporal awareness**, not just "RAG over embeddings."

## 7. Prompt-time context assembly

The hosted agent does not blindly inject everything it knows into the model context. The system explicitly constructs prompt-time context.

### Current sources used in prompt-time context

- trimmed message history
- local compact memory snippets from prior tool results
- artifact references created from successful tool calls
- selective artifact rehydration for detail-heavy questions

### Current implementation note

The repository contains a `FoundryMemoryService` for Azure AI Foundry Memory Store, but the current prompt-time hybrid memory retrieval path in `backend/agent/nodes/base.py` uses `memory_context` and `artifact_refs` from graph state. The Foundry Memory Store service exists as an available capability, but it is not currently part of the active retrieval path shown in the base node logic.

That distinction is important to keep the architecture documentation honest.

## 8. State accumulation and artifact persistence

After tool execution, `update_context` extracts compact summaries and persists the result in a way that can support later reasoning.

The graph currently maintains bounded state such as:

- `partial_results`
- `memory_context`
- `artifact_refs`

The logic intentionally trims these structures so the agent can remain stateful without uncontrolled context growth.

## 9. Error handling and graceful degradation

One of the strongest design choices in the hosted agent flow is that the graph does not collapse immediately when a tool chain is imperfect.

If the error threshold is reached but useful partial results exist, the workflow can route to a graceful degradation path and synthesize the best answer possible from what was already gathered.

This is a much stronger enterprise pattern than a brittle "all tools must succeed" design.

## 10. Response streaming and delivery modes

`FoundryAgentClient` supports both:

- materialized request/response behavior through `send_message`
- streaming behavior through `send_streaming_message`

The streaming client path is built on the OpenAI Responses API with `stream=True` and converts streamed events into incremental application-friendly updates.

### Important implementation nuance

The simple `/chat/agent` REST endpoint returns a completed response object. The client service also supports streaming mode for richer conversational delivery patterns, but streaming should not be documented as the behavior of every route unless the route explicitly exposes it.

## 11. Security and tenancy considerations

The retrieval path includes several security-sensitive boundaries:

- the user is authenticated before the hosted agent call is made
- media context includes a user identifier for tenant scoping
- graph and content retrieval are constrained by user-aware filtering
- WebSocket and agent-related flows do not bypass the primary identity model

Hosted agent design is not only a model orchestration concern. It is also a multi-tenant access-control concern.

## 12. Key architectural trade-offs

| Decision | Benefit | Cost |
|---|---|---|
| Hosted agent runtime | Managed agent execution boundary and cleaner model integration | Adds cross-service orchestration complexity |
| StateGraph loop | Better multi-step reasoning and tool usage | More runtime states to observe and debug |
| Dynamic tool binding | Better focus and latency | Requires careful tool-description hygiene |
| Hybrid retrieval | Better grounding quality | More scoring logic and tuning surface area |
| Prompt-time bounded context | Better token discipline | Requires selective omission of lower-value context |

## How to present this professionally

When presenting the hosted agent retrieval architecture as a Solution Architect, frame it in this order:

1. **entry boundary**: authenticated request enters through the API
2. **context integrity**: video context is carried, restored, and sanitized
3. **bounded agent loop**: LangGraph orchestrates reasoning with safeguards
4. **hybrid grounding**: retrieval uses multiple complementary signals
5. **state discipline**: context is accumulated selectively, not indiscriminately
6. **graceful degradation**: the architecture is resilient under imperfect tool chains

That framing makes the agent architecture legible to both AI specialists and platform reviewers.
