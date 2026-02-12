# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**QPrisma** is an intelligent multimedia processing platform for analyzing video/image content using AI. It combines computer vision, LLMs, and advanced RAG to provide automatic content processing, conversational search, and semantic analysis.

## Architecture

```
Frontend (Next.js 16) ←→ Backend API (FastAPI) ←→ Azure Services
                              ↓
                   LangGraph Video Agent
                      (ReAct pattern)
                              ↓
                      Processing Services
                    (Video, Audio, Vision AI)
                              ↓
                      Storage & Indexing
                   (Blob, PostgreSQL, Neo4j)
```

**Backend** (Python 3.11+): FastAPI + LangGraph agents + Celery workers
**Frontend** (TypeScript): Next.js 16 / React 19 / Tailwind CSS 4 / SWR
**Data**: PostgreSQL (metadata), Neo4j (Knowledge Graph), Redis Stack (cache/queue/checkpoints), Azure Blob (media files)

## Development Commands

### Infrastructure
```bash
docker-compose up -d redis postgres neo4j          # Core services
docker-compose --profile full up -d                 # Full stack + Celery
docker-compose --profile debug up -d                # + pgAdmin, Redis Commander
```

### Backend
```bash
cd backend
uv venv && uv pip install -e .           # Install (uv recommended)
.venv\Scripts\activate                    # Windows
source .venv/bin/activate                 # Linux/Mac
python api/main.py                        # API server (auto-reload) → http://localhost:8000/docs

# Tests (asyncio_mode = "auto" in pyproject.toml — no @pytest.mark.asyncio needed)
pytest tests/                             # All tests
pytest tests/test_api.py -v               # Single file
pytest tests/ -k "test_search"            # Pattern match

# Linting (line-length = 100, target = py311)
ruff check .                              # Lint
ruff check . --fix                        # Auto-fix
black .                                   # Format
```

### Frontend
```bash
cd frontend
npm install
npm run dev                               # Dev server → http://localhost:3000
npm run build                             # Production build
npm run lint                              # ESLint
npm run typecheck                         # TypeScript check
npm test                                  # Jest
npm run test:coverage                     # With coverage
```

## LangGraph Agent System

Two LangGraph StateGraph agents in `backend/agent/`:

**Video Agent** (`graphs/video.py`): `START → call_model → has_tool_calls? → tools → update_context → call_model → ... → END`
- 16 search/analysis tools in `tools/general.py` (SEARCH_TOOLS, MULTI_VIDEO_TOOLS)
- MAX_TOOL_ITERATIONS = 5, MAX_CONTEXT_TOKENS = 100000

**Editor Agent** (`graphs/editor.py`): `START → call_model → tools_condition? → tools → call_model → ... → END`
- 15 clip/subtitle/export tools in `tools/editor.py` (EDITOR_TOOLS)
- MAX_EDITOR_TOOL_ITERATIONS = 8
- Tools split into DESTRUCTIVE_TOOLS and SAFE_TOOLS for HITL confirmation

**State**: TypedDict with `Annotated[list, add_messages]` reducer, input/output schema separation (AgentInputState/AgentOutputState)

**Checkpointers**: Production cascade — PostgreSQL → Redis → MemorySaver

### Agent Memory Architecture (Current)
- **Short-term operational memory**: LangGraph checkpointer persists full thread state for resumability/retries.
- **Durable full tool outputs**: `ToolArtifactService` stores complete payloads (Redis hot cache + Blob + PostgreSQL metadata).
- **Semantic long-term memory**: `Mem0MemoryService` persists/retrieves compact summaries when enabled.
- **Prompt-time context strategy**:
  - Hybrid retrieval (local memory + Mem0 + artifact refs)
  - Lightweight reranking (lexical overlap + semantic score + recency)
  - Dynamic context budget before model call
  - Selective artifact rehydration for detail-heavy queries
- **Observability**: Use structured logger + `Metrics` counters/histograms (no `print()` in runtime paths).

### LangGraph Version Notes (v1.0+)
- `from langgraph.types import RetryPolicy` (NOT `langgraph.pregel`)
- Use `retry_policy=` parameter in `add_node()` (NOT `retry=`)
- `langgraph.pregel.types` is deprecated — use `langgraph.types`

## Key Architecture Patterns

