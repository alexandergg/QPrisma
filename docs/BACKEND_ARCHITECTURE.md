# QPrisma Backend — Technical Architecture Documentation

> **Backend version**: 1.1.0 | **Python**: 3.11+ | **Framework**: FastAPI + LangGraph + Celery
> **Last updated**: February 2026

---

## Table of Contents

1. [General Overview](#1-general-overview)
2. [Project Structure](#2-project-structure)
3. [Configuration System](#3-configuration-system)
4. [API Layer — FastAPI Routes](#4-api-layer--fastapi-routes)
5. [Agent System — LangGraph](#5-agent-system--langgraph)
6. [Service Layer](#6-service-layer)
7. [Data Models — SQLAlchemy + Pydantic](#7-data-models--sqlalchemy--pydantic)
8. [Async Tasks — Celery](#8-async-tasks--celery)
9. [Video Processing Pipeline](#9-video-processing-pipeline)
10. [Knowledge Graph — Neo4j](#10-knowledge-graph--neo4j)
11. [Hybrid Search System](#11-hybrid-search-system)
12. [Memory System — Layered State and Foundry Memory Capability](#12-memory-system--layered-state-and-foundry-memory-capability)
13. [Caching Layer — Redis Enterprise](#13-caching-layer--redis-enterprise)
14. [A2A Protocol — Agent-to-Agent](#14-a2a-protocol--agent-to-agent)
15. [Authentication and Authorization](#15-authentication-and-authorization)
16. [Observability and Monitoring](#16-observability-and-monitoring)
17. [Architecture Patterns and Conventions](#17-architecture-patterns-and-conventions)
18. [Dependencies and Versions](#18-dependencies-and-versions)
19. [Flow Diagrams](#19-flow-diagrams)

---

## 1. General Overview

QPrisma is a multimedia analysis platform powered by AI agents. The backend orchestrates video processing, knowledge extraction, semantic search, and conversational interactions through a LangGraph-based agent system.

### Core Capabilities

| Capability | Technology | Description |
|---|---|---|
| Video Processing | FFmpeg + Whisper | Transcription, scene detection, thumbnails |
| AI Agent | LangGraph + GPT-4o / GPT-5.2-chat | Multi-tool conversational agent |
| Knowledge Graph | Neo4j | Entity relationships and semantic structure |
| Search | PostgreSQL + Neo4j | Hybrid vector + graph search |
| Memory | Checkpointer + artifacts + optional Foundry Memory Store | Thread state, persisted tool artifacts, and available long-term semantic memory capability |
| Cache | Redis Enterprise | Multi-layer caching with TTL |
| Auth | Microsoft Entra ID | OIDC-based authentication and RBAC |
| Tasks | Celery + Redis, optional Service Bus/Databricks dispatch | Async video processing pipeline and Databricks pilot handoff |
| Protocol | A2A (Agent-to-Agent) | Google A2A interoperability protocol |

### AI Model Deployments

| Model | Deployment Name | Purpose |
|---|---|---|
| GPT-5.5 | `gpt-5.5` | Primary chat, tool-calling, and evaluator judge |
| text-embedding-3-large | `text-embedding-3-large` | Semantic embeddings (3072-dim) |
| Whisper | `whisper` | Audio transcription |
| GPT-5.1 (batch) | `gpt-5.1-batch` | Batch processing operations |

### Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                        QPrisma Backend                              │
│                                                                     │
│  ┌─────────────────┐  ┌─────────────────┐  ┌────────────────────┐  │
│  │  FastAPI Routes  │  │  LangGraph Agent │  │  Celery Workers     │  │
│  │  (17 modules)   │  │  (16 tools)      │  │  (async tasks)      │  │
│  └────────┬────────┘  └────────┬────────┘  └─────────┬──────────┘  │
│           │                  │                   │              │
│           └─────────┬────────┘                   │              │
│                     │                             │              │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │              Service Layer (51 files)                      │  │
│  │  chat │ structure │ graph_search │ media │ embedding ...  │  │
│  └───────────────────────────────────────────────────────────────┘  │
│                                                                     │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌───────────┐  │
│  │ PostgreSQL  │  │    Neo4j    │  │    Redis    │  │ Azure Blob│  │
│  │ (primary)   │  │ (knowledge) │  │ (cache)    │  │ (storage) │  │
│  └─────────────┘  └─────────────┘  └─────────────┘  └───────────┘  │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 2. Project Structure

```
backend/
├── api/
│   ├── main.py                      # FastAPI app entry point
│   ├── dependencies.py              # Shared dependency providers
│   └── routes/
│       ├── a2a_agent_cards.py        # A2A agent card endpoints
│       ├── a2a_message_routes.py     # A2A message handling
│       ├── a2a_task_routes.py        # A2A task management
│       ├── auth_routes.py            # Auth endpoints (me/config)
│       ├── batch_routes.py           # Batch processing operations
│       ├── cache_routes.py           # Cache management endpoints
│       ├── chat_routes.py            # Chat/conversation endpoints
│       ├── chunked_upload_routes.py  # Chunked file upload handling
│       ├── graph_routes.py           # Knowledge graph queries
│       ├── jobs_routes.py            # Job status tracking
│       ├── media_routes.py           # Media CRUD operations
│       ├── processing_routes.py      # Media processing endpoints
│       ├── storage_routes.py         # Storage management
│       ├── structure_routes.py       # Scene/chapter generation
│       ├── websocket_manager.py      # WebSocket connection manager
│       └── websocket_routes.py       # WebSocket connections
├── agent/
│   ├── graph.py                     # LangGraph workflow definition
│   ├── nodes.py                     # Graph node functions
│   ├── state.py                     # Agent state schema
│   ├── prompt.py                    # System prompt templates
│   ├── tools/
│   │   ├── search_tools.py          # Search-related tools
│   │   ├── analysis_tools.py        # Content analysis tools
│   │   ├── context_tools.py         # Context retrieval tools
│   │   ├── highlight_tools.py       # Highlight generation tools
│   │   └── multi_video_tools.py     # Cross-video analysis tools
│   └── utils/
│       ├── observability.py         # Agent tracing/metrics
│       └── token_management.py      # Token budget management
├── core/
│   ├── config.py                    # Pydantic Settings (centralized)
│   ├── database.py                  # PostgreSQL session management
│   └── redis_client.py              # Redis connection management
├── models/
│   ├── database.py                  # SQLAlchemy ORM models
│   ├── schemas.py                   # Pydantic request/response schemas
│   └── enums.py                     # Shared enumerations
├── services/                        # Business logic layer (51 files)
│   ├── chat_service.py              # RAG chat with video context
│   ├── structure_service.py         # Scene/chapter generation
│   ├── graph_search_service.py      # Hybrid graph+vector search
│   ├── media_service.py             # Media lifecycle management
│   ├── embedding_service.py         # Vector embedding generation
│   ├── entra_auth_service.py        # Microsoft Entra ID auth
│   ├── foundry_memory_service.py    # Foundry Memory Store
│   ├── ...                           # (41 root files total)
│   └── graph/                       # Graph submodule (10 files)
│       ├── base_graph_service.py     # Base Neo4j operations
│       ├── entity_graph_service.py   # Entity management
│       ├── relationship_service.py   # Relationship CRUD
│       ├── query_builder.py          # Cypher query construction
│       └── ...                       # (10 files total)
├── tasks/
│   ├── celery_app.py                # Celery configuration
│   └── video_tasks.py               # Async video processing tasks
├── evaluation_foundry/              # Azure AI Foundry evaluation
│   ├── config.py                    # Evaluation configuration
│   ├── generate_eval_data.py        # Test data generation
│   ├── register_evaluators.py       # Evaluator registration
│   ├── tool_definitions.py          # Tool schemas for evaluation
│   └── data/                        # Evaluation datasets
└── tests/                           # pytest test suite
    ├── conftest.py                  # Shared fixtures
    ├── test_services/               # Service unit tests
    ├── test_routes/                 # API integration tests
    └── test_agent/                  # Agent workflow tests
```

---

## 3. Configuration System

All configuration is centralized through Pydantic Settings in `core/config.py`. Direct use of `os.getenv()` is prohibited.

### Settings Structure

```python
from pydantic_settings import BaseSettings
from pydantic import Field

class AzureSettings(BaseSettings):
    openai_endpoint: str = Field(alias="AZURE_OPENAI_ENDPOINT")
    openai_api_key: str = Field(alias="AZURE_OPENAI_API_KEY")
    openai_deployment_gpt: str = Field(default="gpt-5.5", alias="AZURE_OPENAI_DEPLOYMENT_GPT")
    openai_deployment_gpt_batch: str | None = Field(
        default="gpt-5.1-batch", alias="AZURE_OPENAI_DEPLOYMENT_GPT_BATCH"
    )
    openai_embedding_deployment: str = Field(
        default="text-embedding-3-large", alias="AZURE_OPENAI_EMBEDDING_DEPLOYMENT"
    )
    storage_connection: str = Field(alias="AZURE_STORAGE_CONNECTION_STRING")
    storage_container: str = Field(default="media", alias="AZURE_STORAGE_CONTAINER")

class DatabaseSettings(BaseSettings):
    url: str = Field(alias="DATABASE_URL")
    pool_size: int = Field(default=10)
    max_overflow: int = Field(default=20)

class Neo4jSettings(BaseSettings):
    uri: str = Field(alias="NEO4J_URI")
    username: str = Field(default="neo4j", alias="NEO4J_USERNAME")
    password: str = Field(alias="NEO4J_PASSWORD")

class RedisSettings(BaseSettings):
    url: str = Field(alias="REDIS_URL")
    ssl: bool = Field(default=True)

class AuthSettings(BaseSettings):
    entra_tenant_id: str = Field(alias="AZURE_ENTRA_TENANT_ID")
    entra_client_id: str = Field(alias="AZURE_ENTRA_CLIENT_ID")

class AppSettings(BaseSettings):
    environment: str = Field(default="development")
    debug: bool = Field(default=False)
    log_level: str = Field(default="INFO")
    cors_origins: list[str] = Field(default=["http://localhost:3000"])

class Settings(BaseSettings):
    azure: AzureSettings = AzureSettings()
    database: DatabaseSettings = DatabaseSettings()
    neo4j: Neo4jSettings = Neo4jSettings()
    redis: RedisSettings = RedisSettings()
    auth: AuthSettings = AuthSettings()
    app: AppSettings = AppSettings()

settings = Settings()
```

### Required Environment Variables

| Variable | Description | Example |
|---|---|---|
| `AZURE_OPENAI_ENDPOINT` | Azure OpenAI endpoint URL | `https://xxx.openai.azure.com/` |
| `AZURE_OPENAI_API_KEY` | Azure OpenAI API key | `sk-...` |
| `AZURE_OPENAI_DEPLOYMENT_GPT` | Primary GPT model deployment | `gpt-5.5` |
| `AZURE_OPENAI_DEPLOYMENT_GPT_BATCH` | Global Batch deployment | `gpt-5.1-batch` |
| `DATABASE_URL` | PostgreSQL connection string | `postgresql+asyncpg://...` |
| `NEO4J_URI` | Neo4j Bolt endpoint | `neo4j+s://xxx.neo4j.io` |
| `NEO4J_PASSWORD` | Neo4j password | `...` |
| `REDIS_URL` | Redis connection URL | `rediss://...` |
| `AZURE_STORAGE_CONNECTION_STRING` | Azure Blob connection string | `DefaultEndpointsProtocol=...` |
| `AZURE_ENTRA_TENANT_ID` | Microsoft Entra ID tenant | `xxxxxxxx-xxxx-...` |
| `AZURE_ENTRA_CLIENT_ID` | Entra application client ID | `xxxxxxxx-xxxx-...` |
| `CELERY_BROKER_URL` | Celery broker (Redis) | `rediss://...` |


---

## 4. API Layer — FastAPI Routes

The API layer consists of 17 route modules organized under `api/routes/`. Route handlers remain thin, delegating business logic to the service layer.

### Route Module Summary

| Module | Prefix | Auth | Description |
|---|---|---|---|
| `health_routes.py` | `/health` | No | Liveness and readiness probes |
| `auth_routes.py` | `/auth` | No | Entra ID login/callback flows |
| `media_routes.py` | `/media` | Yes | Media CRUD with ownership checks |
| `upload_routes.py` | `/upload` | Yes | Multipart file upload |
| `chat_routes.py` | `/chat` | Yes | Conversations and agent sessions |
| `search_routes.py` | `/search` | Yes | Hybrid search endpoints |
| `structure_routes.py` | `/structure` | Yes | Scene/chapter generation |
| `highlight_routes.py` | `/highlights` | Yes | Video highlight management |
| `graph_routes.py` | `/graph` | Yes | Knowledge graph queries |
| `memory_routes.py` | `/memory` | Yes | User memory management |
| `task_routes.py` | `/tasks` | Yes | Async task status polling |
| `user_routes.py` | `/users` | Yes | User profile operations |
| `admin_routes.py` | `/admin` | Yes (admin) | Administrative operations |
| `websocket_routes.py` | `/ws` | Yes (token) | Real-time WebSocket streams |
| `a2a_agent_cards.py` | `/a2a` | No | A2A agent card discovery |
| `a2a_message_routes.py` | `/a2a` | Varies | A2A message exchange |
| `a2a_task_routes.py` | `/a2a` | Varies | A2A task lifecycle |

### Route Pattern Example

```python
from fastapi import APIRouter, Depends, HTTPException
from typing import Annotated
from api.dependencies import get_current_user, get_media_service
from models.schemas import MediaResponse, MediaUpdateRequest

router = APIRouter(prefix="/media", tags=["Media"])

@router.get("/{media_id}", response_model=MediaResponse)
async def get_media(
    media_id: str,
    current_user: Annotated[dict, Depends(get_current_user)],
    media_service=Depends(get_media_service),
) -> MediaResponse:
    """ Retrieve media metadata by ID with ownership verification."""
    media = await media_service.get_media(media_id, current_user["user_id"])
    if not media:
        raise HTTPException(status_code=404, detail="Media not found")
    return media

@router.put("/{media_id}", response_model=MediaResponse)
async def update_media(
    media_id: str,
    request: MediaUpdateRequest,
    current_user: Annotated[dict, Depends(get_current_user)],
    media_service=Depends(get_media_service),
) -> MediaResponse:
    """ Update media metadata."""
    return await media_service.update_media(
        media_id, request, current_user["user_id"]
    )
```

### Dependency Injection

Dependencies are defined in `api/dependencies.py` and shared across routes:

```python
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from services.entra_auth_service import EntraAuthService

security = HTTPBearer()

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> dict:
    """ Validate Entra ID token and return user claims."""
    auth_service = EntraAuthService()
    user = await auth_service.validate_token(credentials.credentials)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )
    return user

def get_media_service():
    from services.media_service import get_media_service
    return get_media_service()

def get_chat_service():
    from services.chat_service import get_chat_service
    return get_chat_service()
```

### WebSocket Authentication

WebSocket connections use token-based auth via query parameters:

```python
@router.websocket("/ws/{session_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    session_id: str,
    token: str = Query(...),
):
    auth_service = EntraAuthService()
    user = await auth_service.validate_token(token)
    if not user:
        await websocket.close(code=4001, reason="Unauthorized")
        return

    await websocket.accept()
    # Stream agent responses...
```


---

## 5. Agent System — LangGraph

The conversational AI agent is built with LangGraph, providing a stateful, multi-tool workflow for video analysis and Q&A.

### Architecture

```
                    ┌─────────────┐
                    │   START     │
                    └──────┬──────┘
                           │
                    ┌──────▼──────┐
                    │  chat_node  │ ◄── System prompt + context
                    └──────┬──────┘
                           │
                    ┌──────▼──────┐
               ┌────┤  should_    ├────┐
               │    │  continue?  │    │
               │    └─────────────┘    │
               │                       │
        ┌──────▼──────┐         ┌──────▼──────┐
        │  tool_node  │         │    END      │
        │ (execute)   │         └─────────────┘
        └──────┬──────┘
               │
               └──────► back to chat_node
```

### State Schema

```python
from typing import Annotated, TypedDict
from langgraph.graph.message import add_messages

class AgentState(TypedDict):
    messages: Annotated[list, add_messages]
    media_id: str | None
    user_id: str
    session_id: str
    context: dict
    tool_results: list[dict]
    iteration_count: int
```

### Graph Definition

```python
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

def create_agent_graph(tools: list, checkpointer=None):
    workflow = StateGraph(AgentState)

    workflow.add_node("chat", chat_node)
    workflow.add_node("tools", ToolNode(tools))

    workflow.set_entry_point("chat")
    workflow.add_conditional_edges(
        "chat",
        should_continue,
        {"continue": "tools", "end": END},
    )
    workflow.add_edge("tools", "chat")

    return workflow.compile(checkpointer=checkpointer)
```

### Tool Modules (18 tools across 5 modules)

| Module | Tools | Description |
|---|---|---|
| `search_tools.py` | `search_video`, `find_entity`, `get_transcript`, `describe_scene` | Content search and scene description |
| `context_tools.py` | `list_chapters`, `get_video_info`, `get_summary`, `get_scene_context`, `get_community_overview` | Context retrieval and video overview |
| `analysis_tools.py` | `get_related_content`, `get_entity_timeline`, `compare_moments` | Analysis and temporal comparison |
| `highlight_tools.py` | `find_highlights` | Highlight detection |
| `multi_video_tools.py` | `search_across_videos`, `compare_videos`, `find_common_entities`, `get_library_overview` | Cross-video analysis |

### Tool Implementation Pattern

```python
from langchain_core.tools import tool

@tool
async def search_transcript(
    media_id: str,
    query: str,
    max_results: int = 10,
) -> dict:
    """ Search video transcript for relevant segments.

    Args:
        media_id: The video identifier.
        query: Natural language search query.
        max_results: Maximum number of results to return.

    Returns:
        Dictionary with 'results' list and 'count'.
    """
    try:
        search_service = get_search_service()
        results = await search_service.search_transcript(
            media_id=media_id,
            query=query,
            limit=max_results,
        )
        return {
            "results": [r.model_dump() for r in results],
            "count": len(results),
        }
    except Exception as e:
        return {"error": str(e), "results": [], "count": 0}
```

### Chat Node with Context Injection

```python
from langchain_openai import AzureChatOpenAI
from core.config import settings

async def chat_node(state: AgentState) -> dict:
    """ Process user message with context-enriched LLM call."""
    llm = AzureChatOpenAI(
        azure_endpoint=settings.azure.openai_endpoint,
        azure_deployment=settings.azure.openai_deployment,
        api_version="2024-12-01-preview",
        temperature=0.1,
    )

    llm_with_tools = llm.bind_tools(tools)

    # Inject video context into system prompt
    system_prompt = build_system_prompt(
        media_id=state.get("media_id"),
        context=state.get("context", {}),
    )

    messages = [SystemMessage(content=system_prompt)] + state["messages"]
    response = await llm_with_tools.ainvoke(messages)

    return {"messages": [response]}
```

### Token Budget Management

```python
class TokenBudgetManager:
    """ Manages token allocation across agent interactions."""

    def __init__(self, max_tokens: int = 128000):
        self.max_tokens = max_tokens
        self.reserved_output = 4096
        self.reserved_tools = 8000

    @property
    def available_context(self) -> int:
        return self.max_tokens - self.reserved_output - self.reserved_tools

    def trim_messages(self, messages: list, system_tokens: int) -> list:
        """ Trim oldest messages to fit within budget."""
        budget = self.available_context - system_tokens
        trimmed = []
        total = 0
        for msg in reversed(messages):
            tokens = self.count_tokens(msg)
            if total + tokens > budget:
                break
            trimmed.insert(0, msg)
            total += tokens
        return trimmed
```

---

## 6. Service Layer

The service layer contains 51 files (41 root-level + 10 in the `graph/` submodule) implementing all business logic. Route handlers delegate to services; services are never imported by routes directly but through dependency providers.

### Service Initialization Pattern

Services use lazy initialization singletons:

```python
_service_instance: ChatService | None = None

def get_chat_service() -> ChatService:
    """ Get or create the ChatService singleton."""
    global _service_instance
    if _service_instance is None:
        _service_instance = ChatService()
    return _service_instance
```

### Root Service Files (41 files)

| Service | File | Description |
|---|---|---|
| ChatService | `chat_service.py` | RAG chat with video context |
| StructureService | `structure_service.py` | Scene/chapter generation |
| GraphSearchService | `graph_search_service.py` | Hybrid graph+vector search |
| MediaService | `media_service.py` | Media lifecycle (CRUD, status) |
| EmbeddingService | `embedding_service.py` | Vector embedding generation |
| TranscriptionService | `transcription_service.py` | Whisper transcription |
| EntraAuthService | `entra_auth_service.py` | Microsoft Entra ID auth |
| FoundryMemoryService | `foundry_memory_service.py` | Foundry Memory Store |
| ToolArtifactService | `tool_artifact_service.py` | Artifact storage (Redis + Blob + PG) |
| CacheService | `cache_service.py` | Multi-layer Redis caching |
| HighlightService | `highlight_service.py` | Video highlight management |
| SceneDetectionService | `scene_detection_service.py` | Visual scene boundary detection |
| ThumbnailService | `thumbnail_service.py` | Thumbnail generation |
| StorageService | `storage_service.py` | Azure Blob operations |
| TaskService | `task_service.py` | Async task tracking |
| UserService | `user_service.py` | User profile management |
| AdminService | `admin_service.py` | Admin operations |
| WebSocketService | `websocket_service.py` | Real-time communication |
| NotificationService | `notification_service.py` | User notifications |
| A2AService | `a2a_service.py` | A2A protocol handling |
| BatchService | `batch_service.py` | Batch processing |
| ExportService | `export_service.py` | Data export operations |
| DatabaseService | `database_service.py` | Database session management |
| HealthService | `health_service.py` | Health check aggregation |
| MetricsService | `metrics_service.py` | Application metrics |

> **Note**: This is a representative listing. See the `services/` directory for the complete set of 41 root-level files.

### Graph Submodule (10 files)

The `services/graph/` directory contains specialized Neo4j services:

| File | Description |
|---|---|
| `base_graph_service.py` | Base class with Neo4j driver management |
| `entity_graph_service.py` | Entity node CRUD operations |
| `relationship_service.py` | Relationship creation and traversal |
| `query_builder.py` | Dynamic Cypher query construction |
| `graph_analytics_service.py` | Graph analytics (centrality, communities) |
| `graph_import_service.py` | Bulk graph data import |
| `graph_export_service.py` | Graph data export |
| `graph_visualization_service.py` | Graph layout data for frontend |
| `graph_cache_service.py` | Graph query result caching |
| `graph_schema_service.py` | Schema management and validation |

### Key Service Examples

#### ChatService

```python
class ChatService:
    """ Manages RAG-enhanced chat sessions with video context."""

    def __init__(self):
        self.agent = create_agent_graph(tools=get_all_tools())
        self.memory = get_foundry_memory_service()
        self.cache = get_cache_service()

    async def chat(
        self,
        session_id: str,
        user_id: str,
        message: str,
        media_id: str | None = None,
    ) -> AsyncGenerator[str, None]:
        """ Process a chat message and stream responses."""
        # Load user memory for context
        memory_context = await self.memory.recall(
            user_id=user_id,
            query=message,
        )

        config = {
            "configurable": {
                "thread_id": session_id,
                "user_id": user_id,
            }
        }

        state = {
            "messages": [HumanMessage(content=message)],
            "media_id": media_id,
            "user_id": user_id,
            "session_id": session_id,
            "context": {"memory": memory_context},
        }

        async for event in self.agent.astream_events(state, config=config):
            if event["event"] == "on_chat_model_stream":
                yield event["data"]["chunk"].content
```

#### StructureService

```python
class StructureService:
    """ Generates scene boundaries and chapter structures for videos."""

    async def generate_scenes(self, media_id: str) -> list[Scene]:
        """ Detect scene boundaries using visual + audio analysis."""
        transcript = await self.transcription_service.get_transcript(media_id)
        visual_scenes = await self.scene_detection.detect(media_id)

        prompt = self._build_scene_prompt(transcript, visual_scenes)
        response = await self.llm.ainvoke(prompt)

        return self._parse_scenes(response)

    async def generate_chapters(
        self, media_id: str, scenes: list[Scene]
    ) -> list[Chapter]:
        """ Group scenes into semantic chapters."""
        prompt = self._build_chapter_prompt(scenes)
        response = await self.llm.ainvoke(prompt)
        return self._parse_chapters(response)
```


---

## 7. Data Models — SQLAlchemy + Pydantic

### SQLAlchemy ORM Models (`models/database.py`)

```python
from sqlalchemy import Column, String, DateTime, ForeignKey, Text, Integer, Enum, Float
from sqlalchemy.dialects.postgresql import JSONB, ARRAY
from sqlalchemy.orm import relationship, DeclarativeBase
from sqlalchemy.sql import func
import enum

class Base(DeclarativeBase):
    pass

class MediaStatus(str, enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"

class Media(Base):
    __tablename__ = "media"

    id = Column(String, primary_key=True)
    user_id = Column(String, nullable=False, index=True)
    title = Column(String, nullable=False)
    description = Column(Text)
    status = Column(Enum(MediaStatus), default=MediaStatus.PENDING)
    duration = Column(Float)
    file_url = Column(String)
    thumbnail_url = Column(String)
    metadata_ = Column("metadata", JSONB, default={})
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    transcripts = relationship("Transcript", back_populates="media")
    scenes = relationship("Scene", back_populates="media")
    highlights = relationship("Highlight", back_populates="media")

class Transcript(Base):
    __tablename__ = "transcripts"

    id = Column(String, primary_key=True)
    media_id = Column(String, ForeignKey("media.id"), nullable=False)
    content = Column(Text, nullable=False)
    segments = Column(JSONB)  # [{start, end, text, confidence}]
    language = Column(String, default="en")
    embedding = Column(ARRAY(Float))  # 3072-dim vector

    media = relationship("Media", back_populates="transcripts")

class Scene(Base):
    __tablename__ = "scenes"

    id = Column(String, primary_key=True)
    media_id = Column(String, ForeignKey("media.id"), nullable=False)
    start_time = Column(Float, nullable=False)
    end_time = Column(Float, nullable=False)
    title = Column(String)
    description = Column(Text)
    thumbnail_url = Column(String)
    embedding = Column(ARRAY(Float))

    media = relationship("Media", back_populates="scenes")

class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id = Column(String, primary_key=True)
    user_id = Column(String, nullable=False, index=True)
    media_id = Column(String, ForeignKey("media.id"))
    title = Column(String)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    messages = relationship("ChatMessage", back_populates="session")

class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(String, primary_key=True)
    session_id = Column(String, ForeignKey("chat_sessions.id"), nullable=False)
    role = Column(String, nullable=False)  # "user" | "assistant"
    content = Column(Text, nullable=False)
    metadata_ = Column("metadata", JSONB, default={})
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    session = relationship("ChatSession", back_populates="messages")

class Highlight(Base):
    __tablename__ = "highlights"

    id = Column(String, primary_key=True)
    media_id = Column(String, ForeignKey("media.id"), nullable=False)
    user_id = Column(String, nullable=False)
    title = Column(String, nullable=False)
    start_time = Column(Float, nullable=False)
    end_time = Column(Float, nullable=False)
    notes = Column(Text)
    tags = Column(ARRAY(String))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    media = relationship("Media", back_populates="highlights")
```

### Pydantic Schemas (`models/schemas.py`)

```python
from pydantic import BaseModel, Field
from datetime import datetime

class MediaResponse(BaseModel):
    id: str
    title: str
    description: str | None = None
    status: str
    duration: float | None = None
    file_url: str | None = None
    thumbnail_url: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}

class MediaCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str | None = None

class MediaUpdateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None

class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=10000)
    media_id: str | None = None
    session_id: str | None = None

class ChatResponse(BaseModel):
    session_id: str
    message: str
    sources: list[dict] = []

class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    media_id: str | None = None
    limit: int = Field(default=10, ge=1, le=100)

class SearchResult(BaseModel):
    content: str
    score: float
    media_id: str
    timestamp: float | None = None
    source_type: str

class HighlightRequest(BaseModel):
    media_id: str
    title: str = Field(min_length=1, max_length=255)
    start_time: float = Field(ge=0)
    end_time: float = Field(ge=0)
    notes: str | None = None
    tags: list[str] = []

class TaskStatusResponse(BaseModel):
    task_id: str
    status: str
    progress: float | None = None
    result: dict | None = None
    error: str | None = None
```

---

## 8. Async Tasks — Celery

Celery remains the default and fallback processing backend. Upload routes no longer call Celery directly; they call `services.video_processing_dispatch_service.VideoProcessingDispatchService`, which selects the backend through centralized settings:

| Setting | Purpose |
|---|---|
| `PROCESSING_BACKEND=celery` | Default path; dispatches `process_video_pipeline` through Celery/Redis |
| `PROCESSING_BACKEND=servicebus` or `databricks` | Pilot path; publishes a durable Service Bus message consumed by the Databricks bridge |
| `SERVICE_BUS_FULLY_QUALIFIED_NAMESPACE` | Required for Service Bus/Databricks dispatch |
| `SERVICE_BUS_MANAGED_IDENTITY_CLIENT_ID` | Pins Service Bus SDK authentication to the intended user-assigned managed identity |
| `DATABRICKS_WORKSPACE_URL`, `DATABRICKS_VIDEO_JOB_ID` | Passed to the bridge/bundle workflow for Databricks job invocation |

The Databricks bridge is intentionally isolated under `backend\functions\video_dispatch_bridge` rather than imported into the FastAPI application. It validates Service Bus payloads, starts Databricks Jobs with `run-now`, projects `running`/`completed`/`failed` outbox events into PostgreSQL, and leaves Celery available as a safe rollback path.

### Celery Configuration (`tasks/celery_app.py`)

```python
from celery import Celery
from core.config import settings

celery_app = Celery(
    "qprisma",
    broker=settings.redis.url,
    backend=settings.redis.url,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_routes={
        "tasks.video_tasks.*": {"queue": "video_processing"},
    },
)
```

### Video Processing Tasks (`tasks/video_tasks.py`)

```python
from tasks.celery_app import celery_app
from services.transcription_service import get_transcription_service
from services.embedding_service import get_embedding_service
from services.scene_detection_service import get_scene_detection_service

@celery_app.task(bind=True, max_retries=3)
def process_video(self, media_id: str, user_id: str):
    """ Full video processing pipeline as a Celery task."""
    try:
        self.update_state(state="PROGRESS", meta={"step": "transcription", "progress": 0.1})

        # Step 1: Transcribe audio
        transcription_service = get_transcription_service()
        transcript = transcription_service.transcribe(media_id)

        self.update_state(state="PROGRESS", meta={"step": "embedding", "progress": 0.4})

        # Step 2: Generate embeddings
        embedding_service = get_embedding_service()
        embedding_service.generate_embeddings(media_id, transcript)

        self.update_state(state="PROGRESS", meta={"step": "scenes", "progress": 0.7})

        # Step 3: Detect scenes
        scene_service = get_scene_detection_service()
        scene_service.detect_scenes(media_id)

        self.update_state(state="PROGRESS", meta={"step": "knowledge_graph", "progress": 0.9})

        # Step 4: Build knowledge graph
        # Entity extraction and graph population
        build_knowledge_graph(media_id, transcript)

        return {"status": "completed", "media_id": media_id}

    except Exception as exc:
        self.retry(exc=exc, countdown=60 * (self.request.retries + 1))
```

### Task Monitoring

```python
from tasks.celery_app import celery_app

async def get_task_status(task_id: str) -> dict:
    """ Check Celery task status and progress."""
    result = celery_app.AsyncResult(task_id)
    response = {
        "task_id": task_id,
        "status": result.status,
    }
    if result.status == "PROGRESS":
        response["progress"] = result.info.get("progress", 0)
        response["step"] = result.info.get("step", "")
    elif result.status == "SUCCESS":
        response["result"] = result.result
    elif result.status == "FAILURE":
        response["error"] = str(result.result)
    return response
```


---

## 9. Video Processing Pipeline

### Pipeline Architecture

```
  Upload          Transcribe        Embed           Scenes          Graph
┌────────┐     ┌────────────┐    ┌──────────┐   ┌──────────┐   ┌──────────┐
│  User  │────►│  Whisper   │───►│ text-emb │──►│  Scene   │──►│  Neo4j   │
│ Upload │     │  (Azure)   │    │ 3-large  │   │  Detect  │   │  Import  │
└────────┘     └────────────┘    └──────────┘   └──────────┘   └──────────┘
     │                                                               │
     ▼                                                               ▼
┌────────┐                                                    ┌──────────┐
│  Blob  │                                                    │  Ready   │
│Storage │                                                    │  for Q&A │
└────────┘                                                    └──────────┘
```

### Processing Steps

| Step | Service | Input | Output |
|---|---|---|---|
| 1. Upload | `StorageService` | Raw video file | Blob URL |
| 2. Transcode | `MediaService` | Blob URL | Normalized video |
| 3. Transcribe | `TranscriptionService` | Audio stream | Timestamped transcript |
| 4. Embed | `EmbeddingService` | Transcript segments | 3072-dim vectors |
| 5. Scenes | `SceneDetectionService` | Video frames + transcript | Scene boundaries |
| 6. Thumbnails | `ThumbnailService` | Video frames | Scene thumbnails |
| 7. Graph | `GraphImportService` | Entities + relations | Neo4j nodes/edges |
| 8. Structure | `StructureService` | Scenes + transcript | Chapters |

### Error Recovery

Each pipeline step implements idempotent retry logic:

```python
@celery_app.task(bind=True, max_retries=3, acks_late=True)
def transcribe_video(self, media_id: str):
    try:
        service = get_transcription_service()
        # Check if already transcribed (idempotent)
        existing = service.get_transcript(media_id)
        if existing:
            return {"status": "already_completed"}

        result = service.transcribe(media_id)
        return {"status": "completed", "segments": len(result.segments)}
    except Exception as exc:
        self.retry(exc=exc, countdown=60 * (2 ** self.request.retries))
```

---

## 10. Knowledge Graph — Neo4j

### Graph Schema

```
(:Video {id, title, duration})
    ├──[:HAS_SCENE]──► (:Scene {id, start, end, title})
    │                      ├──[:MENTIONS]──► (:Entity {name, type})
    │                      └──[:HAS_TOPIC]──► (:Topic {name})
    ├──[:HAS_CHAPTER]──► (:Chapter {id, title, order})
    │                      └──[:CONTAINS]──► (:Scene)
    ├──[:HAS_TRANSCRIPT]──► (:TranscriptSegment {start, end, text})
    └──[:TAGGED_WITH]──► (:Tag {name})

(:Entity)──[:RELATED_TO]──►(:Entity)
(:Entity)──[:APPEARS_IN]──►(:Scene)
```

### Neo4j Service Example

```python
from neo4j import AsyncGraphDatabase
from core.config import settings

class BaseGraphService:
    """ Base service for Neo4j graph operations."""

    def __init__(self):
        self.driver = AsyncGraphDatabase.driver(
            settings.neo4j.uri,
            auth=(settings.neo4j.username, settings.neo4j.password),
        )

    async def execute_query(self, query: str, params: dict = None) -> list:
        """ Execute a Cypher query and return results."""
        async with self.driver.session() as session:
            result = await session.run(query, params or {})
            return [record.data() async for record in result]

    async def close(self):
        await self.driver.close()
```

### Entity Extraction and Graph Population

```python
class EntityGraphService(BaseGraphService):
    """ Manages entity nodes in the knowledge graph."""

    async def create_entities_from_transcript(
        self, media_id: str, transcript: str
    ) -> list[dict]:
        """ Extract entities from transcript and create graph nodes."""
        # Use LLM to extract entities
        entities = await self._extract_entities(transcript)

        query = """
        UNWIND $entities AS entity
        MERGE (e:Entity {name: entity.name})
        SET e.type = entity.type,
            e.description = entity.description
        WITH e
        MATCH (v:Video {id: $media_id})
        MERGE (v)-[:MENTIONS]->(e)
        RETURN e
        """

        return await self.execute_query(query, {
            "media_id": media_id,
            "entities": entities,
        })

    async def find_related_entities(
        self, entity_name: str, depth: int = 2
    ) -> list[dict]:
        """ Find entities related to the given entity within N hops."""
        query = """
        MATCH (e:Entity {name: $name})-[:RELATED_TO*1..$depth]-(related)
        RETURN DISTINCT related.name AS name,
               related.type AS type,
               length(shortestPath((e)-[:RELATED_TO*]-(related))) AS distance
        ORDER BY distance
        """

        return await self.execute_query(query, {
            "name": entity_name,
            "depth": depth,
        })
```

---

## 11. Hybrid Search System

The search system combines Neo4j vector similarity, fulltext indexing, graph connectivity scoring, and temporal proximity into a unified pipeline with a 25-second time budget.

### Search Architecture

```
                    ┌──────────────┐
                    │ User Query   │
                    └──────┬───────┘
                           │
                    ┌──────▼───────┐
                    │ Intent       │
                    │ Classification│
                    └──────┬───────┘
                           │
                    ┌──────▼───────┐
                    │ Azure OpenAI │
                    │ Embedding    │
                    └──────┬───────┘
                           │
              ┌────────────┼────────────┐
              │                         │
       ┌──────▼──────┐          ┌──────▼──────┐
       │ Neo4j Vector │          │ Neo4j       │
       │ Index Search │          │ Fulltext    │
       │ (per type)   │          │ Search      │
       └──────┬──────┘          └──────┬──────┘
              │                         │
              └────────┬────────────────┘
                       │
                ┌──────▼───────┐
                │  Candidate   │
                │  Merge & Cap │
                └──────┬───────┘
                       │
              ┌────────┼────────┐
              │                 │
       ┌──────▼──────┐  ┌──────▼──────┐
       │ Graph       │  │ Temporal    │
       │ Connectivity│  │ Proximity   │
       │ Scoring     │  │ Scoring     │
       └──────┬──────┘  └──────┬──────┘
              │                 │
              └────────┬────────┘
                       │
                ┌──────▼───────┐
                │ Intent-      │
                │ Weighted     │
                │ Reranking    │
                └──────┬───────┘
                       │
                ┌──────▼───────┐
                │   Results    │
                └──────────────┘
```

### Five Scoring Signals

Each search candidate is scored across five independent signals, combined with intent-adaptive weights:

| Signal | Default Weight | Source |
|---|---|---|
| Vector similarity | 0.35 | Neo4j vector index (text-embedding-3-large, 3072-dim) |
| Fulltext relevance | 0.25 | Neo4j fulltext index (BM25-style) |
| Graph connectivity | 0.25 | Path distance to video, entity co-occurrence |
| Temporal proximity | 0.15 | Distance from query timestamp anchor |
| Co-occurrence bonus | +0.1 | Entities appearing in same scene/frame |

### Intent-Adaptive Weight Profiles

The pipeline classifies query intent and selects from 7 weight profiles:

| Profile | Vector | Fulltext | Graph | Temporal | When used |
|---|---|---|---|---|---|
| `time-based` | 0.20 | 0.15 | 0.20 | 0.45 | "What happens at 15:00?" |
| `object` | 0.40 | 0.20 | 0.30 | 0.10 | "Find the laptop" |
| `person` | 0.35 | 0.20 | 0.35 | 0.10 | "Show me Satya Nadella" |
| `text` | 0.25 | 0.45 | 0.15 | 0.15 | "Search for Azure" |
| `action` | 0.35 | 0.25 | 0.25 | 0.15 | "When does the demo start?" |
| `scene` | 0.40 | 0.15 | 0.30 | 0.15 | "Describe the stage" |
| `event` | 0.30 | 0.25 | 0.25 | 0.20 | "What was announced?" |

### Pipeline Budget System

The pipeline enforces a **25-second end-to-end deadline** (`_PIPELINE_BUDGET_S = 25.0`). Each stage receives the remaining budget as its timeout:

```python
deadline = time.monotonic() + _PIPELINE_BUDGET_S

# Stage 1: Vector search (per node type)
remaining = deadline - time.monotonic()
vector_results = vector_search(..., timeout_s=remaining)

# Stage 2: Fulltext search
remaining = deadline - time.monotonic()
fulltext_results = fulltext_search(..., timeout_s=remaining)

# Stage 3: Graph expansion (skipped if <3s remaining)
remaining = deadline - time.monotonic()
if remaining > 3.0:
    graph_scores = calculate_graph_scores(..., timeout_s=remaining)
```

### Neo4j Query Timeouts

All Neo4j queries use `neo4j.Query` with a timeout parameter (not the `session.run(timeout=...)` kwarg, which is treated as a Cypher parameter):

```python
from neo4j import Query

q = Query(cypher_text, timeout=remaining_s) if remaining_s else cypher_text
session.run(q, **params)
```

This pattern is applied at all 9 `session.run()` sites across `graph_search_queries.py` and `graph_search_scoring.py`.

### Candidate Capping

When accumulated candidates exceed `limit × 6`, the pipeline trims to `limit × 4` using a blended provisional score:

```python
provisional = 0.5 * candidate["vector_score"] + 0.5 * candidate["fulltext_score"]
```

Capping happens **after** all node types have merged, not mid-loop. This preserves strong fulltext-only matches (vector_score=0) that would be lost by sorting on vector score alone.

### Adaptive Graph Expansion

Graph connectivity scoring (`_calculate_graph_scores`) reduces `expansion_hops` from 2 → 1 when the candidate set exceeds 50 items, preventing combinatorial explosion in the Neo4j path-finding queries.

### Keyword Fallback

Agent tools (`search_video`, `find_entity`) wrap `hybrid_search()` in a 30-second `asyncio.wait_for()`. On timeout, a keyword-based Cypher fallback executes a direct `CONTAINS` search against scene descriptions and entity names, returning partial results rather than nothing.

### GraphSearchService

```python
class GraphSearchService:
    """Hybrid search combining vector, fulltext, graph, and temporal scoring."""

    async def hybrid_search(
        self,
        query: str,
        media_id: str | None = None,
        limit: int = 10,
    ) -> list[SearchResult]:
        """Execute hybrid search with 25s pipeline budget."""
        # 1. Check Redis cache
        # 2. Generate query embedding (Azure OpenAI)
        # 3. Classify intent → select weight profile
        # 4. Run _sync_search_pipeline via asyncio.to_thread()
        #    - Vector search per node type (Frame, Entity, AudioSegment)
        #    - Fulltext search with score merging
        #    - Candidate capping
        #    - Graph connectivity scoring (adaptive hops)
        #    - Temporal proximity scoring
        #    - Intent-weighted reranking
        # 5. Cache results (5-minute TTL)
        ...
```

---

## 12. Memory System — Layered State and Foundry Memory Capability

QPrisma uses a layered memory approach. The active runtime path is built around graph-state memory plus persisted tool artifacts, while Azure AI Foundry Memory Store exists as an available long-term memory capability in `services/foundry_memory_service.py`.

### Architecture

```
┌─────────────────┐    ┌────────────────────┐    ┌────────────────────────────┐
│ LangGraph Agent │───►│ local memory state │───►│ ToolArtifactService        │
│ runtime         │    │ + artifact refs    │    │ Redis + Blob + Postgres    │
└─────────────────┘    └────────────────────┘    └────────────────────────────┘
         │
         │ optional long-term semantic memory capability
         ▼
┌────────────────────────┐     ┌──────────────┐
│  FoundryMemoryService  │────►│  Azure AI    │
│  ensure/update/search  │     │  Foundry     │
└────────────────────────┘     │  Memory      │
                               └──────────────┘
```

### Foundry Memory Service

```python
service = get_foundry_memory_service()

if service.enabled:
    await service.ensure_memory_store()
    await service.update_memories(
        scope="tenant_object_id",
        messages=[{"role": "user", "content": "Show me the video about supply chain risk"}],
    )
    results = await service.search_memories(
        scope="tenant_object_id",
        query="supply chain preferences",
    )
```

The service exposes three key operations:

- `ensure_memory_store()` - idempotently create or fetch the store definition
- `update_memories()` - extract memory items from one or more conversation messages
- `search_memories()` - retrieve relevant memories for a user scope

### Memory Integration in Agent

The agent uses a layered memory approach:

1. **Checkpointer** — Thread-scoped operational state for resume/retry continuity
2. **Artifact storage** — Full tool payloads via `ToolArtifactService` (Redis + Blob + Postgres metadata)
3. **Foundry Memory Store** — Available long-term semantic memory capability for future automatic integration

In the current runtime path, before each model call the system:
1. Collects hybrid candidates from local `memory_context` plus `artifact_refs`
2. Reranks by lexical overlap, semantic signal, and recency
3. Applies dynamic context budget allocation
4. Selectively rehydrates artifacts only for detail-heavy queries

`FoundryMemoryService` is present in the codebase, but automatic prompt-time retrieval from Foundry Memory Store is not wired into the main LangGraph node flow yet. `docs/MEMORY_ARCHITECTURE.md` is the authoritative reference for that status.


---

## 13. Caching Layer — Redis Enterprise

### Cache Strategy

QPrisma uses multi-layer caching with Redis Enterprise:

| Layer | TTL | Use Case |
|---|---|---|
| Hot cache | 5 min | Search results, embeddings |
| Warm cache | 30 min | Graph queries, structured data |
| Session cache | 24 h | User sessions, preferences |
| Artifact cache | 7 d | Tool artifacts, large payloads |

### CacheService

```python
import redis.asyncio as redis
from core.config import settings

class CacheService:
    """ Multi-layer Redis caching service."""

    def __init__(self):
        self.client = redis.from_url(
            settings.redis.url,
            encoding="utf-8",
            decode_responses=True,
            ssl=settings.redis.ssl,
        )

    async def get(self, key: str) -> dict | None:
        """ Retrieve cached value by key."""
        import json
        value = await self.client.get(key)
        if value:
            return json.loads(value)
        return None

    async def set(self, key: str, value: any, ttl: int = 300) -> None:
        """ Set cache value with TTL in seconds."""
        import json
        await self.client.setex(key, ttl, json.dumps(value, default=str))

    async def delete(self, key: str) -> None:
        """ Delete a cached value."""
        await self.client.delete(key)

    async def invalidate_pattern(self, pattern: str) -> int:
        """ Delete all keys matching a pattern."""
        keys = []
        async for key in self.client.scan_iter(match=pattern):
            keys.append(key)
        if keys:
            return await self.client.delete(*keys)
        return 0
```

### Cache Key Conventions

```
search:{query_hash}:{media_id}:{limit}     # Search results
embed:{text_hash}                           # Embedding vectors
graph:{query_hash}                          # Graph query results
user:{user_id}:profile                      # User profile
session:{session_id}:state                  # Session state
artifact:{artifact_id}                      # Tool artifacts
media:{media_id}:metadata                   # Media metadata
```

---

## 14. A2A Protocol — Agent-to-Agent

QPrisma implements Google's Agent-to-Agent (A2A) protocol for interoperability with external agent systems.

### A2A Architecture

```
┌──────────────┐     ┌─────────────────┐     ┌──────────────┐
│  External    │     │    QPrisma      │     │   QPrisma    │
│  Agent       │────►│  A2A Endpoints  │────►│   Agent      │
│              │◄────│  (3 routes)     │◄────│  (LangGraph) │
└──────────────┘     └─────────────────┘     └──────────────┘
```

### Route Modules

| Module | Endpoints | Description |
|---|---|---|
| `a2a_agent_cards.py` | `GET /.well-known/agent-card.json` | Agent card discovery |
| `a2a_message_routes.py` | `POST /a2a/message:send`, `POST /a2a/message:stream` | Message exchange |
| `a2a_task_routes.py` | `GET /a2a/tasks/{id}`, `POST /a2a/tasks/{id}:cancel`, `POST /a2a/tasks/{id}:subscribe` | Task lifecycle management |

### Agent Card

```python
@router.get("/.well-known/agent-card.json", response_model=AgentCard)
async def get_agent_card():
    """Agent Card discovery endpoint."""
    return get_video_agent_card()
```

### A2A Message Handling

```python
# POST /a2a/message:send  — synchronous message exchange
# POST /a2a/message:stream — message exchange with SSE streaming
```

---

## 15. Authentication and Authorization

### Microsoft Entra ID (Primary)

QPrisma uses Microsoft Entra ID (formerly Azure AD) as its primary authentication provider via OIDC.

```
┌──────────┐     ┌──────────────┐     ┌──────────────┐
│  Client  │────►│  Entra ID    │────►│   QPrisma    │
│  (SPA)   │     │  (OIDC)      │     │   Backend    │
│          │◄────│              │     │              │
└──────────┘     └──────────────┘     └──────────────┘
     │                                      │
     │         Bearer Token                 │
     └──────────────────────────────────────┘
```

### Auth Flow

1. Frontend redirects to Entra ID login page
2. User authenticates with Microsoft credentials
3. Entra ID returns an ID token + access token
4. Frontend sends access token as `Authorization: Bearer <token>`
5. Backend validates token via Entra ID JWKS endpoint
6. User claims extracted and injected via `get_current_user` dependency

### EntraAuthService

```python
from msal import ConfidentialClientApplication
import httpx
from core.config import settings

class EntraAuthService:
    """ Microsoft Entra ID authentication service."""

    JWKS_URL = "https://login.microsoftonline.com/{tenant}/discovery/v2.0/keys"
    ISSUER = "https://login.microsoftonline.com/{tenant}/v2.0"

    def __init__(self):
        self.tenant_id = settings.auth.entra_tenant_id
        self.client_id = settings.auth.entra_client_id
        self._jwks_cache: dict | None = None

    async def validate_token(self, token: str) -> dict | None:
        """ Validate an Entra ID access token and return user claims."""
        try:
            jwks = await self._get_jwks()
            claims = self._decode_and_verify(token, jwks)

            return {
                "user_id": claims["oid"],
                "email": claims.get("preferred_username"),
                "name": claims.get("name"),
                "roles": claims.get("roles", []),
            }
        except Exception:
            return None

    async def _get_jwks(self) -> dict:
        """ Fetch and cache JWKS from Entra ID."""
        if self._jwks_cache:
            return self._jwks_cache

        url = self.JWKS_URL.format(tenant=self.tenant_id)
        async with httpx.AsyncClient() as client:
            response = await client.get(url)
            self._jwks_cache = response.json()
            return self._jwks_cache
```

### Role-Based Access Control

```python
from functools import wraps
from fastapi import HTTPException, status

def require_role(role: str):
    """ Dependency that checks if user has the required role."""
    async def role_checker(
        current_user: Annotated[dict, Depends(get_current_user)]
    ):
        if role not in current_user.get("roles", []):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{role}' required",
            )
        return current_user
    return role_checker

# Usage in routes:
@router.delete("/{media_id}")
async def delete_media(
    media_id: str,
    admin_user: Annotated[dict, Depends(require_role("admin"))],
    media_service=Depends(get_media_service),
):
    return await media_service.delete_media(media_id)
```

> **Note**: A legacy JWT-based auth module (`auth_service.py`) exists in the codebase but is disabled in production. All production authentication routes through Entra ID.


---

## 16. Observability and Monitoring

### Logging

QPrisma uses structured logging throughout:

```python
from agent.utils.observability import get_logger, Metrics

logger = get_logger(__name__)

# Structured log with context
logger.info(
    "Video processing started",
    extra={
        "media_id": media_id,
        "user_id": user_id,
        "step": "transcription",
    },
)
```

> **Important**: Never use `print()` in runtime paths. Always use `get_logger()` from `agent.utils.observability`.

### Metrics Collection

```python
class Metrics:
    """ Application metrics using Azure Monitor / Application Insights."""

    @staticmethod
    def track_event(name: str, properties: dict = None):
        """ Track a custom event."""
        # Emitted to Application Insights
        pass

    @staticmethod
    def track_duration(name: str, duration_ms: float, properties: dict = None):
        """ Track operation duration."""
        pass

    @staticmethod
    def track_dependency(
        name: str, target: str, duration_ms: float, success: bool
    ):
        """ Track an external dependency call."""
        pass
```

### Health Checks

```python
@router.get("/health")
async def health_check():
    """ Comprehensive health check for all services."""
    checks = {
        "postgresql": await check_postgres(),
        "neo4j": await check_neo4j(),
        "redis": await check_redis(),
        "azure_openai": await check_openai(),
        "azure_storage": await check_storage(),
    }

    all_healthy = all(c["status"] == "healthy" for c in checks.values())

    return {
        "status": "healthy" if all_healthy else "degraded",
        "checks": checks,
        "version": settings.app.version,
        "timestamp": datetime.now(UTC).isoformat(),
    }

@router.get("/health/liveness")
async def liveness():
    """ Simple liveness probe for container orchestrator."""
    return {"status": "alive"}

@router.get("/health/readiness")
async def readiness():
    """ Readiness probe — checks if the app can serve requests."""
    try:
        await check_postgres()
        return {"status": "ready"}
    except Exception:
        raise HTTPException(status_code=503, detail="Not ready")
```

### Agent Observability

```python
class AgentTracer:
    """ Traces agent execution for debugging and monitoring."""

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.traces = []

    def on_tool_start(self, tool_name: str, inputs: dict):
        self.traces.append({
            "event": "tool_start",
            "tool": tool_name,
            "timestamp": datetime.now(UTC).isoformat(),
        })
        Metrics.track_event("agent_tool_start", {"tool": tool_name})

    def on_tool_end(self, tool_name: str, output: dict, duration_ms: float):
        self.traces.append({
            "event": "tool_end",
            "tool": tool_name,
            "duration_ms": duration_ms,
            "has_error": "error" in output,
        })
        Metrics.track_duration("agent_tool", duration_ms, {"tool": tool_name})

    def on_llm_call(self, model: str, tokens_used: int, duration_ms: float):
        Metrics.track_dependency(
            "azure_openai", model, duration_ms, success=True
        )
```

---

## 17. Architecture Patterns and Conventions

### 1. Thin Routes, Thick Services

Route handlers only handle HTTP concerns (validation, status codes, auth). Business logic lives in `services/`.

```python
# ✅ Correct — thin route
@router.post("/media")
async def create_media(
    request: MediaCreateRequest,
    current_user: Annotated[dict, Depends(get_current_user)],
    media_service=Depends(get_media_service),
):
    return await media_service.create(request, current_user["user_id"])

# ❌ Incorrect — business logic in route
@router.post("/media")
async def create_media(request: MediaCreateRequest, db=Depends(get_db)):
    media = Media(title=request.title, user_id=get_user_id())
    db.add(media)
    await db.commit()
    await notify_user(media)
    return media
```

### 2. Centralized Configuration

All config through `core.config.settings`:

```python
# ✅ Correct
from core.config import settings
endpoint = settings.azure.openai_endpoint

# ❌ Incorrect
import os
endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
```

### 3. Error Handling in Agent Tools

Agent tools return structured error payloads instead of raising exceptions:

```python
# ✅ Correct — return error dict
@tool
async def my_tool(query: str) -> dict:
    try:
        result = await do_something(query)
        return {"results": result, "count": len(result)}
    except Exception as e:
        return {"error": str(e), "results": [], "count": 0}

# ❌ Incorrect — raising exception
@tool
async def my_tool(query: str) -> dict:
    result = await do_something(query)  # May throw
    return {"results": result}
```

### 4. Async-First Pattern

All I/O operations use async:

```python
# ✅ Correct
async def fetch_media(media_id: str) -> Media:
    async with get_session() as session:
        result = await session.execute(
            select(Media).where(Media.id == media_id)
        )
        return result.scalar_one_or_none()

# ❌ Incorrect — blocking I/O
def fetch_media(media_id: str) -> Media:
    with get_session() as session:
        return session.query(Media).get(media_id)
```

### 5. Lazy Singleton Services

Services use the lazy initialization singleton pattern:

```python
_instance: MyService | None = None

def get_my_service() -> MyService:
    global _instance
    if _instance is None:
        _instance = MyService()
    return _instance
```

### 6. Pydantic Models for API Boundaries

All request/response data uses Pydantic models:

```python
class MediaCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str | None = None

class MediaResponse(BaseModel):
    id: str
    title: str
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}
```

### 7. UTC Timestamps

Always use timezone-aware UTC:

```python
from datetime import datetime, UTC

# ✅ Correct
now = datetime.now(UTC)

# ❌ Incorrect
now = datetime.utcnow()
```

### 8. Dependency Injection

Use FastAPI's `Depends()` system for service injection:

```python
from api.dependencies import get_current_user, get_media_service

@router.get("/media/{media_id}")
async def get_media(
    media_id: str,
    current_user: Annotated[dict, Depends(get_current_user)],
    media_service=Depends(get_media_service),
):
    return await media_service.get(media_id, current_user["user_id"])
```

---

## 18. Dependencies and Versions

### Core Dependencies

| Package | Version | Purpose |
|---|---|---|
| `fastapi` | ^0.115.x | Web framework |
| `uvicorn` | ^0.34.x | ASGI server |
| `pydantic` | ^2.x | Data validation |
| `pydantic-settings` | ^2.x | Configuration management |
| `sqlalchemy` | ^2.x | ORM / database toolkit |
| `asyncpg` | ^0.30.x | Async PostgreSQL driver |
| `alembic` | ^1.x | Database migrations |

### AI/ML Dependencies

| Package | Version | Purpose |
|---|---|---|
| `langgraph` | ^0.3.x | Agent workflow framework |
| `langchain-openai` | ^0.3.x | Azure OpenAI integration |
| `langchain-core` | ^0.3.x | Core LangChain abstractions |
| `openai` | ^1.x | OpenAI Python SDK |
| `tiktoken` | ^0.8.x | Token counting |

### Infrastructure Dependencies

| Package | Version | Purpose |
|---|---|---|
| `celery` | ^5.4.x | Distributed task queue |
| `redis` | ^5.x | Redis client (async) |
| `neo4j` | ^5.x | Neo4j driver |
| `azure-storage-blob` | ^12.x | Azure Blob Storage |
| `azure-identity` | ^1.x | Azure credential management |
| `httpx` | ^0.28.x | Async HTTP client |
| `msal` | ^1.x | Microsoft auth library |

### Development Dependencies

| Package | Version | Purpose |
|---|---|---|
| `pytest` | ^8.x | Test framework |
| `pytest-asyncio` | ^0.24.x | Async test support |
| `pytest-cov` | ^6.x | Coverage reporting |
| `ruff` | ^0.8.x | Linter + formatter |
| `mypy` | ^1.x | Static type checker |
| `pre-commit` | ^4.x | Git hooks |

---

## 19. Flow Diagrams

### Complete Request Flow

```
Client Request
      │
      ▼
┌─────────────┐
│   FastAPI    │
│   Router     │──── Auth Middleware (Entra ID token validation)
└──────┬──────┘
       │
       ▼
┌─────────────┐
│ Dependency   │──── get_current_user, get_*_service
│ Injection    │
└──────┬──────┘
       │
       ▼
┌─────────────┐
│  Service     │──── Business logic, validation
│  Layer       │
└──────┬──────┘
       │
       ├──────► PostgreSQL (data persistence)
       ├──────► Neo4j (knowledge graph)
       ├──────► Redis (caching)
       ├──────► Azure Blob (file storage)
       └──────► Azure OpenAI (LLM calls)
```

### Chat Flow (Detailed)

```
User Message
      │
      ▼
┌──────────────┐
│  chat_routes │
│  .py         │
└──────┬───────┘
       │
       ▼
┌──────────────┐     ┌──────────────┐
│  ChatService │────►│ Foundry      │
│              │     │ Memory       │── recall relevant memories
└──────┬───────┘     └──────────────┘
       │
       ▼
┌──────────────┐
│  LangGraph   │
│  Agent       │
└──────┬───────┘
       │
       ├── Tool Call ──► search_transcript ──► EmbeddingService + pgvector
       ├── Tool Call ──► search_knowledge_graph ──► Neo4j
       ├── Tool Call ──► analyze_scene ──► GPT-4o
       │
       ▼
┌──────────────┐
│  Stream      │──── SSE / WebSocket to client
│  Response    │
└──────────────┘
       │
       ▼
┌──────────────┐
│  Memorize    │──── Store conversation insights
│  (async)     │
└──────────────┘
```

### Video Upload Flow

```
File Upload
      │
      ▼
┌──────────────┐
│ upload_routes│
│ .py          │
└──────┬───────┘
       │
       ▼
┌──────────────┐
│ StorageService│──── Upload to Azure Blob
└──────┬───────┘
       │
       ▼
┌──────────────┐
│ MediaService │──── Create DB record (status: PENDING)
└──────┬───────┘
       │
       ▼
┌──────────────┐
│ Celery Task  │──── process_video.delay(media_id)
│ (async)      │
└──────┬───────┘
       │
       ├── Step 1: Transcribe (Whisper)
       ├── Step 2: Generate embeddings (text-embedding-3-large)
       ├── Step 3: Detect scenes (FFmpeg + GPT-4o)
       ├── Step 4: Generate thumbnails
       ├── Step 5: Build knowledge graph (Neo4j)
       └── Step 6: Update status → COMPLETED
```

---

## Appendix: Evaluation System

QPrisma uses Azure AI Foundry for agent evaluation, located in `evaluation_foundry/`.

### Structure

```
evaluation_foundry/
├── config.py                    # Evaluation pipeline configuration
├── generate_eval_data.py        # Generate test datasets
├── register_evaluators.py       # Register custom evaluators
├── redteam_eval.py              # AI Red Teaming scan runner (direct-attack / jailbreak)
├── tool_definitions.py          # Tool schemas for evaluation
└── data/                        # Evaluation datasets and results
```

### Key Components

| File | Purpose |
|---|---|
| `config.py` | Defines evaluation parameters, model endpoints, and scoring thresholds |
| `generate_eval_data.py` | Creates synthetic test data from video transcripts and Q&A pairs |
| `register_evaluators.py` | Registers custom evaluators with Azure AI Foundry |
| `redteam_eval.py` | Runs the cloud Foundry AI Red Teaming workflow against the hosted agent for direct-attack / jailbreak coverage |
| `tool_definitions.py` | Provides tool schemas used in evaluation scenarios |

### Safety evaluator matrix

The built-in Foundry safety evaluators registered in `config.py::SAFETY_EVALUATORS`:

| Evaluator | Target | Notes |
|---|---|---|
| `violence`, `sexual`, `self_harm`, `hate_unfairness` | Model & Agents | Core content-safety metrics |
| `protected_material` | Model & Agents | Copyrighted content detection |
| `code_vulnerability` | Model & Agents | Unsafe code suggestions |
| `ungrounded_attributes` | Model & Agents | Unsupported attribute inference |
| `indirect_attack` | Model only | Registered for dataset compatibility; may no-op on agent targets |

Direct-attack / jailbreak coverage is **not** a runtime evaluator. It is provided by the cloud Foundry AI Red Teaming workflow and must be invoked separately via `redteam_eval.py`.

### `response_mode=final_answer` guarantee

The hosted agent converter (`agent/hosted/state_converter.py`) enforces that `response_mode=final_answer` responses always contain at least one assistant message item. When the agent graph ends on a tool call, returns an empty `AIMessage`, or emits only preamble text alongside tool calls, the converter falls back to the last non-empty assistant text (or a short placeholder) so Foundry's Responses API never receives an empty payload. Without this guarantee, media-context queries (those exercising tools) produce HTTP 400 "Response could not be saved due to invalid format" during evaluation runs.

The current production/frontend request path does not set `response_mode`
explicitly; it relies on the converter's default `full` mode. `final_answer`
remains available as an opt-in compatibility/debug lever while the hosted
adapter is audited, but it is no longer the default path that evaluation data
generation should mirror.

### Running Evaluations

```bash
# Generate evaluation data
export EVAL_MEDIA_ID_1=<video-uuid>
export EVAL_MEDIA_ID_2=<video-uuid>
export EVAL_USER_ID=<runtime-user-id>
python -m evaluation_foundry.generate_eval_data --output-dir ./eval-output

# Register evaluators
python -m evaluation_foundry.register_evaluators

# Run evaluation via Azure AI Foundry
# (Configured in Azure AI Foundry portal or via SDK)

# Run AI Red Teaming scan (direct-attack / jailbreak)
python -m evaluation_foundry.redteam_eval \
    --agent-id "<agent-name>:<version>" \
    --endpoint "$AZURE_AI_PROJECT_ENDPOINT" \
    --model-deployment gpt-5.5 \
    --strategies base64,flip,indirect_jailbreak \
    --risk-categories prohibited_actions \
    --output redteam-results.json
```

In CI, the red-team scan is gated behind the `run-redteam=true` input on the
`evaluate-agent` workflow (`workflow_dispatch` only) to avoid per-deploy cost.

The cloud red-team path requires the Foundry project to be in a supported
region and the caller to have the **Azure AI User** role on the project.

---

*This document is maintained alongside the codebase. For API endpoint details, see [API_DOCUMENTATION.md](../API_DOCUMENTATION.md). For testing guidelines, see [TESTING.md](../TESTING.md).*
