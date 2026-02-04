# Analyze Video

Interact with the QPrisma video agent to analyze and query video content.

## Usage
```
/analyze-video <media_id> <question> [--session <session_id>] [--stream]
```

## Quick Start

### Via API
```bash
# Start a chat session
curl -X POST "http://localhost:8000/chat/abc123" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"message": "Who speaks in the first minute of the video?"}'

# Response
{
  "response": "In the first minute, John Smith (CEO) speaks, introducing the quarterly results presentation. He appears at timestamp 0:05 and continues until 0:58.",
  "sources": [
    {"timestamp": 5.2, "description": "Man in suit at podium"},
    {"timestamp": 35.8, "description": "Same speaker with slides"}
  ],
  "session_id": "session-789"
}
```

### Via WebSocket (Streaming)
```typescript
const ws = new WebSocket(`ws://localhost:8000/chat/ws/abc123`);

ws.onopen = () => {
  ws.send(JSON.stringify({
    message: "What products are shown?",
    session_id: "session-789"
  }));
};

ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  if (data.type === 'token') {
    process.stdout.write(data.content);
  } else if (data.type === 'done') {
    console.log('\n--- Sources ---');
    console.log(data.sources);
  }
};
```

## Programmatic Usage

### Using the Agent Directly
```python
from agent.video_agent_graph import get_video_agent_graph

async def analyze_video(media_id: str, question: str, session_id: str = None):
    agent = get_video_agent_graph()

    # Run agent with question
    result = await agent.run(
        message=question,
        media_id=media_id,
        thread_id=session_id or f"session-{media_id}",
    )

    return {
        "response": result["response"],
        "sources": result.get("sources", []),
        "tool_calls": result.get("tool_calls_count", 0),
    }


# Example usage
result = await analyze_video(
    media_id="abc123",
    question="Describe the main speakers in this video",
)
print(result["response"])
```

### With Streaming
```python
async def analyze_video_stream(media_id: str, question: str):
    agent = get_video_agent_graph()

    async for event in agent.run_stream(
        message=question,
        media_id=media_id,
    ):
        if event["event"] == "on_chat_model_stream":
            # Token from LLM
            chunk = event["data"]["chunk"]
            if content := chunk.content:
                print(content, end="", flush=True)

        elif event["event"] == "on_tool_start":
            # Tool being called
            tool_name = event["data"]["name"]
            print(f"\n[Using tool: {tool_name}]")

        elif event["event"] == "on_tool_end":
            # Tool result
            result = event["data"]["output"]
            print(f"[Tool returned {len(str(result))} chars]")

    print("\n--- Done ---")
```

## Example Questions

### Content Discovery
```
"What happens in this video?"
"Summarize the key points"
"List all people who appear"
"What products or items are shown?"
```

### Timestamp Queries
```
"What happens at 2:30?"
"Find when the speaker mentions pricing"
"When does the demo start?"
"Show me all timestamps with charts or graphs"
```

### Specific Searches
```
"Find all mentions of the word 'revenue'"
"When does someone speak about customer feedback?"
"Show frames where a laptop is visible"
"Find the introduction and conclusion sections"
```

### Comparative Analysis
```
"How does the beginning compare to the end?"
"What changes between the first and second half?"
"Are there any repeated themes?"
```

## Agent Tools

The video agent has access to these tools:

| Tool | Purpose | Example Use |
|------|---------|-------------|
| `search_video` | Semantic search of frames | "Find frames with presentations" |
| `get_frame_at_time` | Get frame at specific timestamp | "What's at 1:30?" |
| `get_transcript` | Get audio transcript | "What is said?" |
| `search_transcript` | Search spoken words | "Find mentions of 'budget'" |
| `get_entities` | List detected entities | "Who appears?" |
| `get_timeline` | Get video timeline | "Show me the structure" |
| `export_clip` | Export video segment | "Extract 1:00 to 2:00" |

## Session Management

### Continue Conversation
```bash
# First message
curl -X POST "http://localhost:8000/chat/abc123" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"message": "Who is the main speaker?"}'

# Response includes session_id
# {"response": "...", "session_id": "sess-xyz"}

# Continue with same session
curl -X POST "http://localhost:8000/chat/abc123" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"message": "When do they first appear?", "session_id": "sess-xyz"}'
```

### Get Session History
```bash
curl "http://localhost:8000/chat/history/sess-xyz" \
  -H "Authorization: Bearer $TOKEN"

# Response
{
  "session_id": "sess-xyz",
  "messages": [
    {"role": "user", "content": "Who is the main speaker?"},
    {"role": "assistant", "content": "The main speaker is..."},
    {"role": "user", "content": "When do they first appear?"},
    {"role": "assistant", "content": "They first appear at..."}
  ]
}
```

### Clear Session
```bash
curl -X DELETE "http://localhost:8000/chat/session/sess-xyz" \
  -H "Authorization: Bearer $TOKEN"
```

## Response Format

### Standard Response
```json
{
  "response": "The video shows a product demo presented by John Smith...",
  "sources": [
    {
      "timestamp": 15.5,
      "description": "Speaker at podium with product image",
      "confidence": 0.95
    },
    {
      "timestamp": 45.2,
      "description": "Hands holding product",
      "confidence": 0.88
    }
  ],
  "session_id": "sess-xyz",
  "tool_calls": 2,
  "tokens_used": {
    "input": 1500,
    "output": 350
  }
}
```

### Streaming Events
```json
// Token event
{"type": "token", "content": "The"}

// Tool start
{"type": "tool_start", "name": "search_video", "args": {"query": "..."}}

// Tool end
{"type": "tool_end", "name": "search_video", "result_count": 5}

// Done
{"type": "done", "response": "...", "sources": [...]}
```

## Error Handling

### Common Errors
```json
// Video not processed
{
  "error": "VIDEO_NOT_PROCESSED",
  "message": "Video abc123 has not been processed. Run /processing/ffmpeg/abc123 first."
}

// No results found
{
  "response": "I couldn't find any content matching your query in this video.",
  "sources": [],
  "suggestion": "Try rephrasing your question or ask about different content."
}

// Context limit reached
{
  "error": "CONTEXT_OVERFLOW",
  "message": "Conversation too long. Start a new session.",
  "session_id": "new-session-id"
}
```

## Cost Optimization

### Batch Processing
```python
# For multiple videos, use batch analysis
async def batch_analyze(media_ids: list[str], question: str):
    results = []
    for media_id in media_ids:
        result = await analyze_video(media_id, question)
        results.append({"media_id": media_id, **result})
    return results
```

### Caching Common Queries
```python
# Cache expensive queries
from functools import lru_cache

@lru_cache(maxsize=100)
def get_video_summary(media_id: str) -> str:
    # Generate and cache summary
    ...
```

## Checklist
- [ ] Video has been processed (status: completed)
- [ ] Knowledge Graph indexed (Neo4j has data)
- [ ] Question is clear and specific
- [ ] Session ID used for follow-up questions
- [ ] Streaming used for long responses