### Agent Tools — Never Raise Exceptions
```python
@tool
async def my_tool(query: str, media_id: Annotated[str | None, InjectedState("media_id")] = None) -> dict:
    """Tool description for LLM."""
    try:
        results = await do_search(media_id, query)
        return {"results": results, "count": len(results)}
    except Exception as e:
        return {"error": str(e), "results": [], "count": 0}  # Return error dict, never raise
```

### Lazy Initialization Singletons
Azure clients and services use global singleton pattern with lazy init in `api/dependencies.py` (single source of truth):
```python
_service: MyService | None = None
def get_my_service() -> MyService:
    global _service
    if _service is None:
        _service = MyService()
    return _service
```

### Service Layer Extraction
Business logic lives in `services/`, NOT in route handlers. Route handlers should delegate to services:
- `services/chat_service.py` — ChatService (RAG chat with video context)
- `services/structure_service.py` — StructureService (video scene/chapter generation)
- `services/graph_search_service.py` — GraphSearchService (hybrid search)

### Centralized Configuration
All configuration uses `core.config.settings` (Pydantic Settings). Do NOT use `os.getenv()` directly — use the typed settings object:
```python
from core.config import settings
settings.azure.openai_endpoint       # Azure OpenAI
settings.azure.storage_connection     # Blob Storage
settings.neo4j.uri                    # Neo4j
settings.redis.url                    # Redis
settings.app.environment              # App environment
```

### Timezone-Aware Datetimes
Always use `datetime.now(UTC)` (never `datetime.utcnow()` which is deprecated in Python 3.12+):
```python
from datetime import UTC, datetime
now = datetime.now(UTC)
```

### Authentication on All Endpoints
Every endpoint must require authentication via `Depends(get_current_user)`:
```python
from api.dependencies import get_current_user
from models.user import User

@router.get("/items")
async def list_items(current_user: User = Depends(get_current_user)):
    ...
```

### Model Caching
`@lru_cache(maxsize=4)` on LLM model creation functions to avoid re-creating per invocation.

## File Naming Conventions

| Type | Pattern | Example |
|------|---------|---------|
| API Route | `{name}_routes.py` | `media_routes.py` |
| Service | `{name}_service.py` or `{name}_processor.py` | `embedding_service.py` |
| Agent Tool | grouped in `tools/general.py` or `tools/editor.py` | |
| Pydantic Model | `{name}.py` in `models/` | `ffmpeg_config.py`, `graph_route_schemas.py` |
| React Component | `{Name}.tsx` | `VideoPlayer.tsx` |
| Python Test | `test_{name}.py` | `test_langgraph_agent.py` |
| React Test | `{Name}.test.tsx` | `VideoPlayer.test.tsx` |

## Adding New Features

### New Agent Tool
1. Add tool function in `agent/tools/general.py` or `editor.py` with `@tool` decorator
2. Use `InjectedState` for context (media_id, video_context)
3. Export in `agent/tools/__init__.py` under `SEARCH_TOOLS` or `EDITOR_TOOLS`

### New Processing Service
1. Create service in `backend/services/`
2. Add lazy init getter in `api/dependencies.py`
3. Create route in `api/routes/{name}_routes.py`
4. Register router in `api/main.py`

### New API Route
```python
router = APIRouter(prefix="/myroute", tags=["MyRoute"])

@router.get("/")
async def list_items(
    current_user: Annotated[dict, Depends(get_current_user)],
    db=Depends(get_database_service),
) -> list[ItemResponse]:
    return await db.list_items(current_user["user_id"])
```

## Video Processing Pipeline

1. Upload → Azure Blob Storage
2. Metadata → PostgreSQL
3. Frame extraction → FFmpeg (recommended: presets fast/balanced/quality) or OpenCV
4. Vision analysis → GPT-4o (standard or batch API for 50% cost savings)
5. Audio transcription → Whisper
6. Embeddings → text-embedding-3-large
7. Indexing → Neo4j Knowledge Graph

## Environment Configuration

Backend: `backend/.env` — requires AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_API_KEY, AZURE_STORAGE_CONNECTION_STRING, DATABASE_URL, NEO4J_URI, REDIS_URL, JWT_SECRET_KEY

Optional memory/artifact runtime variables:
- `MEM0_ENABLED` (true/false)
- `MEM0_API_KEY` (required for Mem0 Cloud)
- `MEM0_TOP_K` (retrieval top-k)
- `ARTIFACT_CACHE_TTL_SECONDS`
- `ARTIFACT_CACHE_KEY_PREFIX`
- `ARTIFACT_BLOB_PREFIX`

