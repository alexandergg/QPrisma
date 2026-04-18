# QPrisma Hosted Agent Converter

This document explains the custom state converter used by the QPrisma Hosted
Agent and the response-shape contract that Azure AI Foundry evaluations rely on.

## Why a custom converter?

QPrisma wraps its LangGraph video agent with the official Foundry Hosted Agent
adapter:

```python
from azure.ai.agentserver.langgraph import from_langgraph
app = from_langgraph(graph)
```

`from_langgraph()` ships a default `ResponseAPIMessagesNonStreamResponseConverter`
that translates LangGraph state updates into Responses-API items. Two concrete
QPrisma requirements are not met by the default converter:

1. **Multi tool-call fan-out in a single super-step.** The default adapter emits
   only the first `function_call` item when one `AIMessage` triggers multiple
   tools in parallel, breaking traces used by Foundry agent evaluations.
2. **`response_mode` selection.** QPrisma allows callers to opt in to either a
   full trace (`full`) or a single final message (`final_answer`). The
   default adapter does not understand either knob.

`backend/agent/hosted/state_converter.py` subclasses the SDK converter and
overrides `convert()` to address both gaps while preserving the SDK's item
shape, id generation, and HITL support.

## `response_mode`

Clients can still select the response shape by injecting a `QPRISMA_CONTEXT`
marker at the top of the user message:

```
[QPRISMA_CONTEXT:{"media_id":"...","user_id":"...","response_mode":"final_answer"}]
What happens at minute 3 of this video?
```

Supported values:

| Value           | Behavior                                                          |
| --------------- | ----------------------------------------------------------------- |
| `full`          | Emit every assistant message, tool call, and tool output (default). |
| `final_answer`  | Strip intermediate tool calls/outputs; emit only the final answer.  |

In `final_answer` mode the converter guarantees a single, non-empty assistant
message. When the final `AIMessage` is empty (tool-only or whitespace) the
converter synthesizes a fallback placeholder so downstream evaluators never see
a null or blank `response`.

The current production/frontend path does **not** set `response_mode` by
default. It sends `media_id`, `user_id`, and `session_id` in
`QPRISMA_CONTEXT`, and relies on the converter's default `full` mode. Treat
`final_answer` as a legacy opt-in for targeted evaluation/debug scenarios until
the adapter audit proves it can be removed safely.

## Context injection

Besides `response_mode`, `QPRISMA_CONTEXT` also carries:

- `media_id` — injected into the LangGraph input state so tools can scope
  queries to a specific video. Required for video-aware queries.
- `user_id` — propagated for audit, personalization, and retrieval filters.

Both keys are forwarded to the graph's input state and are **not** included in
the resulting prompt text.

## Content-shape invariant

Foundry `microsoft/ai-agent-evals@v3-beta` derives the `response` input from
`sample.output[*].content`. It fails every evaluation row with
`Response is a required input and cannot be None` when that field lands as a
JSON-stringified list or a plain string rather than a typed list of content
parts.

To defend against regressions, `QPrismaNonStreamResponseConverter.convert()`
runs a final sanitization pass before returning:

- Every `ResponsesAssistantMessageItemResource` is asserted to carry a `list`
  of typed SDK content parts (for example `ItemContent({"type": "output_text", ...})`).
- Any item whose content is a `str`, `None`, or a list containing raw strings
  is rebuilt via `self.convert_MessageContent(...)` so the emitted shape stays
  SDK-typed end-to-end.

The invariant is covered by the `TestContentShapeInvariant` tests in
`backend/tests/test_state_converter_response.py`.

## Files

- `backend/agent/hosted/state_converter.py` — converter + sanitization.
- `backend/agent/hosted/main.py` — builds the hosted app and passes
  `QPrismaStateConverter(graph=graph)` to `from_langgraph(...)`.
- `backend/tests/test_state_converter_response.py` — end-to-end shape tests.

## Related

- [`BACKEND_ARCHITECTURE.md`](./BACKEND_ARCHITECTURE.md) — tool modules and
  `@tool`-decorated LangGraph patterns used by the hosted agent.
- [`AGENTS.md`](../AGENTS.md) — operating rules for the agent and services.
