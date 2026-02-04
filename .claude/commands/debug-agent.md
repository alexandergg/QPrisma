# Debug Agent

Debug and troubleshoot LangGraph video agent issues.

## Usage
```
/debug-agent [--session <session_id>] [--tool <tool_name>] [--trace]
```

## Common Issues and Solutions

### 1. Agent Not Using Tools

**Symptoms:**
- Agent responds without searching the video
- Tool calls not appearing in logs

**Diagnosis:**
```python
# Check if tools are bound correctly
from agent.video_agent_graph import create_video_agent_graph

graph = create_video_agent_graph()
print(graph.get_graph().draw_mermaid())  # Visualize graph

# Check tool definitions
from agent.tools import SEARCH_TOOLS, TOOL_DEFINITIONS
print(f"Available tools: {[t.name for t in SEARCH_TOOLS]}")
print(f"Tool definitions: {len(TOOL_DEFINITIONS)}")
```

**Solutions:**
1. Ensure `media_id` is passed to agent (tools only bind with video context)
2. Check `MAX_TOOL_ITERATIONS` limit (default: 5)
3. Verify tool is in correct list (`SEARCH_TOOLS` vs `EDITOR_TOOLS`)

### 2. Context Window Overflow

**Symptoms:**
- `InvalidRequestError: maximum context length exceeded`
- Agent responses cut off or incomplete

**Diagnosis:**
```python
# Check message sizes
from agent.video_agent import estimate_messages_tokens

messages = state.get("messages", [])
total_tokens = estimate_messages_tokens(messages)
print(f"Total tokens: {total_tokens} / 128000")

# Check tool result sizes
for msg in messages:
    if msg.get("role") == "tool":
        content = msg.get("content", "")
        print(f"Tool result size: {len(content)} chars (~{len(content)//4} tokens)")
```

**Solutions:**
1. Increase truncation in `truncate_tool_result()`
2. Reduce `MAX_TOOL_RESULT_CHARS` (default: 8000)
3. Limit search result count in tool parameters

### 3. Infinite Tool Loops

**Symptoms:**
- Agent keeps calling same tool repeatedly
- Max iterations reached without response

**Diagnosis:**
```python
# Check tool call history
for i, msg in enumerate(messages):
    if msg.get("tool_calls"):
        tools = [tc["function"]["name"] for tc in msg["tool_calls"]]
        print(f"Turn {i}: {tools}")
```

**Solutions:**
1. Add iteration hints in `call_model` (already implemented at `WARN_TOOL_ITERATIONS`)
2. Check tool is returning useful results
3. Review system prompt for clear guidance

### 4. Tool Execution Errors

**Symptoms:**
- Tool returns `{"error": "..."}`
- Agent can't find information that exists

**Diagnosis:**
```python
# Test tool directly
from agent.tools import search_video

result = await search_video(
    media_id="test-media-id",
    query="test query",
)
print(result)

# Check Knowledge Graph connection
from services.knowledge_graph import get_knowledge_graph_service
kg = get_knowledge_graph_service()
status = await kg.health_check()
print(f"Neo4j status: {status}")
```

**Solutions:**
1. Verify Neo4j is running and has data
2. Check embedding service for search tools
3. Verify media_id exists in database

### 5. Session/Memory Issues

**Symptoms:**
- Agent forgets previous conversation
- Checkpointing not working

**Diagnosis:**
```python
# Check checkpointer type
from agent.video_agent_graph import get_video_agent_graph

agent = get_video_agent_graph()
print(f"Checkpointer: {type(agent.checkpointer)}")

# Check Redis connection for AsyncRedisSaver
import redis
r = redis.from_url(os.getenv("REDIS_URL"))
r.ping()

# List stored sessions
keys = r.keys("langgraph:*")
print(f"Stored sessions: {len(keys)}")
```

**Solutions:**
1. Ensure Redis Stack is running (not standard Redis)
2. Use `AsyncRedisSaver` for async operations
3. Check `thread_id` is consistent across turns

### 6. Streaming Not Working

**Symptoms:**
- No events yielded during streaming
- Only final response received

**Diagnosis:**
```python
# Test streaming directly
async for event in agent.run_stream(
    message="test",
    media_id="test-id",
):
    print(f"Event: {event['event']} - {event.get('data', {}).keys()}")
```

**Solutions:**
1. Ensure using `astream_events` with `version="v2"`
2. Check WebSocket connection if through API
3. Verify `streaming=True` in model config

## Debug Logging

Enable detailed logging:

```python
# In your test or main.py
import logging

logging.basicConfig(level=logging.DEBUG)

# Or specific loggers
logging.getLogger("agent").setLevel(logging.DEBUG)
logging.getLogger("langchain").setLevel(logging.DEBUG)
logging.getLogger("langgraph").setLevel(logging.DEBUG)
```

## Graph Visualization

```python
# Generate Mermaid diagram
from agent.video_agent_graph import create_video_agent_graph

graph = create_video_agent_graph()
mermaid = graph.get_graph().draw_mermaid()
print(mermaid)

# Or ASCII art
ascii_diagram = graph.get_graph().draw_ascii()
print(ascii_diagram)
```

## State Inspection

```python
# Get state history for a session
async def inspect_session(session_id: str):
    agent = get_video_agent_graph()
    history = await agent.get_state_history(session_id, limit=5)

    for state in history:
        print(f"Created: {state['created_at']}")
        print(f"Messages: {len(state['values'].get('messages', []))}")
        print(f"Tool calls: {state['values'].get('tool_calls_count', 0)}")
        print("---")
```

## Performance Profiling

```python
import time
from functools import wraps

def profile_tool(func):
    @wraps(func)
    async def wrapper(*args, **kwargs):
        start = time.perf_counter()
        result = await func(*args, **kwargs)
        elapsed = time.perf_counter() - start
        print(f"{func.__name__}: {elapsed:.3f}s")
        return result
    return wrapper

# Apply to tool
search_video = profile_tool(search_video)
```

## Checklist for Debugging
- [ ] Check logs for errors
- [ ] Verify media_id is valid and exists
- [ ] Confirm Neo4j has indexed data
- [ ] Test tool directly outside agent
- [ ] Check token counts aren't exceeding limits
- [ ] Verify Redis Stack (not standard Redis) for checkpointing
- [ ] Review tool iteration count
- [ ] Inspect message history for anomalies
