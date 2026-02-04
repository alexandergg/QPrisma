# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**QPrisma** is an intelligent multimedia processing platform for analyzing video and image content using AI. It combines computer vision, LLMs, and advanced RAG to provide automatic content processing, conversational search, and semantic analysis of multimedia content.

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

### Core Components

**Backend (Python 3.11+)**
- `backend/api/main.py`: FastAPI entry point with lazy-initialized Azure clients
- `backend/api/routes/`: Modular route files (auth, batch, media, processing, graph, chat, etc.)
- `backend/agent/`: LangGraph-based video agent with ReAct pattern
- `backend/services/`: Processing services (video, audio, FFmpeg, knowledge graph, embeddings)
- `backend/models/`: Pydantic configuration models
- `backend/tasks/`: Celery background tasks

**Frontend (TypeScript/React)**
- Next.js 16 with App Router
- React 19 with Tailwind CSS 4
- SWR for data fetching, ReactFlow for pipeline visualization

**Data Layer**
- PostgreSQL: Metadata storage
- Neo4j: Knowledge Graph for semantic retrieval
- Redis Stack: Cache, Celery queue, and LangGraph checkpoints (RediSearch required)
- Azure Blob Storage: Media files

## LangGraph Agent System

The platform uses two agent implementations in `backend/agent/`:

### VideoAgent (`video_agent.py`)
Custom ReAct-style agent using Azure OpenAI function calling directly:
```
START → call_model → has_tool_calls? → execute_tools → call_model → ... → END
                          ↓ no
                         END
```

### VideoAgentGraph (`video_agent_graph.py`)
LangGraph StateGraph implementation with built-in streaming and checkpointing:
```
START → call_model → should_continue? → tools → update_context → call_model → ... → END
                          ↓ end
                         END
```

**Key files:**
- `agent/state.py`, `agent/graph_state.py`: TypedDict state definitions
- `agent/tools/`: Tool implementations (search, navigation, structure, graph, export, subtitles)
- `agent/prompts.py`: System prompts for video context
- `agent/memory.py`: Conversation memory handling

**Tool registration pattern:**
```python
# In agent/tools/__init__.py - tools are LangChain-style
TOOL_DEFINITIONS = [tool.to_openai_tool() for tool in ALL_TOOLS]
SEARCH_TOOLS = [search_video, get_transcript, ...]  # For LangGraph ToolNode
```

## Development Commands

### Infrastructure
```bash
# Start required services (PostgreSQL, Neo4j, Redis Stack)
docker-compose up -d redis postgres neo4j

# Full stack with Celery workers
docker-compose --profile full up -d

# With debug UIs (pgAdmin, Redis Commander)
docker-compose --profile debug up -d
```

### AI-Assisted Development
This project is configured with Claude Code commands (slash commands) to accelerate development. See [.claude/README.md](.claude/README.md) for details.

```bash
# Example commands
/create-route media        # Create new API endpoint
/create-component Player   # Create React component
/create-service export     # Create backend service
/process-video video.mp4   # Run video pipeline
/debug-agent               # Debug LangGraph issues
```

### Backend
```bash
cd backend

# Install with uv (recommended)
uv venv && uv pip install -e .

# Activate environment
source .venv/bin/activate  # Linux/Mac
.venv\Scripts\activate     # Windows

# Run API server (auto-reload enabled)
python api/main.py
# http://localhost:8000/docs for Swagger UI

# Run tests
pytest tests/
pytest tests/test_api.py -v  # Specific file
pytest tests/ -k "test_search"  # Pattern match

# Linting
ruff check .
ruff check . --fix
black .
```

### Frontend
```bash
cd frontend
npm install
npm run dev          # Development server at http://localhost:3000
npm run build        # Production build
npm run lint         # ESLint
npm run typecheck    # TypeScript check
npm test             # Jest tests
```

## Environment Configuration

