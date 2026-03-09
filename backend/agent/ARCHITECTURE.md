# Agent Architecture - LangGraph Implementation

## Overview

QPrisma's agent system is built using **LangGraph** for declarative, stateful agent orchestration.
This document describes the architecture and best practices followed.

## Directory Structure

```
agent/
├── __init__.py           # Main exports (VideoAgentGraph, AgentState)
├── a2a.py               # A2A protocol bridge for inter-agent communication
├── prompts.py           # System prompts and templates
├── graphs/              # LangGraph StateGraph definitions
│   ├── __init__.py
│   └── video.py         # Video analysis agent graph
├── nodes/               # Graph node implementations
│   ├── __init__.py
│   └── video_nodes.py   # Video agent nodes (call_model, should_continue)
├── state/               # State definitions with reducers
│   ├── __init__.py
│   └── agent_state.py   # AgentState, VideoContext
├── tools/               # LangGraph @tool implementations
│   ├── __init__.py      # Tool collections (SEARCH_TOOLS)
│   └── general.py       # Search & analysis tools
└── utils/               # Helper functions
    ├── __init__.py
    └── formatting.py    # Timestamp formatting
```

## LangGraph Patterns Used

### 1. State Definition (TypedDict + Annotated)

```python
from typing import Annotated
from typing_extensions import TypedDict
from langgraph.graph.message import add_messages

class AgentState(TypedDict, total=False):
    # Messages with automatic accumulation reducer
    messages: Annotated[list[AnyMessage], add_messages]
    media_id: str | None
    video_context: VideoContext | None
    # ... other state fields
```

### 2. Graph Construction

```python
from langgraph.graph import START, END, StateGraph
from langgraph.prebuilt import ToolNode

workflow = StateGraph(AgentState)
workflow.add_node("call_model", call_model)
workflow.add_node("tools", ToolNode(SEARCH_TOOLS, handle_tool_errors=True))
workflow.add_edge(START, "call_model")
workflow.add_conditional_edges("call_model", should_continue, {"tools": "tools", END: END})
workflow.add_edge("tools", "call_model")
graph = workflow.compile(checkpointer=checkpointer)
```

### 3. Tool Definition with InjectedState

```python
from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState

@tool
async def search_video(
    query: Annotated[str, "What to search for"],
    media_id: Annotated[str | None, InjectedState("media_id")] = None,
) -> dict[str, Any]:
    """Tool docstring for LLM."""
    if not media_id:
        return {"error": "No video context available.", "results": []}
    # ... implementation
```

### 4. Conditional Routing

```python
from typing import Literal

def should_continue(state: AgentState) -> Literal["tools", "__end__"]:
    """Determine next step based on tool calls."""
    last_message = state["messages"][-1]
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        return "tools"
    return END
```

## Graph Architectures

### Video Agent Graph

```
START → call_model → has_tool_calls? → tools → update_context → call_model → ... → END
                          ↓ no
                        END
```

**Nodes:**
- `call_model`: Invokes LLM with tools bound
- `tools`: Executes tool calls via ToolNode
- `update_context`: Updates conversation memory

**Features:**
- Iteration limits (MAX_TOOL_ITERATIONS=5)
- Message trimming for context window management
- Conversation context tracking

## Best Practices Followed

| Practice | Implementation |
|----------|----------------|
| TypedDict state | ✅ `AgentState(TypedDict)` |
| Annotated reducers | ✅ `add_messages` for message accumulation |
| START/END constants | ✅ Imported from `langgraph.graph` |
| Prebuilt ToolNode | ✅ With `handle_tool_errors=True` |
| InjectedState for tools | ✅ Context injection without globals |
| Async nodes | ✅ All nodes are `async def` |
| RunnableConfig | ✅ Passed to all node functions |
| Checkpointer support | ✅ MemorySaver and Redis |
| Graph visualization | ✅ `get_graph().draw_mermaid()` |

## Configuration

### ConfigSchema

```python
class ConfigSchema(TypedDict, total=False):
    model_deployment: str
    temperature: float
    max_tokens: int
    max_iterations: int
```

### Environment Variables

- `AZURE_OPENAI_ENDPOINT`
- `AZURE_OPENAI_API_KEY`
- `AZURE_OPENAI_DEPLOYMENT_GPT`
- `AZURE_OPENAI_API_VERSION`

## Testing

```bash
# Run agent tests
pytest tests/test_langgraph_agent.py -v

# Test graph compilation
python -c "from agent import VideoAgentGraph; g = VideoAgentGraph(); print(g.get_graph_diagram())"
```

## A2A Protocol Integration

The `a2a.py` module bridges LangGraph agents with the A2A (Agent-to-Agent) protocol:

- Task lifecycle management (submitted → working → completed)
- Streaming support via `astream_events`
- Artifact generation for results
- Multi-agent orchestration support

## Performance Considerations

1. **Message Trimming**: Prevents context window overflow with `trim_messages`
2. **Tool Result Truncation**: Large results are truncated to 6000 chars
3. **Iteration Limits**: Max 5 tool calls per turn
4. **Token Estimation**: Rough estimate for context management

## References

- [LangGraph Documentation](https://langchain-ai.github.io/langgraph/)
- [LangGraph GitHub](https://github.com/langchain-ai/langgraph)
- [A2A Protocol Specification](https://a2a-protocol.org/)
