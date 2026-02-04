# 4. Use LangGraph for Agent Orchestration

Date: 2024-02-04

## Status

Accepted

## Context

We need an agent framework that supports:
- Stateful multi-turn conversations.
- Cyclic graphs (loops) for iterative reasoning (ReAct pattern).
- Human-in-the-loop capabilities (breakpoints).
- Persistence/Checkpointing of conversation state.

## Decision

We will use **LangGraph**.

## Consequences

### Positive
- **Control**: Provides fine-grained control over the cognitive architecture (StateGraph) compared to purely autonomous agents.
- **Persistence**: Built-in checkpointer support (e.g., Redis) for long-running sessions.
- **State Management**: TypedDict state makes data flow explicit and debuggable.
- **Ecosystem**: Integrates natively with LangChain tools and models.

### Negative
- **New Abstraction**: Requires learning the graph-based mental model (Nodes/Edges).
- **Boilerplate**: More verbose setup than simple `AgentExecutor`.