### Backend (`backend/.env`)
```bash
# Azure OpenAI (required)
AZURE_OPENAI_ENDPOINT=https://<resource>.openai.azure.com/
AZURE_OPENAI_API_KEY=<key>
AZURE_OPENAI_DEPLOYMENT_GPT=gpt-4o
AZURE_OPENAI_DEPLOYMENT_GPT_BATCH=gpt-4o-global-batch  # For 50% cost savings
AZURE_OPENAI_DEPLOYMENT_EMBEDDING=text-embedding-3-large
AZURE_OPENAI_API_VERSION=2024-08-01-preview

# Azure Storage
AZURE_STORAGE_CONNECTION_STRING=<connection_string>
AZURE_STORAGE_CONTAINER_NAME=media

# Databases
DATABASE_URL=postgresql://qprisma:qprisma123@localhost:5432/qprisma
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=qprisma123
REDIS_URL=redis://localhost:6379/0

# Auth
JWT_SECRET_KEY=<secret>
```

### Frontend (`frontend/.env.local`)
```bash
NEXT_PUBLIC_API_URL=http://localhost:8000
```

## Key Architecture Patterns

### Lazy Initialization
Azure clients use lazy initialization in `api/main.py`:
```python
_blob_service = None

def get_blob_service():
    global _blob_service
    if _blob_service is None:
        _blob_service = BlobServiceClient.from_connection_string(...)
    return _blob_service
```

### Service Layer
Each capability is isolated in `backend/services/`:
- Services maintain Azure client state
- Services are singletons initialized on first use
- Clear interfaces for specific tasks (video processing, embeddings, graph search)

### Agent State Management
LangGraph agents use TypedDict states with message accumulation:
```python
class AgentState(TypedDict):
    messages: Annotated[list, add_messages]  # Reducer pattern
    video_context: VideoContext | None
    tool_calls_count: int
    # ...
```

### Context Window Management
Agent implements token-aware truncation:
- `MAX_CONTEXT_TOKENS = 100000` (leaves headroom below 128k)
- `MAX_TOOL_RESULT_CHARS = 8000` per tool result
- Intelligent truncation preserves structure (keeps first/last messages)

## Video Processing Pipeline

Two processing approaches:

1. **FFmpeg-based** (recommended): `services/ffmpeg_processor.py`
   - Presets: fast (1 FPS, 720p), balanced (2 FPS, 1080p), quality (5 FPS, original)
   - Hardware acceleration support
   - Configuration via `FFmpegProcessingConfig`

2. **OpenCV-based**: `services/video_processor.py`
   - Direct frame extraction with cv2
   - More control over frame selection

### Processing Flow
1. Upload → Azure Blob Storage
2. Metadata → PostgreSQL
3. Frame extraction → FFmpeg/OpenCV
4. Vision analysis → GPT-4o (standard or batch API)
5. Audio transcription → Whisper
6. Embeddings → text-embedding-3-large
7. Indexing → Neo4j Knowledge Graph

## API Structure

Routes are modular in `backend/api/routes/`:
- `/media/*`: Upload, list, delete, search
- `/processing/*`: FFmpeg pipeline, presets, batch jobs
- `/graph/*`: Knowledge Graph search, hierarchy, expansion
- `/chat/*`: Conversational AI with RAG
- `/batch/*`: Azure OpenAI Batch API management
- `/auth/*`: JWT authentication

Interactive docs at `http://localhost:8000/docs`

## Adding New Features

### New Processing Service
1. Create service in `backend/services/`
2. Add lazy initialization in `api/main.py`
3. Create route file in `api/routes/`
4. Register router in `api/main.py`

### New Agent Tool
1. Create tool function in `backend/agent/tools/`
2. Use `@tool` decorator from langchain_core.tools
3. Export in `agent/tools/__init__.py`
4. Add to `SEARCH_TOOLS` for LangGraph or `ALL_TOOLS` for custom agent

## System Requirements

- Python 3.11+
- Node.js 20+
- FFmpeg (system install required)
- Docker (for infrastructure)

## Access Points

| Service | URL | Credentials |
|---------|-----|-------------|
| Frontend | http://localhost:3000 | - |
| API Docs | http://localhost:8000/docs | - |
| Neo4j Browser | http://localhost:7474 | neo4j/qprisma123 |
| Flower (Celery) | http://localhost:5555 | admin/qprisma123 |
| pgAdmin | http://localhost:5050 | admin@qprisma.local/qprisma123 |
| Redis Commander | http://localhost:8081 | - |
