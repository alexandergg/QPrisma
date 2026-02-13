# QPrisma Backend — Documentación Técnica de Arquitectura

> **Versión**: 1.0.0 | **Python**: 3.11+ | **Framework**: FastAPI + LangGraph + Celery  
> **Última actualización**: Febrero 2026

---

## Tabla de Contenidos

1. [Visión General](#1-visión-general)
2. [Estructura del Proyecto](#2-estructura-del-proyecto)
3. [Capa de Configuración (`core/`)](#3-capa-de-configuración-core)
4. [API REST (`api/`)](#4-api-rest-api)
5. [Sistema de Agentes IA (`agent/`)](#5-sistema-de-agentes-ia-agent)
6. [Capa de Servicios (`services/`)](#6-capa-de-servicios-services)
7. [Modelos de Datos (`models/`)](#7-modelos-de-datos-models)
8. [Procesamiento Asíncrono (`tasks/`)](#8-procesamiento-asíncrono-tasks)
9. [Pipeline de Procesamiento de Video](#9-pipeline-de-procesamiento-de-video)
10. [Knowledge Graph (Neo4j)](#10-knowledge-graph-neo4j)
11. [Sistema de Búsqueda Híbrida](#11-sistema-de-búsqueda-híbrida)
12. [Arquitectura de Memoria del Agente](#12-arquitectura-de-memoria-del-agente)
13. [Sistema de Caché Multinivel](#13-sistema-de-caché-multinivel)
14. [Chat-to-Edit (Editor de Video)](#14-chat-to-edit-editor-de-video)
15. [Protocolo A2A (Agent-to-Agent)](#15-protocolo-a2a-agent-to-agent)
16. [Autenticación y Seguridad](#16-autenticación-y-seguridad)
17. [Observabilidad y Métricas](#17-observabilidad-y-métricas)
18. [Patrones de Diseño](#18-patrones-de-diseño)
19. [Dependencias y Stack Tecnológico](#19-dependencias-y-stack-tecnológico)
20. [Diagramas de Flujo](#20-diagramas-de-flujo)

---

## 1. Visión General

QPrisma es una plataforma de procesamiento multimedia inteligente que combina visión por computador, modelos de lenguaje (LLMs) y RAG avanzado para proporcionar análisis automático de contenido, búsqueda conversacional y análisis semántico de video.

### Arquitectura de Alto Nivel

```
┌──────────────┐     ┌─────────────────────────────────────────────────────┐
│   Frontend   │────▶│                   FastAPI Backend                   │
│  (Next.js)   │◀────│                                                     │
└──────────────┘     │  ┌─────────┐  ┌──────────┐  ┌───────────────────┐  │
                     │  │  API    │  │ Services │  │  LangGraph Agents │  │
                     │  │ Routes  │──│  Layer   │──│  (Video + Editor) │  │
                     │  └─────────┘  └──────────┘  └───────────────────┘  │
                     │       │            │               │               │
                     └───────┼────────────┼───────────────┼───────────────┘
                             │            │               │
              ┌──────────────┼────────────┼───────────────┼──────────────┐
              │              ▼            ▼               ▼              │
              │  ┌──────────────┐ ┌─────────────┐ ┌───────────────┐    │
              │  │  PostgreSQL  │ │    Neo4j     │ │ Azure OpenAI  │    │
              │  │  (Metadata)  │ │  (Knowledge  │ │ (GPT-4o,      │    │
              │  │              │ │   Graph)     │ │  Whisper,      │    │
              │  └──────────────┘ └─────────────┘ │  Embeddings)   │    │
              │  ┌──────────────┐ ┌─────────────┐ └───────────────┘    │
              │  │    Redis     │ │ Azure Blob  │                      │
              │  │ (Cache/Queue │ │  Storage    │                      │
              │  │ Checkpoints) │ │  (Media)    │                      │
              │  └──────────────┘ └─────────────┘                      │
              │                 Infraestructura                          │
              └─────────────────────────────────────────────────────────┘
```

### Principios Arquitectónicos

| Principio | Implementación |
|-----------|----------------|
| **Separación de responsabilidades** | Routes → Services → Data Access |
| **Async-first** | `async/await` en toda la cadena I/O |
| **Configuración centralizada** | Pydantic Settings (`core.config.settings`) |
| **Singletons con lazy init** | Servicios y clientes Azure inicializados bajo demanda |
| **Fail-safe en herramientas** | Las tools del agente nunca lanzan excepciones |
| **Observabilidad estructurada** | Correlation IDs + métricas Prometheus-style |
| **Multi-tenant** | Scoping por `user_id` en todas las operaciones |

---

## 2. Estructura del Proyecto

```
backend/
├── api/                          # Capa HTTP (FastAPI)
│   ├── main.py                   # App entry point, lifespan, CORS, routers
│   ├── dependencies.py           # Singletons, auth, service getters
│   └── routes/                   # 14 módulos de rutas
│       ├── a2a_routes.py         # Protocolo Agent-to-Agent
│       ├── auth_routes.py        # Autenticación JWT
│       ├── batch_routes.py       # Azure Batch API
│       ├── cache_routes.py       # Gestión de caché
│       ├── chat_routes.py        # Chat conversacional + RAG
│       ├── chunked_upload_routes.py  # Upload paralelo por bloques
│       ├── editor_routes.py      # Video editor (Chat-to-Edit)
│       ├── graph_routes.py       # Knowledge Graph CRUD + búsqueda
│       ├── jobs_routes.py        # Gestión de jobs Celery
│       ├── media_routes.py       # Upload/CRUD de media
│       ├── processing_routes.py  # Pipeline de procesamiento
│       ├── storage_routes.py     # Tiering de almacenamiento
│       ├── structure_routes.py   # Estructura video (escenas/capítulos)
│       ├── websocket_routes.py   # WebSocket para progreso real-time
│       └── websocket_manager.py  # Gestor de conexiones WebSocket
│
├── agent/                        # Sistema de agentes IA (LangGraph)
│   ├── a2a.py                    # Bridge A2A ↔ LangGraph
│   ├── prompts.py                # System prompts para agentes
│   ├── graphs/                   # Definiciones de StateGraph
│   │   ├── video.py              # Agente de análisis de video
│   │   └── editor.py             # Agente de edición (Chat-to-Edit)
│   ├── nodes/                    # Implementaciones de nodos
│   │   ├── base.py               # Nodos compartidos (DRY)
│   │   ├── video_nodes.py        # Nodos específicos video
│   │   └── editor_nodes.py       # Nodos específicos editor
│   ├── state/                    # Definiciones de estado
│   │   └── agent_state.py        # AgentState, Input/Output schemas
│   ├── tools/                    # Herramientas del agente
│   │   ├── general.py            # 16 tools de búsqueda/análisis
│   │   └── editor.py             # 15 tools de edición
│   └── utils/                    # Utilidades
│       ├── formatting.py         # Formateo de timestamps
│       └── observability.py      # Logging estructurado + métricas
│
├── core/                         # Módulos transversales
│   ├── config.py                 # Configuración centralizada (Pydantic Settings)
│   ├── constants.py              # Constantes de aplicación
│   ├── exceptions.py             # Excepciones estructuradas
│   ├── logging_config.py         # Configuración de logging
│   ├── async_utils.py            # Thread pool para sync→async
│   └── serializers.py            # Serialización JSON (numpy, neo4j, datetime)
│
├── models/                       # Modelos de datos
│   ├── database.py               # SQLAlchemy ORM (User, Media, Job, Project, Clip)
│   ├── graph_models.py           # Modelos Neo4j (Pydantic)
│   ├── api_schemas.py            # Schemas de request/response
│   ├── a2a_models.py             # Modelos A2A protocol
│   ├── editor.py                 # Modelos de editor
│   ├── export_config.py          # Configuración de exportación
│   ├── ffmpeg_config.py          # Configuración FFmpeg
│   ├── cache_models.py           # Modelos de caché
│   ├── graph_route_schemas.py    # Schemas para rutas del grafo
│   └── user.py                   # Modelos de usuario
│
├── services/                     # Lógica de negocio (25 servicios)
│   ├── audio_processor.py        # Extracción y transcripción de audio
│   ├── auth_service.py           # Autenticación JWT + bcrypt
│   ├── batch_processor.py        # Azure Batch API (50% ahorro)
│   ├── cache_service.py          # Caché multinivel Redis/Memory
│   ├── chat_service.py           # Chat conversacional con RAG
│   ├── database_service.py       # Acceso a datos PostgreSQL
│   ├── embedding_service.py      # Embeddings (text-embedding-3-large)
│   ├── enhanced_search.py        # Búsqueda avanzada con re-ranking LLM
│   ├── entity_extractor.py       # Extracción de entidades (GPT-4o vision)
│   ├── export_service.py         # Exportación FFmpeg + Azure Blob
│   ├── face_tracking_service.py  # Detección/tracking facial (smart crop)
│   ├── ffmpeg_processor.py       # Procesamiento FFmpeg (hwaccel)
│   ├── graph_search_service.py   # Búsqueda híbrida Neo4j (VideoRAG)
│   ├── hierarchical_context_service.py  # RAG jerárquico
│   ├── hierarchical_summarizer.py # Resúmenes multi-nivel
│   ├── knowledge_graph.py        # CRUD Neo4j (1738 líneas)
│   ├── mem0_memory_service.py    # Memoria semántica (Mem0)
│   ├── relation_builder.py       # Construcción de relaciones
│   ├── scene_analyzer.py         # Análisis de escenas
│   ├── storage_tiering_service.py # Tiering Azure Blob
│   ├── structure_service.py      # Estructura de video
│   ├── subtitle_service.py       # Generación de subtítulos
│   ├── tool_artifact_service.py  # Almacenamiento de artifacts (3 capas)
│   ├── video_processor.py        # Pipeline completo de video
│   └── viral_score_service.py    # Scoring de potencial viral
│
├── tasks/                        # Procesamiento distribuido (Celery)
│   ├── celery_app.py             # Configuración Celery + Redis
│   └── video_tasks.py            # Pipeline de tareas de video
│
├── evaluation/                   # Framework de evaluación
│   ├── run_evaluation.py         # Runner de benchmarks
│   ├── adapters/                 # Adaptadores de benchmarks
│   ├── benchmarks/               # Video-MME, MLVU
│   ├── judges/                   # Evaluadores LLM
│   └── metrics/                  # Métricas de scoring
│
└── tests/                        # Tests (pytest, asyncio_mode="auto")
```

---

## 3. Capa de Configuración (`core/`)

### 3.1 Configuración Centralizada (`config.py`)

Toda la configuración se gestiona a través de **Pydantic Settings**, prohibiendo el uso directo de `os.getenv()`:

```python
from core.config import settings

settings.azure.openai_endpoint        # Azure OpenAI endpoint
settings.azure.storage_connection_string  # Blob Storage
settings.postgres.database_url         # PostgreSQL
settings.neo4j.uri                     # Neo4j bolt://
settings.redis.url                     # Redis
settings.auth.jwt_secret_key           # JWT secret
settings.mem0.enabled                  # Feature flag Mem0
settings.artifacts.cache_ttl_seconds   # TTL artifacts
settings.app.environment               # dev/prod
```

#### Jerarquía de Settings

```
Settings (Root)
├── AppSettings           # app name, version, port, CORS, log level
├── AzureSettings         # OpenAI, Storage, Batch deployments
├── BatchAPISettings      # polling interval, max wait time
├── PostgresSettings      # DATABASE_URL (validated in prod)
├── Neo4jSettings         # URI, user, password, database
├── RedisSettings         # URL
├── ArtifactSettings      # TTL, key prefix, blob prefix
├── Mem0Settings          # enabled, api_key, top_k
└── AuthSettings          # JWT secret, algorithm, token expiry
```

#### Validaciones de Producción

Las settings incluyen `field_validator` que **fallan en producción** si detectan credenciales por defecto:

```python
@field_validator("database_url")
def validate_database_url(cls, v: str) -> str:
    if _is_production() and "qprisma123" in v:
        raise ValueError("Default database credentials detected in production.")
    return v
```

Esto aplica a: `database_url`, `neo4j.password`, `auth.jwt_secret_key`.

#### Factory de Clientes Azure

```python
# Clientes cacheados para evitar recreación
@lru_cache
def get_settings() -> Settings: ...

def create_azure_openai_client() -> AzureOpenAI: ...
def create_async_azure_openai_client() -> AsyncAzureOpenAI: ...
```

### 3.2 Logging Estructurado (`logging_config.py`)

Dos formateadores disponibles:

| Formateador | Uso | Formato |
|-------------|-----|---------|
| `ColoredFormatter` | Desarrollo (TTY) | Colores ANSI por nivel |
| `StructuredFormatter` | Producción | `[timestamp] [LEVEL] [module] message │ key=value` |

### 3.3 Excepciones Estructuradas (`exceptions.py`)

```python
class APIError(HTTPException):
    """Respuesta JSON estructurada con código de error."""
    # Response: {"error": {"code": "MEDIA_NOT_FOUND", "message": "...", "context": {...}}}

# Factory functions
not_found_error("media", media_id)       # 404
access_denied_error("media", media_id)   # 403
validation_error("Invalid format")        # 400
service_unavailable_error("neo4j")        # 503
```

### 3.4 Constantes (`constants.py`)

| Categoría | Constantes clave |
|-----------|-----------------|
| Procesamiento | `DEFAULT_MAX_FRAMES=20`, `DEFAULT_SCENE_THRESHOLD=0.3`, `WHISPER_MAX_FILE_SIZE_MB=25` |
| API | `MAX_VIDEO_SIZE_BYTES=500MB`, `MAX_CHAT_HISTORY_LENGTH=20` |
| Cache TTLs | `SHORT=60s`, `MEDIUM=300s`, `LONG=3600s`, `VERY_LONG=86400s` |
| Neo4j Labels | `NODE_VIDEO`, `NODE_SCENE`, `NODE_FRAME`, `NODE_ENTITY`, `NODE_TOPIC` |

### 3.5 Utilidades Async (`async_utils.py`)

```python
# Ejecutar código sync sin bloquear el event loop
result = await run_sync(heavy_sync_function, arg1, arg2)

# Decorador para envolver funciones sync
@async_wrap
def sync_compute(data): ...
# Ahora: await sync_compute(data)
```

Usa `ThreadPoolExecutor(max_workers=4)` compartido.

---

## 4. API REST (`api/`)

### 4.1 Entry Point (`main.py`)

La aplicación FastAPI se configura con:

- **Lifespan manager**: Health checks de startup (OpenAI, Blob, PostgreSQL) y Redis Pub/Sub para WebSocket
- **CORS**: Configurable vía `settings.app.cors_origins`
- **14 routers** registrados con prefijos y tags
- **Endpoints base**: `GET /` (health), `GET /health` (detallado), `GET /config` (estado)
- **Servidor**: Uvicorn con auto-reload en desarrollo

### 4.2 Dependency Injection (`dependencies.py`)

Patrón singleton con lazy initialization para todos los clientes y servicios:

```python
_blob_service: BlobServiceClient | None = None

def get_blob_service() -> BlobServiceClient | None:
    global _blob_service
    if _blob_service is None:
        conn = settings.azure.storage_connection_string
        if conn:
            _blob_service = BlobServiceClient.from_connection_string(
                conn,
                max_single_put_size=256 * 1024 * 1024,   # 256MB
                max_block_size=100 * 1024 * 1024,         # 100MB bloques
                max_concurrency=8,                          # threads paralelos
            )
    return _blob_service
```

#### Singletons disponibles

| Getter | Servicio | Notas |
|--------|----------|-------|
| `get_blob_service()` | Azure Blob Storage | Transfer settings optimizados |
| `get_openai_client()` | Azure OpenAI (sync) | AzureOpenAI |
| `get_async_openai_client()` | Azure OpenAI (async) | AsyncAzureOpenAI |
| `get_video_processor()` | VideoProcessor | Requiere blob + openai |
| `get_auth_service()` | AuthService | JWT management |
| `get_graph_search_service()` | GraphSearchService | + auto-init vector indexes |
| `get_tool_artifact_service()` | ToolArtifactService | async getter |
| `get_current_user()` | Auth dependency | FastAPI `Depends()` |
| `get_current_user_optional()` | Auth opcional | No lanza 401 |

### 4.3 Catálogo de Endpoints (14 Routers, ~80 endpoints)

#### Autenticación (`/auth`)
| Método | Ruta | Descripción |
|--------|------|-------------|
| POST | `/register` | Registro de usuario → JWT |
| POST | `/login` | Login → JWT access + refresh token |
| GET | `/me` | Perfil del usuario actual |
| POST | `/refresh` | Renovar access token |

#### Media (`/media`, `/upload`)
| Método | Ruta | Descripción |
|--------|------|-------------|
| POST | `/upload` | Upload de archivo multimedia |
| POST | `/upload/optimized` | Upload con pipeline optimizado |
| GET | `/media` | Listar media del usuario |
| GET | `/media/{id}` | Obtener detalle (hydrata datos blob) |
| GET | `/media/{id}/status` | Estado de procesamiento |
| GET | `/media/{id}/audio` | Datos de audio/transcripción |
| GET | `/media/{id}/search` | Búsqueda dentro de un video |
| DELETE | `/media/{id}` | Eliminar media |

#### Upload Chunked (`/upload/chunked`)
| Método | Ruta | Descripción |
|--------|------|-------------|
| POST | `/init` | Iniciar sesión de upload por bloques |
| POST | `/commit` | Finalizar y consolidar upload |
| GET | `/status/{id}` | Progreso del upload |
| DELETE | `/cancel/{id}` | Cancelar upload |

#### Chat & Search
| Método | Ruta | Descripción |
|--------|------|-------------|
| POST | `/chat` | Chat conversacional con RAG de video |
| POST | `/search` | Búsqueda híbrida (vector + fulltext + graph) |

#### Procesamiento (`/process`, `/batch`, `/pipeline`)
| Método | Ruta | Descripción |
|--------|------|-------------|
| POST | `/process/video/ffmpeg` | Procesar video con FFmpeg (tarea background) |
| POST | `/process/video/ffmpeg/batch` | Batch de múltiples videos |
| GET | `/batch/status` | Estado de trabajo batch Azure |
| POST | `/batch/cancel` | Cancelar batch |
| GET | `/pipeline/preview` | Preview configuración pipeline |
| GET | `/presets` | Listar presets FFmpeg |
| POST | `/search/enhanced` | Búsqueda avanzada con matching |

#### Knowledge Graph (`/graph`)
| Método | Ruta | Descripción |
|--------|------|-------------|
| GET | `/health` | Salud de conexión Neo4j |
| GET | `/stats` | Estadísticas del grafo |
| POST | `/search/hybrid` | Búsqueda híbrida VideoRAG |
| POST | `/search/entities` | Buscar entidades |
| POST | `/search/frames` | Buscar frames |
| POST | `/search/cross-video` | Búsqueda cross-video |
| POST | `/embeddings/generate` | Generar embeddings para nodos |
| POST | `/expand` | Expansión de contexto (N-hop) |
| POST | `/timeline` | Timeline de entidad |
| POST | `/hierarchy/process` | Construir jerarquía |
| POST | `/hierarchy/search/drill-down` | Búsqueda drill-down jerárquica |
| GET | `/video/{id}/visualization` | Datos visualización (NVL) |

#### Editor (`/editor`)
| Método | Ruta | Descripción |
|--------|------|-------------|
| POST | `/projects` | Crear proyecto desde video |
| GET | `/projects` | Listar proyectos |
| GET/PATCH/DELETE | `/projects/{id}` | CRUD proyecto |
| POST | `/projects/{id}/clips` | Crear clip |
| POST | `/projects/{id}/chat` | Chat-to-Edit (streaming SSE) |
| POST | `/clips/{id}/subtitles/generate` | Generar subtítulos |
| POST | `/clips/{id}/export` | Exportar clip para plataforma |
| GET | `/subtitle-styles` | Estilos de subtítulos disponibles |
| GET | `/export/presets` | Presets de exportación |

#### A2A Protocol
| Método | Ruta | Descripción |
|--------|------|-------------|
| GET | `/.well-known/agent-card.json` | Descubrimiento de agente (público) |
| POST | `/a2a/message:send` | Enviar mensaje al agente |
| POST | `/a2a/message:stream` | Stream de mensajes (SSE) |
| GET | `/a2a/tasks/{id}` | Estado de tarea |
| POST | `/a2a/tasks/{id}:cancel` | Cancelar tarea |
| POST | `/a2a/tasks/{id}:subscribe` | Suscripción SSE a tarea |

#### Jobs (`/jobs`)
| Método | Ruta | Descripción |
|--------|------|-------------|
| POST | `/submit` | Enviar video a procesamiento async |
| GET | `/{id}` | Estado del job |
| POST | `/{id}/cancel` | Cancelar job |
| GET | `/{id}/result` | Resultado completo |
| GET | `/stats/summary` | Estadísticas (workers, colas) |

#### Storage Tiering (`/storage`)
| Método | Ruta | Descripción |
|--------|------|-------------|
| GET | `/media/{id}/tier` | Tier actual del blob |
| POST | `/media/{id}/tier` | Cambiar tier (Hot/Cool/Cold/Archive) |
| POST | `/media/{id}/rehydrate` | Rehidratar desde Archive |
| GET | `/media/{id}/recommendation` | Recomendación de tier |
| GET | `/cost-analysis` | Análisis de costos |

#### Cache (`/cache`)
| Método | Ruta | Descripción |
|--------|------|-------------|
| GET | `/metrics` | Métricas hit/miss/ahorro |
| POST | `/invalidate` | Invalidar caché |
| GET | `/health` | Salud de la caché |

#### WebSocket (`/ws`)
| Protocolo | Ruta | Descripción |
|-----------|------|-------------|
| WS | `/jobs/{job_id}` | Seguimiento de un job |
| WS | `/user/{user_id}` | Todos los updates de un usuario |
| WS | `/all` | Todos los updates (admin) |

---

## 5. Sistema de Agentes IA (`agent/`)

### 5.1 Arquitectura General

QPrisma implementa dos agentes basados en **LangGraph** (v1.0+) con el patrón **ReAct** (Reasoning + Acting):

```
┌─────────────────────────────────────────────────┐
│              LangGraph StateGraph                │
│                                                   │
│  START → call_model → has_tool_calls?            │
│               │              │                    │
│               │         ┌────▼────┐               │
│               │         │  tools  │  (ToolNode)   │
│               │         └────┬────┘               │
│               │              │                    │
│               │     ┌────────▼────────┐           │
│               │     │ update_context  │           │
│               │     └────────┬────────┘           │
│               │              │                    │
│               │         back to call_model        │
│               │                                   │
│          no tool calls                            │
│               │                                   │
│          ┌────▼────┐                              │
│          │   END   │                              │
│          └─────────┘                              │
│                                                   │
│  error_handler → END (graceful degradation)       │
└─────────────────────────────────────────────────┘
```

### 5.2 Video Agent (`graphs/video.py`)

**Propósito**: Análisis profundo de contenido de video — búsqueda, exploración, análisis comparativo.

#### Grafo

```
START → call_model → should_continue? ─── "tools" ──→ tools → update_context → call_model
                          │                                         ↑
                          │── "error_handler" ──→ error_handler → END
                          │
                          └── "__end__" ──→ END
```

#### Configuración

| Parámetro | Valor | Descripción |
|-----------|-------|-------------|
| `MAX_TOOL_ITERATIONS` | 5 | Máximo de ciclos tool-call |
| `WARN_TOOL_ITERATIONS` | 3 | Umbral de advertencia |
| `MAX_CONTEXT_TOKENS` | 200,000 | Límite de tokens de contexto |
| `MAX_TOOL_RESULT_CHARS` | 6,000 | Truncado de resultados de tools |
| `MAX_CONSECUTIVE_ERRORS` | 3 | Umbral para degradación |

#### Herramientas (16 Search Tools)

| Tool | Categoría | Descripción |
|------|-----------|-------------|
| `search_video` | Búsqueda | Buscar momentos, temas, objetos, palabras |
| `find_entity` | Búsqueda | Encontrar todas las ocurrencias de una entidad |
| `get_transcript` | Contenido | Obtener transcripción en un rango temporal |
| `describe_scene` | Contenido | Descripción visual detallada en un timestamp |
| `get_scene_context` | Contenido | Contexto completo (antes/durante/después) |
| `list_chapters` | Estructura | Capítulos y estructura del video |
| `get_video_info` | Estructura | Metadatos del video |
| `get_summary` | Estructura | Resumen a diferentes niveles |
| `get_related_content` | Grafo | Explorar conexiones del knowledge graph |
| `get_entity_timeline` | Análisis | Tracking cronológico de una entidad |
| `compare_moments` | Análisis | Comparar múltiples timestamps |
| `find_highlights` | Análisis | Identificar mejores momentos (virales) |
| `search_across_videos` | Multi-video | Buscar en múltiples videos |
| `compare_videos` | Multi-video | Comparar videos entre sí |
| `find_common_entities` | Multi-video | Entidades comunes entre videos |
| `get_library_overview` | Multi-video | Overview de la biblioteca |

#### Técnicas Clave

1. **Dynamic Tool Binding**: Selección dinámica de subset focalizados de herramientas basada en la consulta del usuario (máx 8 tools):

```python
tools = select_tools_for_query(user_query, SEARCH_TOOLS, max_tools=8)
```

2. **Message Trimming**: Prevención de overflow del context window con `trim_messages`:
```python
_message_trimmer = get_message_trimmer(max_tokens=80000)
# strategy="last", include_system=True, start_on="human"
```

3. **Tool Result Truncation**: Resultados de tools truncados a 6000 chars (~1500 tokens).

4. **Smart Retry Policy**: Reintentos por excepción con backoff exponencial:
```python
RetryPolicy(
    max_attempts=3,
    initial_interval=1.0,
    backoff_factor=2.0,
    retry_on=should_retry_exception,  # Solo errores transitorios
)
```

5. **Metadata Extraction**: Extracción automática de sources, navigation_actions, clip_suggestions y entities de los resultados de tools para enriquecer la respuesta.

### 5.3 Editor Agent (`graphs/editor.py`)

**Propósito**: Edición de video conversacional (Chat-to-Edit) — crear clips, subtítulos, exportar.

#### Grafo

```
START → call_model → should_continue? ─── "tools" ──→ tools* → update_context → call_model
                          │
                          │── "error_handler" ──→ error_handler → END
                          └── "__end__" ──→ END

* tools = tools_with_interrupt (si HITL habilitado) OR ToolNode estándar
```

#### Configuración

| Parámetro | Valor |
|-----------|-------|
| `MAX_EDITOR_TOOL_ITERATIONS` | 8 |
| `EDITOR_WARN_TOOL_ITERATIONS` | 6 |

#### Herramientas (15 Editor Tools)

| Tool | Tipo | Descripción |
|------|------|-------------|
| `create_clip` | 🔴 Destructiva | Crear clip desde rango temporal |
| `modify_clip` | 🔴 Destructiva | Modificar timing/título de clip |
| `delete_clip` | 🔴 Destructiva | Eliminar clip |
| `reorder_clips` | 🔴 Destructiva | Reordenar clips |
| `add_suggested_clips` | 🔴 Destructiva | Añadir clips sugeridos por IA |
| `add_subtitles` | 🔴 Destructiva | Añadir subtítulos |
| `change_subtitle_style` | 🔴 Destructiva | Cambiar estilo subtítulos |
| `remove_subtitles` | 🔴 Destructiva | Quitar subtítulos |
| `export_clip` | 🔴 Destructiva | Exportar clip |
| `export_all_clips` | 🔴 Destructiva | Exportar todos los clips |
| `list_clips` | 🟢 Safe | Listar clips del proyecto |
| `generate_auto_clips` | 🟢 Safe | Generar clips automáticamente |
| `list_subtitle_styles` | 🟢 Safe | Listar estilos disponibles |
| `get_export_status` | 🟢 Safe | Estado de exportación |
| `list_export_presets` | 🟢 Safe | Presets de plataforma |

#### Human-in-the-Loop (HITL)

El editor implementa **interrupción granular** usando `interrupt()` de LangGraph v1.0+:

```python
async def tools_with_interrupt(state, config):
    # Clasificar tools por peligrosidad
    for tool_call in last_message.tool_calls:
        if tool_name in DESTRUCTIVE_TOOLS:
            needs_confirmation.append(tool_call)
        else:
            safe_calls.append(tool_call)
    
    # Interrumpir solo para tools destructivas
    if needs_confirmation:
        user_response = interrupt({
            "message": "I'm about to: • Create clip...\nProceed?",
            "pending_tools": needs_confirmation
        })
        
        if not user_response.get("confirmed"):
            return cancelled_messages  # Operación cancelada
    
    # Ejecutar tools aprobadas
    return await tool_node.ainvoke(state, config)
```

### 5.4 Estado del Agente (`state/agent_state.py`)

#### AgentState (interno)

```python
class AgentState(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]  # Reducer automático
    media_id: str | None
    media_ids: list[str] | None
    video_context: VideoContext | None
    project_context: ProjectContext | None
    project_id: str | None
    sources: list[dict]
    
    # Internos (ocultos de la API)
    tool_calls_count: int
    conversation_context: list[str]      # Últimos 10 temas discutidos
    consecutive_errors: int
    last_error: str | None
    partial_results: list[dict]
    memory_context: list[str]            # Snippets de memoria compactos
    artifact_refs: list[ToolArtifactRef] # Referencias a artifacts externos
    
    user_id: str | None
    session_id: str | None
```

#### Separación Input/Output (Best Practice LangGraph v1.0+)

```python
class AgentInputState(TypedDict):   # Lo que el API consumer envía
    messages, media_id, media_ids, video_context, project_context, project_id, user_id, session_id

class AgentOutputState(TypedDict):  # Lo que el API consumer recibe
    messages, sources, video_context, project_context
```

#### InjectedState para Tools

Las tools acceden al estado del grafo sin acoplamientos globales:

```python
@tool
async def search_video(
    query: Annotated[str, "What to search for"],
    media_id: Annotated[str | None, InjectedState("media_id")] = None,
) -> dict:
    # media_id inyectado automáticamente desde el estado del grafo
```

### 5.5 Nodos Base (`nodes/base.py`)

#### Modelo LLM (Cacheado)

```python
@lru_cache(maxsize=8)
def create_model(
    model_deployment: str | None = None,
    temperature: float = 1,
    streaming: bool = True,
) -> AzureChatOpenAI:
    # Cacheado por (deployment, temperature, streaming)
```

#### Selección Dinámica de Herramientas

```python
def select_tools_for_query(query: str, all_tools: list, max_tools: int = 8) -> list:
    """Selecciona subset relevante de tools basado en la consulta."""
    # Análisis de keywords → matching con tools → top-N por relevancia
```

#### Memory Context Híbrido

Antes de cada invocación del modelo, se ejecuta:

1. **Recolección de candidatos híbridos**: memoria local + Mem0 + artifact refs
2. **Re-ranking ligero**: overlap léxico + score semántico + recencia
3. **Budget dinámico de contexto**: 1200–2200 chars según tipo de query
4. **Rehidratación selectiva de artifacts**: solo para queries detail-heavy

```python
ARTIFACT_REHYDRATION_MAX_ITEMS = 2
ARTIFACT_REHYDRATION_MAX_TOTAL_CHARS = 3500
HYBRID_MEMORY_MAX_CANDIDATES = 24
HYBRID_MEMORY_MAX_SNIPPETS = 6
```

### 5.6 Checkpointers (Persistencia de Estado)

Cascada de checkpointers para producción:

```
PostgreSQL (más durable, ACID)
    ↓ fallback
Redis (baja latencia)
    ↓ fallback  
MemorySaver (solo desarrollo)
```

```python
def create_production_checkpointer():
    cp = create_postgres_checkpointer()  # AsyncPostgresSaver
    if cp: return cp
    
    cp = create_redis_checkpointer()     # AsyncRedisSaver
    if cp: return cp
    
    return MemorySaver()  # ⚠️ NO apto para producción
```

### 5.7 System Prompts (`prompts.py`)

| Prompt | Contexto | Contenido |
|--------|----------|-----------|
| `SYSTEM_PROMPT` | Video cargado | Rol, capacidades, guidelines de calidad, estrategias por tipo de pregunta, formato de respuesta |
| `MULTI_VIDEO_SYSTEM_PROMPT` | Múltiples videos | Capacidades cross-video |
| `NO_VIDEO_CONTEXT_PROMPT` | Sin video | Guía al usuario para cargar video |
| `EDITOR_SYSTEM_PROMPT` | Modo editor | Capacidades de edición |
| `EDITOR_NO_PROJECT_PROMPT` | Sin proyecto | Guía para crear proyecto |

---

## 6. Capa de Servicios (`services/`)

La lógica de negocio reside en **25 servicios** en la capa `services/`. Los route handlers delegan directamente a los servicios.

### 6.1 Servicios de Procesamiento de Video

#### VideoProcessor
**Orquestador del pipeline completo de procesamiento de video.**

```
Upload → Frame Extraction (FFmpeg) → Vision Analysis (GPT-4o) → Embedding Generation → Audio Transcription
```

- **Extracción de frames**: FFmpeg con hwaccel (CUDA, QSV, D3D11VA)
- **Análisis visual**: GPT-4o con Batch API para 50% ahorro de costos
- **Budget adaptativo de tokens**: Estimación de complejidad por entropía de imagen (low/medium/high)
- **Embeddings batch**: Generación paralela con `text-embedding-3-large`

#### FFmpegVideoProcessor (1181 líneas)
**Motor de extracción de frames ultra-rápido.**

| Feature | Detalle |
|---------|---------|
| Hardware Acceleration | Auto-detect CUDA, QSV, D3D11VA, VideoToolbox, VAAPI |
| Métodos de extracción | Uniform, Scene-based, Hybrid, Keyframes, Adaptive |
| Filter chains | Composición dinámica de filtros FFmpeg |
| Parallel extraction | `ThreadPoolExecutor` para extracción multithread |
| Presets | FAST_PREVIEW, BALANCED, HIGH_QUALITY, KEYFRAMES_ONLY, SCENE_ANALYSIS |

#### AudioProcessor
**Extracción de audio y transcripción con Azure Whisper.**

- Extracción FFmpeg → formato Whisper-compatible
- **Chunking inteligente**: Para archivos >25MB (límite Whisper), split en puntos de silencio via VAD
- **Rate limiting**: Throttling configurable (`WHISPER_MAX_RPM`)
- **Análisis enriquecido**: GPT-4o analiza la transcripción (temas, speakers, sentimiento)

#### BatchProcessor
**Azure OpenAI Global Batch API para 50% de ahorro en análisis visual.**

```
Create JSONL → Upload → Submit → Poll Status → Download Results → Parse
```

- Build JSONL con schema de respuesta forzado (`FRAME_ANALYSIS_SCHEMA`)
- Wait con backoff exponencial
- Estimación de costos por frame

#### SceneAnalyzer
**Chunking inteligente de video en escenas.**

```
Detección FFmpeg (scene filter) ──┐
                                   ├──→ Merge → Scenes → Chapters → VideoStructure
Clustering Semántico (embeddings) ─┘
```

- Detección de cambios de escena vía `select=gt(scene,threshold)`
- Clustering semántico por embeddings de frames
- Merge de ambos métodos con pesos configurables
- Generación automática de capítulos

### 6.2 Servicios de Knowledge Graph

#### KnowledgeGraphService (1738 líneas)
**Servicio primario del Knowledge Graph en Neo4j.**

```
Video → [HAS_SCENE] → Scene → [HAS_FRAME] → Frame
  │                      │                      │
  │── [HAS_CHAPTER] → Chapter              [CONTAINS] → Entity
  │                                             │
  └── [HAS_AUDIO] → AudioSegment          [INTERACTS_WITH, SIMILAR_TO, ...]
```

| Capacidad | Detalle |
|-----------|---------|
| Drivers | Dual sync/async Neo4j drivers |
| Connection pooling | Pool de conexiones gestionado |
| Batch operations | `UNWIND` para creación masiva |
| Schema | Constraints + indexes automáticos |
| Search | Entities, frames, transcripts, multimodal |
| Traversal | Context expansion (N-hop), entity timeline, subgraph |

#### EntityExtractor
**Extracción de entidades estructuradas de frames via GPT-4o vision.**

Tipos: `PERSON`, `OBJECT`, `LOCATION`, `ACTION`, `CONCEPT`, `TEXT` (OCR), `BRAND`, `EVENT`

- Confidence scores y bounding boxes
- Conversión a `EntityNode` para Neo4j
- Batch extraction para múltiples frames

#### RelationBuilder
**Construcción automática de relaciones en el Knowledge Graph.**

| Tipo de Relación | Método | Descripción |
|-----------------|--------|-------------|
| Co-ocurrencia | `build_cooccurrence_relations()` | Entidades en el mismo frame |
| Temporal | `build_temporal_relations()` | BEFORE/AFTER/DURING/SIMULTANEOUS |
| Semántica | `infer_semantic_relations()` | GPT-4o infiere relaciones |
| Cross-video | `find_cross_video_entities()` | Matching entre videos |

### 6.3 Servicios de Búsqueda

#### GraphSearchService (1092 líneas)
**Motor de búsqueda híbrida inspirado en VideoRAG.**

```
Query → ┌─ Vector Search (cosine similarity) ──┐
        │  Fulltext Search (Neo4j FTS)          ├──→ Signal Fusion → Reranking → Results
        │  Graph Proximity (N-hop scores)       │
        └─ Temporal Relevance ──────────────────┘
```

| Signal | Peso por defecto | Descripción |
|--------|-----------------|-------------|
| Vector | 0.4 | Cosine similarity con embeddings |
| Fulltext | 0.2 | Neo4j fulltext index (BM25-like) |
| Graph | 0.25 | Proximidad por travesía del grafo |
| Temporal | 0.15 | Relevancia temporal |

**Matryoshka Two-Stage Search:**
1. **Fase 1 (Coarse)**: Búsqueda con embeddings truncados a 512 dimensiones → candidatos rápidos
2. **Fase 2 (Fine)**: Re-ranking con embeddings completos de 3072 dimensiones → precisión

#### EnhancedSearchService
**Búsqueda avanzada con pipeline multi-etapa:**

```
Query → QueryAnalyzer (intent/entity via LLM) → Query Expansion
    → Hybrid Search (vector + BM25) → LLM Reranking
    → Scene-aware Context Expansion → Temporal Clustering
    → Scene Grouping → RAG Context Building
```

#### HierarchicalContextService (1234 líneas)
**RAG jerárquico para búsqueda multi-nivel.**

```
Video (embedding pooled) → Chapters → Scenes → Keyframes
              ↓                ↓          ↓          ↓
        drill_down_search: Video → Chapter → Scene → Frame (progressive)
```

- **Embedding pooling strategies**: Mean, Weighted, Max, Attention
- **Dimensionality reduction** en niveles superiores
- **Lazy loading** de nodos hijos

### 6.4 Servicios de Memoria y Artefactos

#### ToolArtifactService
**Almacenamiento durable de outputs de tools en 3 capas:**

```
               ┌─────────────┐
               │  Redis Hot   │  ← TTL 6h (fast reads)
               │   Cache      │
               └──────┬──────┘
                      │ miss
               ┌──────▼──────┐
               │  Azure Blob  │  ← gzip compressed, date-partitioned
               │   Storage    │
               └──────┬──────┘
                      │ metadata
               ┌──────▼──────┐
               │  PostgreSQL  │  ← artifact_id, checksums, timestamps
               │   Metadata   │
               └──────────────┘
```

- Gzip compression de payloads
- SHA-256 checksums para integridad
- Date-partitioned blob paths: `tool-artifacts/2026/02/13/{artifact_id}.json.gz`

#### Mem0MemoryService
**Memoria semántica de largo plazo (feature-flagged).**

- Wrapper sobre Mem0 SDK para resúmenes compactos
- Scoping por `user_id`, `session_id`, `media_id`, `project_id`
- Graceful degradation: retorna vacío si falla
- Async via `asyncio.to_thread` (SDK sync)

### 6.5 Servicios de Caché

#### CacheService (790 líneas)
**Caché multi-estrategia para reducir costos Azure OpenAI.**

| Tipo | TTL | Uso |
|------|-----|-----|
| Embedding | 7 días | Cachear embeddings generados |
| Frame Analysis | 24 horas | Cachear análisis GPT-4o de frames |
| Frame Hash | 30 días | Perceptual hashes para dedup |
| Search Result | 5 minutos | Cachear resultados de búsqueda |
| Job Status | 1 hora | Estado de jobs |
| Video Metadata | 12 horas | Metadatos de video |

**Técnicas:**
- **Cache-aside pattern**: `get_or_compute_embedding()`, `get_or_compute_frame_analysis()`
- **Perceptual hashing**: `imagehash` para detectar frames similares → dedup de análisis
- **Fallback in-memory**: `InMemoryCache` cuando Redis no está disponible
- **Invalidación en cascada**: `invalidate_video()` limpia todos los tipos de caché para un video

### 6.6 Servicios de Edición

#### ExportService (799 líneas)
**Exportación de clips con FFmpeg y subida a Azure Blob.**

- Corte de video, conversión de aspect ratio (crop/letterbox/blur fill)
- Quemado de subtítulos (ASS format)
- **Presets por plataforma**: TikTok (9:16, 1080x1920), Reels, Shorts, YouTube, Twitter
- **Calidades**: DRAFT (CRF 28), STANDARD (23), HIGH (18), MAX (12)
- Upload a Azure Blob Storage

#### SubtitleService (641 líneas)
**Generación y gestión de subtítulos estilo creator.**

| Estilo | Inspirado en | Características |
|--------|-------------|-----------------|
| HORMOZI | Alex Hormozi | Bold, uppercase, high contrast |
| MRBEAST | MrBeast | Colorful, animated, large |
| MINIMAL | Clean | Small, elegant, minimal |
| KARAOKE | Karaoke | Word-by-word highlight |
| NEWS | News | Lower third, formal |

- Timing word-level desde Whisper
- Outputs SRT y ASS (Advanced SubStation Alpha)

#### FaceTrackingService
**Detección y tracking facial para smart crop (16:9 → 9:16).**

Cascada de backends: MediaPipe (preferido) → OpenCV DNN → Haar Cascades

- Keyframe interpolation para crop animado suave
- Generación de filtros FFmpeg `crop` con keyframes

#### ViralScoreService
**Scoring de potencial viral para contenido short-form.**

Score compuesto con pesos:
- Hook strength (primeras palabras)
- Energy/pacing (densidad de palabras)
- Topic engagement (temas trending)
- Completeness (idea completa)
- Controversia (contenido polarizante)
- Duration score (longitud óptima)
- Visual features (caras, cambios de escena)

### 6.7 Otros Servicios

#### ChatService
RAG completo: carga resumen de Neo4j → búsqueda híbrida → contexto → GPT completion.

#### EmbeddingService
Azure OpenAI `text-embedding-3-large` (3072 dims) con:
- Content-hash caching
- Batch processing
- **Matryoshka truncation**: 3072 → 512 dims para filtrado rápido
- Retry con backoff exponencial (tenacity)

#### DatabaseService (712 líneas)
ORM PostgreSQL con SQLAlchemy:
- Connection pooling: `pool_size=10, max_overflow=20`
- Context-managed sessions
- CRUD completo: Users, Media, Jobs, BatchJobs, Projects, Clips, Artifacts

#### StorageTieringService
Gestión de tiers Azure Blob Storage:
- Hot → Cool → Cold → Archive (95% más barato)
- Recomendaciones automáticas basadas en patrones de acceso
- Rehidratación de Archive tier (Standard/High priority)

#### HierarchicalSummarizer
Resúmenes multi-nivel: Frame → Scene → Chapter → Video con GPT-4o.

---

## 7. Modelos de Datos (`models/`)

### 7.1 ORM — SQLAlchemy (`database.py`)

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│   UserModel  │────▶│  MediaModel  │────▶│   JobModel   │ (referencia)
│              │     │              │     └──────────────┘
│ id (UUID)    │     │ id (UUID)    │
│ email        │     │ user_id (FK) │     ┌──────────────┐
│ hashed_pass  │     │ blob_name    │     │ BatchJobModel│
│ full_name    │     │ media_type   │     │              │
│ is_active    │     │ file_size    │     │ azure_batch_id│
│ is_superuser │     │ processed    │     │ status       │
│ created_at   │     │ status       │     │ frames_count │
└──────────────┘     │ video_meta   │     │ cost         │
                     │ audio_data   │     └──────────────┘
                     │ storage_tier │
                     │ *_data_blob  │     ┌──────────────┐
                     └──────────────┘     │ProjectModel  │
                                          │              │
┌──────────────┐     ┌──────────────┐     │ user_id      │
│  ClipModel   │◀────│ProjectModel  │     │ source_media │
│              │     │              │     │ name, status │
│ project_id   │     │              │     └──────┬───────┘
│ start_time   │     └──────────────┘            │
│ end_time     │                            ┌────▼───────┐
│ title, order │                            │ ClipModel  │
│ subtitles_*  │                            └────────────┘
│ export_*     │
└──────────────┘     ┌────────────────────┐
                     │ToolArtifactModel   │
                     │                    │
                     │ artifact_id        │
                     │ thread_id          │
                     │ tool_name/call_id  │
                     │ blob_name          │
                     │ checksum_sha256    │
                     │ size_bytes         │
                     └────────────────────┘
```

**Offloading de datos pesados**: `MediaModel` usa campos `*_data_blob` para referenciar datos grandes en Azure Blob en vez de almacenarlos en PostgreSQL.

### 7.2 Knowledge Graph — Pydantic (`graph_models.py`)

#### Enums

| Enum | Valores |
|------|---------|
| `EntityType` | PERSON, OBJECT, LOCATION, ACTION, CONCEPT, TEXT, BRAND, EVENT |
| `RelationType` | CONTAINS, BELONGS_TO, BEFORE, AFTER, SIMILAR_TO, INTERACTS_WITH, SAME_ENTITY, TOPIC_OVERLAP, CO_OCCURS, HAS_ATTRIBUTE, PLAYS_ROLE, PERFORMS_ACTION, TRANSITION_TO |
| `NodeType` | VIDEO, CHAPTER, SCENE, FRAME, ENTITY, AUDIO_SEGMENT, TOPIC |

#### Nodos

```
GraphNodeBase (id, node_type, embedding, metadata, created_at)
├── VideoNode (video_id, title, description, duration, fps, resolution, topics, ai_summary)
├── ChapterNode (video_id, start_time, end_time, chapter_index, title, summary, topics)
├── SceneNode (video_id, chapter_id, start_time, end_time, scene_index, description)
├── FrameNode (video_id, scene_id, timestamp, frame_number, description, perceptual_hash)
├── AudioSegmentNode (video_id, start_time, end_time, text, language, speaker_id)
└── EntityNode (nombre, tipo, atributos)
```

### 7.3 API Schemas (`api_schemas.py`)

Schemas Pydantic para request/response de la API. Incluye:

- **Auth**: `RegisterRequest`, `LoginRequest`, `TokenResponse`, `UserResponse`
- **Chat**: `ChatRequest` (message, media_id, media_ids, chat_history), `ChatResponse`
- **Search**: `SearchRequest`, `SearchResponse` con `SearchResult`
- **Batch**: `BatchStatusResponse`, `CostEstimateResponse`
- **TypedDicts**: `ChatHistoryMessage`, `SourceReference`, `TokenUsage`, `EntityReference`

### 7.4 Editor Models (`editor.py`)

```
ProjectCreate → ProjectResponse (+ ProjectWithClips)
ClipCreate → ClipResponse
ClipSubtitleUpdate, ClipReorder
ExportFormat: TIKTOK, REELS, SHORTS, YOUTUBE, TWITTER
SubtitleStyle: HORMOZI, MRBEAST, MINIMAL, KARAOKE, NEWS
```

### 7.5 Export Config (`export_config.py`)

Configuración detallada de exportación con presets por plataforma:

| Plataforma | Aspect Ratio | Resolución | Max Duración | CropMode |
|-----------|-------------|-----------|-------------|----------|
| TikTok | 9:16 | 1080×1920 | 180s | FACE_TRACK |
| Reels | 9:16 | 1080×1920 | 90s | FACE_TRACK |
| Shorts | 9:16 | 1080×1920 | 60s | CENTER |
| YouTube | 16:9 | 1920×1080 | - | NONE |
| Twitter | 16:9 | 1280×720 | 140s | CENTER |

### 7.6 FFmpeg Config (`ffmpeg_config.py`)

Configuración declarativa de procesamiento FFmpeg:

- `FrameExtractionMethod`: FPS, INTERVAL, KEYFRAMES, SCENE_DETECT, UNIFORM, ADAPTIVE, HYBRID
- `ProcessingPreset`: FAST_PREVIEW, BALANCED, HIGH_QUALITY, KEYFRAMES_ONLY, SCENE_ANALYSIS
- Support para hardware acceleration, filter chains, pixel formats

### 7.7 A2A Models (`a2a_models.py`)

Implementación completa del protocolo A2A v1.0:
- `TaskState`: SUBMITTED → WORKING → COMPLETED/FAILED/CANCELED
- `AgentCard`, `AgentSkill`, `AgentCapabilities`
- `Message`, `Part`, `Artifact`, `Task`
- Request/Response types para messaging y streaming

---

## 8. Procesamiento Asíncrono (`tasks/`)

### 8.1 Celery (`celery_app.py`)

| Configuración | Valor |
|--------------|-------|
| Broker | Redis |
| Result Backend | Redis |
| Serializer | json |
| Task retry | 3 intentos, backoff exponencial |
| Rate limiting | Azure OpenAI throttling |
| Priority | Support de prioridades |
| TLS | Azure Redis con `rediss://` + SSL |

```bash
celery -A tasks.celery_app worker --loglevel=info
```

### 8.2 Pipeline de Video (`video_tasks.py`)

Cadena de Celery tasks orquestada:

```
process_video_pipeline (orchestrator)
    │
    ├─→ download_video_task        # Descargar de Azure Blob
    ├─→ extract_frames_task        # FFmpeg frame extraction
    ├─→ analyze_frames_task        # GPT-4o vision (batch API)
    ├─→ generate_embeddings_task   # text-embedding-3-large (parallel)
    ├─→ transcribe_audio_task      # Whisper con chunking
    ├─→ index_to_neo4j             # Indexar en Knowledge Graph
    ├─→ index_transcription_to_graph  # Indexar transcripción
    └─→ cleanup_task               # Limpiar archivos temporales
```

- **Lazy loading** de servicios para evitar imports pesados al cargar el módulo
- **WebSocket events**: Cada tarea publica progreso via Redis Pub/Sub → WebSocket

---

## 9. Pipeline de Procesamiento de Video

### Flujo Completo

```
                    Upload
                      │
                      ▼
┌─────────────────────────────────────────────┐
│            Azure Blob Storage                │
│         (almacenamiento de media)            │
└──────────────────┬──────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────┐
│         Frame Extraction (FFmpeg)             │
│  • Auto-detect hardware accel (CUDA/QSV)     │
│  • Métodos: Uniform, Scene, Hybrid           │
│  • Presets: fast/balanced/quality             │
└──────────────────┬──────────────────────────┘
                   │
          ┌────────┴────────┐
          ▼                 ▼
┌──────────────┐   ┌──────────────────┐
│ Vision (GPT) │   │ Audio (Whisper)   │
│              │   │                    │
│ Batch API    │   │ VAD chunking      │
│ 50% savings  │   │ Rate limiting     │
│              │   │ Speaker ID        │
│ Adaptive     │   │                    │
│ token budget │   │ Enriched analysis │
└──────┬───────┘   └────────┬──────────┘
       │                     │
       ▼                     ▼
┌──────────────────────────────────────────────┐
│           Entity Extraction (GPT-4o)          │
│  PERSON, OBJECT, LOCATION, TEXT, BRAND...     │
│  + confidence scores + bounding boxes         │
└──────────────────┬───────────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────────┐
│      Embedding Generation (batch)             │
│  text-embedding-3-large (3072 dims)           │
│  + Matryoshka truncation (512 dims)           │
│  + Content-hash caching                       │
└──────────────────┬───────────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────────┐
│       Knowledge Graph Indexing (Neo4j)        │
│  Nodes: Video, Scene, Frame, Entity, Audio    │
│  Relations: temporal, co-occurrence, semantic  │
│  Vector indexes para búsqueda                 │
└──────────────────────────────────────────────┘
```

### Optimizaciones de Costo

| Técnica | Ahorro | Detalle |
|---------|--------|---------|
| Batch API | ~50% | Azure Global Batch pricing |
| Perceptual hash dedup | Variable | Skip frames visualmente similares |
| Adaptive token budget | ~20-30% | Menos tokens para frames simples |
| Matryoshka embeddings | ~40% búsqueda | Filtrado rápido con 512 dims |
| Content-hash caching | Variable | Evitar re-computación |
| Storage tiering | Hasta 95% | Archive tier para media antigua |

---

## 10. Knowledge Graph (Neo4j)

### 10.1 Schema

```cypher
-- Nodos
(:Video {media_id, title, description, duration_seconds, topics, ai_summary, embedding})
(:Chapter {video_id, chapter_index, start_time, end_time, title, summary, topics, embedding})
(:Scene {video_id, scene_index, start_time, end_time, description, embedding})
(:Frame {video_id, timestamp, frame_number, description, perceptual_hash, embedding})
(:AudioSegment {video_id, start_time, end_time, text, language, speaker_id, embedding})
(:Entity {name, type, description, attributes, embedding})
(:Topic {name, description, embedding})

-- Relaciones jerárquicas
(v:Video)-[:HAS_CHAPTER]->(ch:Chapter)
(v:Video)-[:HAS_SCENE]->(s:Scene)
(ch:Chapter)-[:CONTAINS_SCENE]->(s:Scene)
(s:Scene)-[:HAS_FRAME]->(f:Frame)
(v:Video)-[:HAS_AUDIO]->(a:AudioSegment)
(f:Frame)-[:CONTAINS]->(e:Entity)

-- Relaciones temporales
(s1:Scene)-[:BEFORE]->(s2:Scene)
(s1:Scene)-[:AFTER]->(s2:Scene)
(f1:Frame)-[:NEXT]->(f2:Frame)

-- Relaciones semánticas
(e1:Entity)-[:SIMILAR_TO]->(e2:Entity)
(e1:Entity)-[:INTERACTS_WITH]->(e2:Entity)
(e1:Entity)-[:CO_OCCURS {count, frames}]->(e2:Entity)
(e:Entity)-[:SAME_ENTITY]->(e2:Entity)  -- Cross-video

-- Relaciones de topic
(v:Video)-[:HAS_TOPIC]->(t:Topic)
(v1:Video)-[:TOPIC_OVERLAP {shared_topics}]->(v2:Video)
```

### 10.2 Indexes

```cypher
-- Vector indexes (Neo4j 5.x)
CREATE VECTOR INDEX frame_embedding FOR (f:Frame) ON (f.embedding)
    OPTIONS {indexConfig: {`vector.dimensions`: 3072, `vector.similarity_function`: 'cosine'}}

CREATE VECTOR INDEX frame_coarse_embedding FOR (f:Frame) ON (f.coarse_embedding)
    OPTIONS {indexConfig: {`vector.dimensions`: 512, `vector.similarity_function`: 'cosine'}}

-- Fulltext indexes
CREATE FULLTEXT INDEX frame_description FOR (f:Frame) ON EACH [f.description]
CREATE FULLTEXT INDEX audio_text FOR (a:AudioSegment) ON EACH [a.text]
CREATE FULLTEXT INDEX entity_name FOR (e:Entity) ON EACH [e.name]
```

### 10.3 Jerarquía para RAG

```
Video (embedding pooled de chapters)
  └── Chapter (embedding pooled de scenes)
        └── Scene (embedding pooled de frames/audio)
              └── Frame (embedding individual)
              └── AudioSegment (embedding individual)
```

**Drill-down search**: Busca en video → refina en chapter → detalla en scene → precisión en frame.

---

## 11. Sistema de Búsqueda Híbrida

### Pipeline Completo

```
User Query
    │
    ▼
┌─── Query Analysis ───────────────────────────┐
│  • Intent detection (search/compare/explore)  │
│  • Entity extraction                          │
│  • Query expansion (synonyms, related terms)  │
└──────────────────┬────────────────────────────┘
                   │
    ┌──────────────┼──────────────┐
    ▼              ▼              ▼
┌────────┐  ┌──────────┐  ┌──────────┐
│ Vector │  │ Fulltext  │  │  Graph   │
│ Search │  │  Search   │  │Traversal │
│ (Neo4j)│  │ (Neo4j    │  │ (N-hop)  │
│        │  │  FTS)     │  │          │
└───┬────┘  └────┬─────┘  └────┬─────┘
    │             │             │
    └──────┬──────┘──────┬──────┘
           │             │
           ▼             ▼
    ┌────────────┐ ┌──────────────┐
    │  Temporal   │ │Signal Fusion │
    │ Relevance   │ │  (weighted)  │
    └──────┬─────┘ └──────┬───────┘
           │              │
           └──────┬───────┘
                  ▼
         ┌───────────────┐
         │  LLM Reranking │
         │   (optional)    │
         └────────┬────────┘
                  ▼
         ┌───────────────┐
         │Context-aware   │
         │  Expansion     │
         └────────┬───────┘
                  ▼
         ┌───────────────┐
         │  Temporal      │
         │  Clustering    │
         └────────┬───────┘
                  ▼
            Final Results
```

### Pesos de Señales (Configurables)

```python
DEFAULT_WEIGHTS = {
    "vector": 0.4,      # Cosine similarity
    "fulltext": 0.2,    # BM25-like text match
    "graph": 0.25,      # Graph proximity
    "temporal": 0.15,   # Temporal relevance
}
```

### Matryoshka Two-Stage Search

```
Stage 1 (Coarse - 512 dims):
  Query embedding truncado → búsqueda en coarse_embedding index
  → Top-100 candidatos rápidos

Stage 2 (Fine - 3072 dims):
  Re-ranking con embeddings completos
  → Top-K resultados precisos
```

---

## 12. Arquitectura de Memoria del Agente

### Capas de Memoria

```
┌───────────────────────────────────────────────────────┐
│                  Prompt-Time Context                    │
│                                                         │
│  1. Hybrid Candidate Collection                         │
│     ├── Local memory (conversation_context)            │
│     ├── Mem0 semantic memories (top_k=5)               │
│     └── Artifact refs (tool output summaries)          │
│                                                         │
│  2. Lightweight Reranking                               │
│     ├── Lexical overlap with query terms               │
│     ├── Semantic score                                  │
│     └── Recency bias                                    │
│                                                         │
│  3. Dynamic Context Budget                              │
│     ├── Base: 1200 chars (standard queries)            │
│     └── Detail: 2200 chars (precision queries)         │
│                                                         │
│  4. Selective Artifact Rehydration                      │
│     ├── Max 2 artifacts per turn                        │
│     ├── Max 3500 chars total                            │
│     └── Only for detail-heavy/precision queries        │
└───────────────────────────────────────────────────────┘

┌───────────────────────────────────────────────────────┐
│              Storage Layers                             │
│                                                         │
│  Checkpointer (thread-scoped)                          │
│  ├── Full message history                               │
│  ├── Resume/retry continuity                           │
│  └── PostgreSQL → Redis → MemorySaver                  │
│                                                         │
│  Artifact Storage (ToolArtifactService)                 │
│  ├── Redis hot cache (TTL 6h)                          │
│  ├── Azure Blob (gzipped, date-partitioned)            │
│  └── PostgreSQL (metadata + checksums)                 │
│                                                         │
│  Semantic Memory (Mem0, feature-flagged)                │
│  ├── Compact summaries                                  │
│  ├── User/session/media scoped                         │
│  └── Cloud or self-hosted                              │
└───────────────────────────────────────────────────────┘
```

### Detection de Queries que Requieren Detalle

```python
detail_hints = ("exact", "specific", "detail", "timestamp", "timecode",
                "quote", "verbatim", "full", "complete", "all results", "evidence")
```

---

## 13. Sistema de Caché Multinivel

```
┌──────────────────────────────────────────┐
│           CacheService                    │
│                                           │
│  ┌─── Redis (primary) ───────────────┐   │
│  │  Embeddings     │ TTL: 7 days     │   │
│  │  Frame Analysis │ TTL: 24 hours   │   │
│  │  Frame Hash     │ TTL: 30 days    │   │
│  │  Search Results │ TTL: 5 minutes  │   │
│  │  Job Status     │ TTL: 1 hour     │   │
│  │  Video Metadata │ TTL: 12 hours   │   │
│  └────────────────────────────────────┘   │
│                                           │
│  ┌─── InMemoryCache (fallback) ──────┐   │
│  │  LRU con TTL cuando Redis no      │   │
│  │  está disponible                   │   │
│  └────────────────────────────────────┘   │
│                                           │
│  Técnicas especiales:                     │
│  • Perceptual hashing (pHash) para       │
│    detectar frames similares             │
│  • Cache-aside pattern                    │
│  • Cascade invalidation por video        │
│  • Métricas: hits, misses, savings ($)   │
└──────────────────────────────────────────┘
```

### Perceptual Hash Dedup

```python
# Computa hash perceptual de frame
phash = cache_service.compute_perceptual_hash(frame_image)

# Busca frame similar ya analizado (threshold=8 bits Hamming)  
existing = cache_service.find_similar_frame(phash, media_id)

if existing:
    return existing["analysis"]  # Skip análisis GPT-4o → ahorro $
```

---

## 14. Chat-to-Edit (Editor de Video)

### Flujo de Edición Conversacional

```
Usuario: "Create a 30s highlight clip starting from when the speaker says 'innovation'"

    │
    ▼
┌─── Editor Agent ────────────────────────────────┐
│                                                   │
│  1. search_video("innovation", audio) → t=45.3s │
│  2. get_scene_context(45.3) → context             │
│  3. create_clip(45.3, 75.3, "Innovation")         │
│     ↪ [INTERRUPT: HITL confirmation]             │
│     ↪ User confirms                              │
│  4. add_subtitles(clip_id, style="HORMOZI")      │
│     ↪ [INTERRUPT: HITL confirmation]             │
│     ↪ User confirms                              │
│                                                   │
│  Response: "Created 30s clip with subtitles..."   │
└───────────────────────────────────────────────────┘
```

### Arquitectura del Export Pipeline

```
Source Video (Azure Blob)
    │
    ▼
Download → FFmpeg Clip → Aspect Ratio Conversion → Subtitle Burning → Encoding → Upload
                              │                         │
                         ┌────┴────┐              ┌─────┴──────┐
                         │ Modes:  │              │ ASS Format │
                         │ Center  │              │ Word-level │
                         │ Face    │              │ timing     │
                         │ Track   │              │ (Whisper)  │
                         │ Letter  │              └────────────┘
                         │ box     │
                         │ Blur    │
                         │ Fill    │
                         └─────────┘
```

---

## 15. Protocolo A2A (Agent-to-Agent)

### Implementación

QPrisma expone sus agentes como servidores A2A v1.0 compatibles:

```
A2A Client ──→ a2a_routes.py ──→ A2AAgentExecutor ──→ LangGraph Agent
                                        │
                                   TaskStore (in-memory)
                                        │
                                   Task Lifecycle:
                                   SUBMITTED → WORKING → COMPLETED/FAILED
```

### Agent Cards (Descubrimiento)

```json
GET /.well-known/agent-card.json

{
  "name": "QPrisma Video Agent",
  "description": "Intelligent video analysis...",
  "url": "https://qprisma.example.com",
  "capabilities": {
    "streaming": true,
    "pushNotifications": false,
    "stateTransitionHistory": true
  },
  "skills": [
    {"id": "video-search", "name": "Video Search", ...},
    {"id": "video-analysis", "name": "Video Analysis", ...}
  ]
}
```

### Streaming SSE

```
POST /a2a/message:stream

data: {"type": "status", "task_id": "...", "state": "working"}
data: {"type": "artifact", "text": "The video shows..."}
data: {"type": "artifact", "text": "at timestamp [2:34]..."}
data: {"type": "status", "state": "completed"}
```

---

## 16. Autenticación y Seguridad

### JWT Flow

```
Register/Login → AuthService → bcrypt hash → PostgreSQL
    │
    ▼
JWT Access Token (24h) + Refresh Token (30d)
    │
    ▼
Every Request → HTTPBearer → verify_token → User object
```

### Validaciones

| Check | Detalle |
|-------|---------|
| Password | Mín 8 chars, mayúscula, minúscula, dígito |
| JWT Secret | Min 32 chars en producción |
| Default creds | Falla hard en producción si detecta defaults |
| Multi-tenant | `user_id` scoping en todas las queries |
| CORS | Configurable, strict en producción |

### Dependency Injection

```python
@router.get("/items")
async def list_items(current_user: User = Depends(get_current_user)):
    # current_user validado automáticamente
    # 401 si token inválido/expirado
```

---

## 17. Observabilidad y Métricas

### Request Context Propagation

```python
@dataclass
class RequestContext:
    request_id: str       # UUID corto para correlation
    user_id: str | None
    session_id: str | None
    media_id: str | None
    project_id: str | None
    start_time: float
    node_path: list[str]  # Path de nodos ejecutados
    tool_calls: list[dict]
    errors: list[dict]
```

Propagado vía `ContextVar` a través de toda la ejecución del grafo.

### Métricas Prometheus-style

```python
class Metrics:
    # Counters + Histograms para:
    # - model_calls: total, tokens, latencia
    # - tool_calls: por herramienta, éxito/error
    # - memory_retrieval: latencia, items
    # - artifact_rehydration: count, chars
    # - search: latencia, resultados
```

### Logging Estructurado

```python
from agent.utils.observability import get_logger, Metrics

logger = get_logger(__name__)  # Con correlation IDs
logger.info("Processing started", extra={"media_id": "123", "frames": 20})

# NUNCA usar print() en runtime paths
```

---

## 18. Patrones de Diseño

### 18.1 Singleton con Lazy Init

```python
_service: MyService | None = None

def get_my_service() -> MyService:
    global _service
    if _service is None:
        _service = MyService()
    return _service
```

Usado en: 13 servicios + todos los clientes Azure.

### 18.2 Cache-Aside Pattern

```python
async def get_or_compute_embedding(text: str) -> list[float]:
    cached = await cache.get_embedding(hash(text))
    if cached:
        return cached
    
    embedding = await openai.create_embedding(text)
    await cache.set_embedding(hash(text), embedding, ttl=7*24*3600)
    return embedding
```

### 18.3 Graceful Degradation

Las herramientas del agente **nunca lanzan excepciones**:

```python
@tool
async def my_tool(...) -> dict:
    try:
        result = await do_work()
        return {"results": result, "count": len(result)}
    except Exception as e:
        return {"error": str(e), "results": [], "count": 0}
```

### 18.4 Service Layer Extraction

```
Route Handler (thin)
    ↓ delegates to
Service (business logic)
    ↓ uses
Data Access (DatabaseService, KnowledgeGraphService)
```

### 18.5 Input/Output Schema Separation

```python
workflow = StateGraph(
    AgentState,                    # Full internal state
    input_schema=AgentInputState,  # Clean API input
    output_schema=AgentOutputState # Filtered output
)
```

### 18.6 Retry con Clasificación de Errores

```python
RETRYABLE:     ConnectionError, TimeoutError, 503, 429, "rate limit"
NON-RETRYABLE: ValueError, TypeError, KeyError, PermissionError
```

### 18.7 Three-Tier Storage

```
Hot (Redis) → Warm (Azure Blob gzipped) → Cold (PostgreSQL metadata)
```

### 18.8 Matryoshka Embeddings

```
3072 dims (full) ─── para ranking preciso
  ↓ truncate
512 dims (coarse) ── para filtrado rápido
```

### 18.9 Perceptual Hashing para Dedup

```
Frame → pHash (8x8 DCT) → Hamming distance → threshold=8 → dedup
```

---

## 19. Dependencias y Stack Tecnológico

### Core Framework

| Paquete | Versión | Uso |
|---------|---------|-----|
| FastAPI | ≥0.115 | Web framework async |
| Uvicorn | ≥0.32 | ASGI server |
| Pydantic | ≥2.10 | Validación + Settings |
| SQLAlchemy | ≥2.0 | ORM PostgreSQL |

### AI / ML

| Paquete | Versión | Uso |
|---------|---------|-----|
| LangGraph | ≥1.0.7 | Agent orchestration |
| langchain-core | ≥1.2.8 | Tools, messages, runnables |
| langchain-openai | ≥1.1.7 | AzureChatOpenAI wrapper |
| openai | ≥1.55 | Azure OpenAI SDK |
| mem0ai | ≥1.0.3 | Semantic memory |

### Datos

| Paquete | Versión | Uso |
|---------|---------|-----|
| neo4j | ≥5.26 | Knowledge Graph driver |
| redis | ≥5.2 | Cache + queue |
| psycopg2-binary | ≥2.9.9 | PostgreSQL adapter |
| celery | ≥5.4 | Distributed tasks |

### Media Processing

| Paquete | Versión | Uso |
|---------|---------|-----|
| opencv-python-headless | ≥4.10 | Procesamiento de imagen |
| ffmpeg-python | ≥0.2 | FFmpeg binding |
| pillow | ≥11.0 | Manipulación de imagen |
| imagehash | ≥4.3 | Perceptual hashing |

### Utilidades

| Paquete | Versión | Uso |
|---------|---------|-----|
| tenacity | ≥9.0 | Retry logic |
| httpx | ≥0.28 | HTTP client async |
| python-jose | ≥3.5 | JWT tokens |
| passlib+bcrypt | ≥1.7 | Password hashing |
| aiofiles | ≥24.1 | Async file I/O |
| a2a-sdk | ≥0.3.22 | A2A protocol |
| yt-dlp | ≥2026.2.4 | Video download |

### Dev Dependencies

| Paquete | Uso |
|---------|-----|
| pytest + pytest-asyncio | Testing (asyncio_mode="auto") |
| pytest-cov + pytest-xdist | Coverage + parallel |
| ruff | Linting (py311, line-length=100) |
| black | Formatting |
| hypothesis | Property-based testing |
| mutmut | Mutation testing |

---

## 20. Diagramas de Flujo

### 20.1 Request Flow (Chat con Video)

```
Client POST /chat
    │
    ▼
┌── auth middleware ──→ get_current_user() ──→ User
    │
    ▼
┌── chat_routes.py ──────────────────────────────────┐
│  1. Validar ChatRequest (media_id, message)         │
│  2. Cargar video context desde PostgreSQL            │
│  3. Crear AgentInputState                            │
│  4. Invocar VideoAgentGraph.astream_events()         │
└──┬──────────────────────────────────────────────────┘
   │
   ▼
┌── LangGraph Execution ─────────────────────────────┐
│                                                     │
│  call_model:                                        │
│    ├── Load system prompt (video-aware)             │
│    ├── Retrieve hybrid memory context               │
│    │   ├── Local conversation_context               │
│    │   ├── Mem0 search_memories()                   │
│    │   └── Artifact refs (scored + ranked)          │
│    ├── Selectively rehydrate artifacts              │
│    ├── Trim messages (max 80k tokens)               │
│    ├── Dynamic tool selection (max 8 tools)         │
│    └── AzureChatOpenAI.invoke()                     │
│                                                     │
│  tools (ToolNode):                                  │
│    ├── search_video() → GraphSearchService          │
│    │   └── hybrid_search() → Neo4j                  │
│    ├── get_transcript() → KnowledgeGraphService     │
│    └── describe_scene() → KnowledgeGraphService     │
│                                                     │
│  update_context:                                    │
│    ├── Extract topics from messages                  │
│    ├── Save artifacts (ToolArtifactService)         │
│    └── Update conversation_context                   │
│                                                     │
│  → Repeat until no tool calls or max iterations     │
│                                                     │
│  error_handler (if needed):                         │
│    └── Return partial_results + apology             │
└──┬──────────────────────────────────────────────────┘
   │
   ▼
┌── Response Assembly ───────────────────────────────┐
│  1. Extract metadata from messages                   │
│     (sources, navigation, clips, entities)           │
│  2. Parse suggested questions                        │
│  3. Return ChatResponse (SSE stream or JSON)         │
└──────────────────────────────────────────────────────┘
```

### 20.2 Video Processing Pipeline

```
POST /jobs/submit {media_id}
    │
    ▼
┌── Celery Task Chain ───────────────────────────────┐
│                                                     │
│  1. download_video_task                             │
│     └── Azure Blob → local temp file                │
│                                                     │
│  2. extract_frames_task                             │
│     └── FFmpeg (hwaccel) → frames/{n}.jpg           │
│                                                     │
│  3. analyze_frames_task                             │
│     ├── Build JSONL batch payloads                  │
│     ├── Azure Batch API submit                      │
│     ├── Poll until complete                         │
│     ├── Parse structured JSON results               │
│     └── Entity extraction (GPT-4o vision)           │
│                                                     │
│  4. generate_embeddings_task                        │
│     ├── text-embedding-3-large (batch)              │
│     ├── Content-hash caching (skip existing)        │
│     └── Matryoshka truncation (3072→512)            │
│                                                     │
│  5. transcribe_audio_task                           │
│     ├── Extract audio (FFmpeg)                      │
│     ├── Chunk if >25MB (VAD split points)           │
│     ├── Whisper transcription (rate limited)        │
│     └── GPT-4o analysis (speakers, topics)          │
│                                                     │
│  6. index_to_neo4j                                  │
│     ├── Video node                                  │
│     ├── Scene/Frame/Entity nodes (batch UNWIND)     │
│     ├── Relations (temporal, co-occurrence)          │
│     ├── Semantic relations (GPT-4o inferred)        │
│     └── Vector indexes                              │
│                                                     │
│  7. index_transcription_to_graph                    │
│     └── AudioSegment nodes + relations              │
│                                                     │
│  8. cleanup_task                                    │
│     └── Remove temp files                           │
│                                                     │
│  Progress → Redis Pub/Sub → WebSocket → Frontend    │
└─────────────────────────────────────────────────────┘
```

### 20.3 Hierarchical RAG Search

```
User Query: "What does the speaker say about AI?"
    │
    ▼
┌── Level 1: Video ────────────────────────┐
│  vector_search(query, VideoNode)          │
│  → Top 3 videos by relevance             │
└──┬───────────────────────────────────────┘
   │
   ▼
┌── Level 2: Chapter ──────────────────────┐
│  vector_search(query, ChapterNode,        │
│               filter=video_id)            │
│  → Top 5 chapters by relevance            │
└──┬───────────────────────────────────────┘
   │
   ▼
┌── Level 3: Scene ────────────────────────┐
│  vector_search(query, SceneNode,          │
│               filter=chapter_id)          │
│  → Top 10 scenes by relevance             │
└──┬───────────────────────────────────────┘
   │
   ▼
┌── Level 4: Frame/Audio ──────────────────┐
│  hybrid_search(query,                     │
│    [FrameNode, AudioSegmentNode],         │
│    filter=scene_id)                       │
│  → Exact moments with timestamps          │
└──────────────────────────────────────────┘
```

---

## Apéndice: Variables de Entorno

### Requeridas

| Variable | Descripción |
|----------|-------------|
| `AZURE_OPENAI_ENDPOINT` | Azure OpenAI endpoint |
| `AZURE_OPENAI_API_KEY` | Azure OpenAI API key |
| `AZURE_STORAGE_CONNECTION_STRING` | Azure Blob Storage |
| `DATABASE_URL` | PostgreSQL connection URL |
| `NEO4J_URI` | Neo4j bolt:// URI |
| `NEO4J_PASSWORD` | Neo4j password |
| `REDIS_URL` | Redis URL |
| `JWT_SECRET_KEY` | JWT signing secret (min 32 chars) |

### Opcionales

| Variable | Default | Descripción |
|----------|---------|-------------|
| `AZURE_OPENAI_DEPLOYMENT_GPT` | `gpt-4o` | Deployment name |
| `AZURE_OPENAI_DEPLOYMENT_EMBEDDING` | `text-embedding-3-large` | Embedding model |
| `AZURE_OPENAI_DEPLOYMENT_WHISPER` | `whisper` | Whisper deployment |
| `AZURE_OPENAI_DEPLOYMENT_GPT_BATCH` | - | Batch API deployment |
| `MEM0_ENABLED` | `false` | Enable Mem0 memory |
| `MEM0_API_KEY` | - | Mem0 Cloud API key |
| `MEM0_TOP_K` | `5` | Memory retrieval top-k |
| `ARTIFACT_CACHE_TTL_SECONDS` | `21600` | Artifact cache TTL |
| `APP_ENV` | `dev` | Environment (dev/prod) |
| `LOG_LEVEL` | `INFO` | Logging level |
| `DISABLE_STARTUP_HEALTHCHECKS` | `false` | Skip startup checks |
| `DISABLE_REDIS_PUBSUB` | `false` | Skip Redis Pub/Sub |

---

> **Nota**: Esta documentación refleja el estado del backend a Febrero 2026. Para cambios recientes, consultar el [CHANGELOG.md](../CHANGELOG.md).
