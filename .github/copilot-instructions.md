# GitHub Copilot Instructions for QPrisma

This document provides codebase architecture and implementation conventions for GitHub Copilot when
working with QPrisma. Operational workflow rules live in `AGENTS.md`; path-specific guidance lives in
`.github/instructions/*.instructions.md`; executable task guidance lives in `.github/skills/*/SKILL.md`.

## Instruction Boundaries

- Use `AGENTS.md` for repo workflow, validation gates, PR hygiene, changelog discipline, and agent/skill routing.
- Use this file for QPrisma-specific architecture, code patterns, imports, and implementation examples.
- Use path-specific instructions before editing backend, frontend, infrastructure, or documentation files.
- Keep generated answers grounded in current implementation; do not duplicate large guidance blocks across files.

## Project Overview

QPrisma is an intelligent multimedia processing platform built with:
- **Backend**: FastAPI (Python 3.11+) with LangGraph agents
- **Frontend**: Next.js 16 with React 19
- **Data**: PostgreSQL, Neo4j Knowledge Graph
- **AI**: Azure AI Foundry (GPT-4o, GPT-5.2-chat, Whisper, text-embedding-3-large)
- **Infrastructure**: Azure Container Apps, Bicep IaC, GitHub Actions CI/CD

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

### Centralized Configuration

All configuration uses `core.config.settings` (Pydantic Settings). Do NOT use `os.getenv()` directly:
```python
from core.config import settings
settings.azure.openai_endpoint       # Azure OpenAI
settings.azure.storage_connection     # Blob Storage
settings.neo4j.uri                    # Neo4j
settings.app.environment              # App environment
```

### Service Layer Extraction

Business logic lives in `services/`, NOT in route handlers:
- `services/structure_service.py` — StructureService (video scene/chapter generation)
- `services/graph_search_service.py` — GraphSearchService (hybrid search)
- `agent/a2a.py` and `api/routes/a2a_*` — A2A chat/task orchestration for agent conversations

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

### LangGraph Memory & Context Patterns

Use the current layered memory approach:
- **Checkpointer** for thread-scoped operational state (resume/retry continuity)
- **Artifact storage** for full tool payloads (`ToolArtifactService`: Blob + Postgres metadata + local hot-cache)
- **Foundry Memory Store** for compact semantic summaries (long-term user memory)

Before each model call, prefer:
1. Hybrid candidate collection (local memory + Foundry Memory Store + artifact refs)
2. Reranking (lexical overlap + semantic signal + recency)
3. Dynamic context budget
4. Selective artifact rehydration only for detail-heavy queries

Never use `print()` in runtime paths; use structured logging (`agent.utils.observability.get_logger`) and `Metrics`.

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
| Service | `{name}_service.py` or `{name}_processor.py` | `embedding_service.py` |
| Agent Tool | grouped by domain in `tools/` | `search_tools.py`, `analysis_tools.py` |
| Pydantic Model | `{name}.py` in `models/` | `ffmpeg_config.py`, `graph_route_schemas.py` |
| React Component | `{Name}.tsx` | `VideoPlayer.tsx` |
| Test (Python) | `test_{name}.py` | `test_langgraph_agent.py` |
| Test (React) | `{Name}.test.tsx` | `VideoPlayer.test.tsx` |

## Key Directories

