# Memory Architecture (QPrisma)

This guide defines what each memory layer stores and which system is the source of truth for agent conversations.

Related views:

- `docs/HOSTED_AGENT_RETRIEVAL_ARCHITECTURE.md` - hosted agent request path and prompt-time context assembly
- `docs/BACKEND_ARCHITECTURE.md` - backend module inventory and memory-layer implementation references

## Memory Layers

1. **LangGraph Checkpointer**
   - Purpose: operational graph state by `thread_id`, working state, and resume/retry continuity.
   - Scope: per conversation thread.
   - Persistence:
      - **Backend-direct mode**: process-local `MemorySaver` in the current implementation.
     - **Foundry Hosted Agent mode**: intentionally process-local `MemorySaver` for in-run state only.
   - In Hosted Agent mode, it does not replace Foundry Responses/Conversations.

2. **Foundry Memory Store (Semantic Memory)**
   - Purpose: long-term memory, preferences, summarized facts, and persistent user signals.
   - Scope: cross-thread per user, scoped by Entra ID `{tid}_{oid}`.
   - Persistence: Azure AI Foundry Memory Store.
   - It complements prompt context; it does not replace the checkpointer.
   - **Status**: `FoundryMemoryService` is available as a singleton but is not automatically invoked in the agent graph yet. Automatic graph-node integration is future work.

3. **A2A Task Store**
   - Purpose: A2A task lifecycle state, including `taskId`, status, artifacts, and task history.
   - Scope: task lifecycle and progress.
   - Persistence: PostgreSQL-backed storage when the DB health check is healthy, with automatic fallback to in-process memory when persistence is unavailable.
   - Operational note: multi-instance and restart durability depend on PostgreSQL availability; the in-memory fallback is best-effort only.

> The UI does not persist conversations in localStorage. Conversational state resides in Foundry Hosted Agent or in backend-direct state, depending on the execution mode.

## Source of Truth and Reconciliation

- **Foundry Hosted Agent conversation history**: Foundry Responses/Conversations. This is the primary production path for sessions, response history, streaming lifecycle, and portal-visible traces.
- **Backend-direct conversation history**: LangGraph checkpointer backed by process-local `MemorySaver` in the current implementation.
- **User semantic knowledge**: Foundry Memory Store after automatic integration is enabled.
- **A2A tasks and artifacts**: QPrisma stores, with explicit ownership, retention, and artifact references.

If there is a conflict in Hosted Agent mode, Foundry is authoritative for conversation history and QPrisma is authoritative for task state/artifacts. In backend-direct mode, the backend checkpointer/task state is authoritative.

## Recommended ID Mapping

- `contextId` (A2A): on the first request this can be a client-generated UUID. The backend replaces it with the Foundry conversation ID returned by Foundry and sends it back to the client. Subsequent turns use that Foundry conversation ID for continuity.
- `taskId` (A2A): execution/progress identity, not the primary conversation identity.
- `thread_id` (LangGraph): operational graph identity for backend-direct or per-run hosted execution state.

## Hosted Agent Per-Turn Flow

1. Client sends a message with `contextId` (UUID on the first turn, Foundry conversation ID on subsequent turns).
2. Backend resolves or creates a Foundry conversation ID from `contextId`.
3. Backend calls the Foundry Hosted Agent using Foundry-managed conversation continuity.
4. Foundry preserves the conversation, responses, and traces.
5. The hosted LangGraph runtime uses process-local `MemorySaver` only for operational state during that hosted execution.
6. A2A streams SSE events with `contextId` set to the Foundry conversation ID.

## Backend-Direct Flow

1. Client calls the backend-direct graph path without going through the Foundry Hosted Agent.
2. Backend executes `get_video_agent_graph()`.
3. `get_shared_checkpointer()` uses process-local `MemorySaver`.
4. The checkpointer is the source of truth for continuity/resume of that thread.

## Latency and Quality

- Backend-direct checkpointer overhead is typically smaller than LLM and retrieval latency.
- Hosted Agent mode avoids duplicating conversation history in QPrisma stores, reducing compliance surface and keeping Foundry as the system of record for conversations.
- For backend-direct mode, keep state compact, avoid large payloads in checkpoints, use connection pooling, and track p50/p95 metrics per phase.

## Recommended Operational Policies

- Define retention policies per environment.
- Use Foundry policies for Hosted Agent conversations/responses and QPrisma policies for A2A tasks/artifacts.
- Use checkpointer `thread_id` deletion for backend-direct conversation deletion.
- Encrypt sensitive state at rest where applicable.
- Preserve traceability with `contextId`, `taskId`, `thread_id`, and Foundry conversation ID while avoiding raw sensitive identifiers in logs and spans.