Frontend: `frontend/.env.local` — requires NEXT_PUBLIC_API_URL=http://localhost:8000

## CI/CD Pipeline

Four GitHub Actions workflows in `.github/workflows/`:

```
ci.yml (PR/push) → build-and-push.yml (main push) → deploy-app.yml (auto)
deploy-infra.yml (infra/** changes, independent)
```

### Workflow Commands
```bash
# CI runs automatically on push/PR to main
# Manual triggers:
gh workflow run build-and-push.yml              # Build & push all images
gh workflow run deploy-infra.yml                # Deploy infrastructure
gh workflow run deploy-app.yml -f image_tag=abc123  # Deploy specific image
```

### Key CI/CD Patterns
- **OIDC Authentication**: `azure/login@v2` with federated credentials (no stored secrets)
- **Path Filtering**: `dorny/paths-filter@v3` — only rebuild changed components
- **Docker Layer Caching**: `cache-from: type=gha`, `cache-to: type=gha,mode=max`
- **Deployment with Rollback**: Records previous revision, health checks, auto-rollback on failure
- **Stale Deployment Cancellation**: Cancels running ARM deployments before starting new ones
- **AI Foundry Wait Loop**: Polls provisioning state up to 10 minutes before proceeding
- **Retry Logic**: `nick-fields/retry@v3` for Bicep deployments (3 attempts, 20min timeout)

### Reusable Composite Actions
- `.github/actions/setup-backend/action.yml` — Python 3.11 + uv + dependencies
- `.github/actions/setup-frontend/action.yml` — Node.js 20 + npm install

## Azure Infrastructure (Bicep IaC)

All infrastructure defined in `infra/` with 12 Bicep modules orchestrated by `main.bicep`:

```
infra/
├── main.bicep                  # Orchestrator
├── parameters/dev.bicepparam   # Dev environment config
└── modules/
    ├── ai-foundry.bicep        # AI Foundry + 5 model deployments
    ├── container-apps-env.bicep # Managed env + VNet + Log Analytics
    ├── container-app-api.bicep  # API (ext, 0.5C/1Gi, 1-2 replicas)
    ├── container-app-frontend.bicep  # Frontend (ext, 0.25C/0.5Gi)
    ├── container-app-worker.bicep    # Worker (int, KEDA Redis scaler)
    ├── neo4j.bicep              # Neo4j 5 Community + File Share
    ├── postgresql.bicep         # Flex Server v16 (North Europe)
    ├── redis.bicep              # Managed Redis Enterprise
    ├── storage.bicep            # Blob Storage + media container
    ├── container-registry.bicep # ACR (Basic)
    └── key-vault.bicep          # Key Vault + RBAC roles
```

### Multi-Region Deployment
| Region | Resources |
|--------|-----------|
| West Europe | Container Apps, Redis, Storage, Key Vault, ACR |
| Sweden Central | AI Foundry (model availability) |
| North Europe | PostgreSQL (service availability) |

### Key Infrastructure Patterns
- **VNet Integration**: Required for Neo4j Bolt (TCP) between containers
- **Managed Identity**: API/Worker get Key Vault Secrets User role via system-assigned identity
- **KEDA Autoscaling**: Worker scales 1-3 replicas based on Celery Redis queue depth
- **Container App Secrets**: Database URLs, API keys stored as secrets, referenced by env vars
- **Memory Runtime Wiring**: `infra/main.bicep` injects `MEM0_*` and `ARTIFACT_*` vars into API/Worker Container Apps, with `MEM0_API_KEY` provided as secret reference.

## Evaluation Framework

Benchmarking system in `backend/evaluation/`:

```bash
cd backend
# Run evaluation
python -m evaluation.run_evaluation --config evaluation/configs/default.yaml

# Video-MME subset evaluation
python evaluation/scripts/run_videomme_subset.py

# Ablation studies
python -m evaluation.ablation --config evaluation/configs/ablation.yaml
```

Components: `adapters/` (benchmark formats), `judges/` (LLM evaluators), `metrics/` (scoring), `batch_pipeline/` (scale), `benchmarks/` (Video-MME, MLVU)

## Access Points (Local Dev)

| Service | URL |
|---------|-----|
| Frontend | http://localhost:3000 |
| API Docs (Swagger) | http://localhost:8000/docs |
| Neo4j Browser | http://localhost:7474 |
| Flower (Celery) | http://localhost:5555 |
| pgAdmin | http://localhost:5050 |
| Redis Commander | http://localhost:8081 |
