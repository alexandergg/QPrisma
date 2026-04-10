# Memory Architecture (QPrisma)

This guide defines **what each layer stores** and which is the **source of truth** for agent conversations.

## Memory Layers

1. **LangGraph Checkpointer (Backend)**
   - Purpose: per-conversation graph operational state (`thread_id`), working history, and resumption after failures/interrupts.
   - Scope: per conversation thread.
   - Persistence: production saver (PostgreSQL/Redis) based on availability.
   - **Conversational source of truth**.

2. **Foundry Memory Store (Semantic Memory)**
   - Purpose: long-term memory (preferences, summarized facts, persistent signals).
   - Scope: cross-thread per user (scoped by Entra ID `{tid}_{oid}`).
   - Persistence: Azure AI Foundry Memory Store.
   - Does not replace the checkpointer; it complements context.
   - **Status**: the service (`FoundryMemoryService`) is available as a singleton but is **not automatically invoked** in the agent graph yet. Automatic integration into graph nodes is future work.

3. **A2A Task Store**
   - Purpose: A2A task state (`taskId`, status, artifacts, task history).
   - Scope: task lifecycle and progress.
   - Current state: persistent PostgreSQL-backed storage when the DB health check is healthy, with automatic fallback to in-process memory when persistence is unavailable.
   - Operational note: multi-instance and restart durability depend on the PostgreSQL-backed store being available; the in-memory fallback is best-effort only.

> **Note**: there is no client-side message persistence (localStorage). The UI does not store conversations locally; all conversational state resides in the backend.

## Source of Truth and Reconciliation

- Conversation: **Backend checkpointer**.
- User semantic knowledge: **Foundry Memory Store** (once automatic integration is enabled).
- In case of conflict, the backend prevails (checkpointer/task state).

## Recommended ID Mapping

- `contextId` (A2A): on the first request this is a client-generated UUID. The backend replaces it with the **Foundry conversation ID** returned by the Conversations API and sends it back to the client in the initial SSE event of the task. From that point on, `contextId` carries the Foundry conversation ID for continuity.
- `taskId` (A2A): execution/progress identity, not the primary conversation identity.

## Per-Turn Flow

1. Client sends a message with `contextId` (UUID on the first turn, Foundry conversation ID on subsequent turns).
2. Backend resolves or creates a Foundry conversation ID from `contextId`.
3. Executes the call to the Foundry Hosted Agent (Responses API with `conversation=conv_id`).
4. Retrieves relevant semantic memory (Foundry Memory Store) for the prompt _(future — service available but not automatically invoked)_.
5. Streams A2A SSE events with `contextId` = Foundry conversation ID.
6. Persists super-step checkpoint.

## Latency and Quality

- The checkpointer overhead is typically smaller than LLM/retrieval time.
- To minimize impact:
  - co-locate API + DB,
  - use connection pooling,
  - keep state compact (avoid large payloads in checkpoints),
  - track p50/p95 metrics per phase.

## Recommended Operational Policies

- Retention policies per environment (dev/stage/prod).
- Per-user/conversation deletion (GDPR) using `delete_thread`.
- Encryption at rest for sensitive state where applicable.
- Traceability via `contextId`, `taskId`, `thread_id` in logs/metrics.