```
backend/
├── api/
│   ├── main.py              # FastAPI app entry point
│   ├── dependencies.py      # Lazy init singletons (single source of truth)
│   └── routes/              # FastAPI route modules
├── agent/
│   ├── graphs/              # StateGraph definitions (video.py)
│   ├── nodes/               # Node implementations (base, video)
│   ├── state/               # AgentInputState / AgentOutputState
│   ├── tools/               # Search, analysis, context, highlight, multi-video tools
│   ├── utils/               # formatting.py, observability.py
│   ├── a2a.py               # Agent-to-Agent executor
│   └── prompts.py           # System prompts
├── core/                    # config.py, logging_config.py, exceptions.py, async_utils.py
├── services/                # Business logic services
├── models/                  # Pydantic models and schemas
├── evaluation/              # Video-MME benchmark evaluation pipeline
├── functions/               # Azure Function bridge for Databricks dispatch/status
└── tests/                   # pytest tests

databricks/
└── video-pipeline/          # Databricks Asset Bundle + modular video pipeline package

frontend/
├── app/                     # Next.js 16 App Router pages
├── components/              # React 19 components
└── lib/                     # Utility functions and API client

infra/
├── main.bicep               # Bicep orchestrator (12 modules)
├── modules/                 # ACR, ACA, AI Foundry, PostgreSQL, Neo4j, etc.
└── parameters/              # Environment-specific parameters (dev.bicepparam)

.github/
├── workflows/               # CI/CD, deployment, evaluation, release automation
├── actions/                 # Reusable composite actions
├── agents/                  # Domain-specific Copilot agents
├── skills/                  # Operational skills for repeatable workflows
└── instructions/            # Path-scoped Copilot instructions
```

## CI/CD Pipeline

QPrisma uses GitHub Actions for CI, security, image build, infrastructure deployment, hosted-agent
deployment, evaluation, and release automation. Core workflows include:

| Workflow | Trigger | Purpose |
|----------|---------|---------|
| `ci.yml` | Push/PR to `main` | Backend lint/test + Frontend lint/typecheck/test (5 parallel jobs) |
| `build-and-push.yml` | Push to `main` (path-filtered) | Build Docker images, push to ACR, trigger deployment |
| `deploy-infra.yml` | Push to `main` (`infra/**`) | Validate + deploy Azure infrastructure via Bicep |
| `deploy-app.yml` | Auto-triggered | Rolling container updates with health checks + rollback |
| `deploy-hosted-agent.yml` | Manual/path-triggered | Deploy the Foundry-hosted QPrisma agent |
| `evaluate-agent.yml` | Manual | Run Foundry agent evaluation |
| `benchmark-video-mme.yml` | Manual | Run Video-MME benchmark workflow |

Key patterns: OIDC auth, path-filtered builds, GHA Docker layer caching, automatic rollback, KEDA autoscaling.

## Azure Infrastructure

Infrastructure is orchestrated by `infra/main.bicep` and modularized under `infra/modules/`:
- **Compute**: Container Apps (API, Frontend) + Neo4j in VNet-enabled managed environment
- **AI**: Azure AI Foundry with 5 model deployments (West Europe)
- **Data**: PostgreSQL Flex v16 (North Europe), Blob Storage, external managed Neo4j
- **Security**: Key Vault with RBAC + managed identity access
- **Observability**: Log Analytics workspace

Multi-region: West Europe (apps + AI), North Europe (PostgreSQL).

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

# Config (always use settings, never os.getenv)
from core.config import settings

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

-- Use UNWIND for batch operations (not one-by-one)
UNWIND $items AS item
CREATE (n:Entity {name: item.name, type: item.type})
```

## Testing Patterns

### Python (pytest)
```python
# asyncio_mode = "auto" — no @pytest.mark.asyncio needed
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

## Error Handling

- Backend: Use HTTPException with appropriate status codes
- Frontend: Display user-friendly error messages
- Agent tools: Return error dict, never raise exceptions
- Always log errors with context
- Use `datetime.now(UTC)` (never `datetime.utcnow()`)

## Performance Considerations

- Use async/await for I/O operations
- Implement lazy initialization for expensive resources
- Use local best-effort caching for frequent queries
- Batch Azure OpenAI calls when possible (50% cost savings)
- Truncate large tool results to prevent context overflow
- Keep full tool payloads in artifacts and inject compact/ranked context into prompts
- Rehydrate artifacts selectively instead of expanding every tool output
- `@lru_cache(maxsize=4)` on LLM model creation functions
