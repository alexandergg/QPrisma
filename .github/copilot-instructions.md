# GitHub Copilot Instructions for QPrisma

This document provides context and guidelines for GitHub Copilot when working with the QPrisma codebase.

## Project Overview

QPrisma is an intelligent multimedia processing platform built with:
- **Backend**: FastAPI (Python 3.11+) with LangGraph agents
- **Frontend**: Next.js 16 with React 19
- **Data**: PostgreSQL, Neo4j Knowledge Graph, Redis Stack
- **AI**: Azure OpenAI (GPT-4o, Whisper, text-embedding-3-large)

## Code Style Guidelines

### Python (Backend)

```python
# Use type hints for all function signatures
async def process_video(media_id: str, config: ProcessingConfig) -> ProcessingResult:
    pass

# Use Pydantic for request/response models
class VideoRequest(BaseModel):
    media_id: str
    title: str | None = None

# Async functions for I/O operations
async def fetch_data() -> dict:
    pass

# Use logging, not print
import logging
logger = logging.getLogger(__name__)
logger.info("Processing started")

# Error handling pattern
try:
    result = await service.process(data)
except ValueError as e:
    raise HTTPException(status_code=400, detail=str(e))
except Exception as e:
    logger.error(f"Processing failed: {e}")
    raise HTTPException(status_code=500, detail="Internal error")
```

### TypeScript (Frontend)

```typescript
// Use explicit types, avoid 'any'
interface VideoProps {
  mediaId: string;
  onComplete?: (result: VideoResult) => void;
}

// Functional components with hooks
export function VideoPlayer({ mediaId, onComplete }: VideoProps) {
  const [loading, setLoading] = useState(false);
  // ...
}

// Use 'use client' directive for client components
'use client';

// Fetch from API using environment variable
const API_URL = process.env.NEXT_PUBLIC_API_URL;
const response = await fetch(`${API_URL}/media/${mediaId}`);
```

## Architecture Patterns

### Backend Service Pattern

```python
# Services use lazy initialization singleton pattern
_service_instance: MyService | None = None

def get_my_service() -> MyService:
    global _service_instance
    if _service_instance is None:
        _service_instance = MyService()
    return _service_instance
```

### LangGraph Agent Tools

```python
from langchain_core.tools import tool

@tool
async def my_tool(media_id: str, query: str) -> dict:
    """
    Tool description for LLM to understand when to use this.

    Args:
        media_id: The video ID
        query: Search query

    Returns:
        Results dictionary with 'results' and 'count' keys
    """
    # Never raise exceptions - return error dict
    try:
        results = await do_search(media_id, query)
        return {"results": results, "count": len(results)}
    except Exception as e:
        return {"error": str(e), "results": [], "count": 0}
```

### FastAPI Route Pattern

```python
from fastapi import APIRouter, Depends, HTTPException
from typing import Annotated

router = APIRouter(prefix="/myroute", tags=["MyRoute"])

@router.get("/")
async def list_items(
    current_user: Annotated[dict, Depends(get_current_user)],
    db=Depends(get_database_service),
) -> list[ItemResponse]:
    """List all items for current user."""
    return await db.list_items(current_user["user_id"])
```

### React Component Pattern

```typescript
'use client';

import { useState, useCallback } from 'react';
import useSWR from 'swr';

interface Props {
  mediaId: string;
  className?: string;
}

export function MediaViewer({ mediaId, className = '' }: Props) {
  const { data, error, isLoading } = useSWR(
    `/api/media/${mediaId}`,
    fetcher
  );

  if (isLoading) return <LoadingSpinner />;
  if (error) return <ErrorDisplay error={error} />;

  return (
    <div className={`p-4 ${className}`}>
      {/* Component content */}
    </div>
  );
}
```

## File Naming Conventions

| Type | Pattern | Example |
|------|---------|---------|
| API Route | `{name}_routes.py` | `media_routes.py` |
| Service | `{name}_service.py` | `embedding_service.py` |
| Agent Tool | `{category}_tools.py` | `search_tools.py` |
| Model | `{name}.py` | `ffmpeg_config.py` |
| React Component | `{Name}.tsx` | `VideoPlayer.tsx` |
| Test (Python) | `test_{name}.py` | `test_media_routes.py` |
| Test (React) | `{Name}.test.tsx` | `VideoPlayer.test.tsx` |

## Key Directories

```
backend/
├── api/
│   ├── main.py          # FastAPI app entry point
│   └── routes/          # API route modules
├── agent/
│   ├── video_agent.py   # Custom ReAct agent
│   ├── video_agent_graph.py  # LangGraph agent
│   └── tools/           # Agent tool implementations
├── services/            # Business logic services
├── models/              # Pydantic models
└── tests/               # pytest tests

frontend/
├── app/                 # Next.js App Router pages
├── components/          # React components
└── lib/                 # Utility functions
```

## Common Imports

### Backend

```python
# FastAPI
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

# Async
import asyncio
from typing import Annotated

# Services
from services.database_service import get_database_service
from services.knowledge_graph import get_knowledge_graph_service
from services.embedding_service import get_embedding_service

# Agent
from langchain_core.tools import tool
from langgraph.graph import StateGraph, END, START
```

### Frontend

```typescript
// React
import { useState, useEffect, useCallback, useRef } from 'react';

// SWR
import useSWR from 'swr';

// Icons
import { Loader2, AlertCircle, Play, Pause } from 'lucide-react';

// Types
import type { MediaItem, ProcessingResult } from '@/types';
```

## Neo4j Cypher Patterns

```cypher
-- Always use parameters, never string interpolation
MATCH (v:Video {media_id: $media_id})-[:HAS_FRAME]->(f:Frame)
WHERE f.timestamp >= $start_time
RETURN f.timestamp, f.description
ORDER BY f.timestamp
LIMIT $limit
```

## Testing Patterns

### Python (pytest)

```python
@pytest.mark.asyncio
async def test_process_success(mock_db, sample_data):
    """Test successful processing."""
    with patch("module.get_database_service", return_value=mock_db):
        result = await process(sample_data)
        assert result["success"] is True
```

### TypeScript (Jest)

```typescript
it('handles click events', async () => {
  const handleClick = jest.fn();
  render(<Button onClick={handleClick} />);

  await userEvent.click(screen.getByRole('button'));

  expect(handleClick).toHaveBeenCalledTimes(1);
});
```

## Environment Variables

Always use environment variables for configuration:

```python
# Python
import os
endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
```

```typescript
// TypeScript
const apiUrl = process.env.NEXT_PUBLIC_API_URL;
```

## Error Handling

- Backend: Use HTTPException with appropriate status codes
- Frontend: Display user-friendly error messages
- Agent tools: Return error dict, never raise exceptions
- Always log errors with context

## Performance Considerations

- Use async/await for I/O operations
- Implement lazy initialization for expensive resources
- Use Redis caching for frequent queries
- Batch Azure OpenAI calls when possible (50% cost savings)
- Truncate large tool results to prevent context overflow
