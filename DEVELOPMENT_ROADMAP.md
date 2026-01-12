# QPrisma Development Roadmap

> Plan de evolución para convertir QPrisma en una plataforma de procesamiento multimedia escalable, eficiente y cloud-native en Azure.

**Inspirado en:** [VideoRAG (HKUDS)](https://github.com/HKUDS/VideoRAG) - Framework de RAG para video con indexación por grafos de conocimiento.

**Fecha de inicio:** Enero 2026
**Última actualización:** 12 Enero 2026
**Estado actual:** Fase 3.8 En Progreso - Mejoras de Procesamiento de Video

---

## Progreso General

```
Fase 1: Fundamentos de Escalabilidad  [████████████████████] 100% ✅
Fase 2: Knowledge Graph RAG           [████████████████████] 100% ✅
  └─ 2.4: VideoRAG Improvements       [████████████████████] 100% ✅
Fase 3: Optimización de Costos        [████████████████████] 100% ✅
  └─ 3.1: Batch API Integration       [████████████████████] 100% ✅
  └─ 3.2: Code Cleanup                [████████████████████] 100% ✅
  └─ 3.3: Database Fixes              [████████████████████] 100% ✅
  └─ 3.4: Frontend UX Redesign        [████████████████████] 100% ✅
  └─ 3.7: Agentic Chat System         [████████████████████] 100% ✅
  └─ 3.8: Video Processing Upgrades   [████████████░░░░░░░░]  60% 🔄
Fase 4: Observabilidad                [░░░░░░░░░░░░░░░░░░░░]   0%
Fase 5: Escalabilidad Horizontal      [░░░░░░░░░░░░░░░░░░░░]   0%
Fase 6: Features Avanzadas            [░░░░░░░░░░░░░░░░░░░░]   0%
```

---

## Resumen Ejecutivo

### Visión
Transformar QPrisma de un procesador de video basado en frames a una plataforma de **Video RAG inteligente** con:
- Grafos de conocimiento multimodales
- Procesamiento jerárquico escalable (100+ horas de video)
- Búsqueda semántica avanzada con re-ranking
- Arquitectura cloud-native optimizada para Azure

### Estado Actual vs. Objetivo

| Capacidad | Inicio | Actual (Fase 2.4 Completa) | Objetivo Final |
|-----------|--------|--------------------------|----------------|
| Procesamiento | Frame-by-frame | **Scene-based + Hierarchical** | Scene-based + Knowledge Graph ✅ |
| Escalabilidad | Videos individuales | **100+ horas con drill-down** | 100+ horas, multi-video ✅ |
| Búsqueda | Vector search | **VideoRAG Hybrid Search** | Hybrid + Graph + Re-ranking ✅ |
| Latencia | Minutos | Segundos (cached) | <50ms |
| Costo | $0.50-2.00/min | ~40% reducción | $0.10-0.30/min |
| Updates | Polling | **WebSocket real-time** | WebSocket + Push ✅ |
| Knowledge Graph | ❌ | **Full Graph RAG con Jerarquía** | Full Graph RAG ✅ |
| Audio Embeddings | ❌ | **AudioSegment vectors** | Multimodal embeddings ✅ |

---

## ✅ Fase 1: Fundamentos de Escalabilidad (COMPLETADA)

**Estado:** ✅ COMPLETADA (8 Enero 2026)

### 1.1 Sistema de Caching Distribuido (Redis) ✅

**Implementado:**
- [x] Docker Compose con Redis 7 Alpine
- [x] `CacheService` con múltiples estrategias de caching
- [x] Cache de embeddings por hash de contenido
- [x] Cache de análisis de frames con perceptual hashing
- [x] Deduplicación de frames similares (pHash)
- [x] TTL configurable por tipo de contenido
- [x] Fallback a memoria cuando Redis no está disponible
- [x] Métricas de cache hit/miss
- [x] API endpoints para gestión del cache
- [x] `CachedVideoProcessor` wrapper

**Archivos creados:**
```
backend/
├── services/
│   ├── cache_service.py          # Core del sistema de cache
│   └── cached_video_processor.py # VideoProcessor con cache
├── models/
│   └── cache_models.py           # Modelos Pydantic
├── api/
│   └── cache_routes.py           # Endpoints REST
└── tests/
    └── test_cache_service.py     # Tests + demo
docker-compose.yml                 # Redis + Redis Commander
```

**Endpoints disponibles:**
- `GET /cache/metrics` - Métricas de rendimiento
- `GET /cache/health` - Health check
- `POST /cache/invalidate` - Invalidar cache
- `DELETE /cache/video/{id}` - Limpiar cache de video

---

### 1.2 Cola de Tareas con Celery ✅

**Implementado:**
- [x] Configuración de Celery con Redis como broker
- [x] Pipeline completo de procesamiento de video
- [x] Task chains para orquestación
- [x] Retry policy con exponential backoff
- [x] Rate limiting para proteger Azure OpenAI
- [x] Colas con prioridades (video_processing, fast_tasks, default)
- [x] Docker Compose con Celery worker
- [x] Flower dashboard para monitoreo
- [x] API endpoints para gestión de jobs

**Archivos creados:**
```
backend/
├── tasks/
│   ├── __init__.py
│   ├── celery_app.py             # Configuración Celery
│   └── video_tasks.py            # Tasks de procesamiento
├── api/
│   └── jobs_routes.py            # Endpoints de jobs
├── tests/
│   └── test_celery_tasks.py      # Tests
└── Dockerfile.worker             # Container para worker
```

**Endpoints disponibles:**
- `POST /jobs/submit` - Enviar video a procesar
- `GET /jobs/{job_id}` - Estado del job
- `POST /jobs/{job_id}/cancel` - Cancelar job
- `GET /jobs/` - Listar jobs
- `GET /jobs/stats/summary` - Estadísticas

**Comandos:**
```bash
# Iniciar con worker
docker-compose --profile worker up -d

# URLs
# - Flower: http://localhost:5555 (admin/qprisma123)
# - Redis Commander: http://localhost:8081
```

---

### 1.3 WebSockets para Actualizaciones en Tiempo Real ✅

**Implementado:**
- [x] `ConnectionManager` para gestión de conexiones
- [x] Endpoints WebSocket por job, usuario y broadcast
- [x] Integración con Celery tasks (notificaciones automáticas)
- [x] Redis Pub/Sub para múltiples instancias de API
- [x] Heartbeat para mantener conexiones vivas
- [x] Hook React `useJobWebSocket` para frontend
- [x] Reconexión automática con backoff

**Archivos creados:**
```
backend/
├── api/
│   ├── websocket_manager.py      # Gestión de conexiones
│   └── websocket_routes.py       # Endpoints WebSocket
└── tests/
    └── test_websocket.py         # Tests + demo interactivo

frontend/
└── hooks/
    └── useWebSocket.ts           # Hook React
```

**Endpoints WebSocket:**
- `ws://localhost:8000/ws/jobs/{job_id}` - Seguir job específico
- `ws://localhost:8000/ws/user/{user_id}` - Jobs de usuario
- `ws://localhost:8000/ws/all` - Todos los updates (admin)

**Uso en Frontend:**
```tsx
import { useJobWebSocket } from '@/hooks/useWebSocket';

const { progress, stage, isConnected } = useJobWebSocket(jobId, {
  onCompleted: (result) => console.log('Done!', result),
});
```

---

## ✅ Fase 2: Knowledge Graph RAG (COMPLETADA)

**Estado:** ✅ COMPLETADA (9 Enero 2026) | **Inspirado en:** VideoRAG

### ✅ 2.1 Grafo de Conocimiento Multimodal (COMPLETADA)

**Estado:** ✅ COMPLETADA (9 Enero 2026)

**Decisión técnica:** Se eligió **Neo4j** en lugar de Cosmos DB Gremlin por:
- Cypher más intuitivo que Gremlin para queries complejas
- Vector search nativo (evita mantener AI Search separado)
- Mejor rendimiento en traversals profundos (4+ hops)
- Integración directa con frameworks RAG (LangChain, etc.)

**Arquitectura del grafo:**
```
                    ┌─────────────┐
                    │   Video     │
                    └──────┬──────┘
                           │
           ┌───────────────┼───────────────┐
           │               │               │
     ┌─────▼─────┐   ┌─────▼─────┐   ┌─────▼─────┐
     │  Scenes   │   │   Audio   │   │  Topics   │
     └─────┬─────┘   └─────┬─────┘   └─────┬─────┘
           │               │               │
     ┌─────▼─────┐   ┌─────▼─────┐   ┌─────▼─────┐
     │  Frames   │   │ Segments  │   │ Concepts  │
     └─────┬─────┘   └───────────┘   └───────────┘
           │
     ┌─────▼─────┐
     │ Entities  │ (personas, objetos, lugares, acciones)
     └───────────┘
```

**Implementado:**
- [x] Neo4j 5-community en Docker Compose
- [x] `KnowledgeGraphService` con driver oficial de Neo4j
- [x] Modelos Pydantic completos (`graph_models.py`)
- [x] `EntityExtractor` con GPT-4o Vision
- [x] `RelationBuilder` para relaciones temporales y semánticas
- [x] Relaciones: CONTAINS, BEFORE, AFTER, DURING, APPEARS_WITH, INTERACTS_WITH, etc.
- [x] Full-text search con índices
- [x] Graph expansion para contexto RAG
- [x] API endpoints completos (`/graph/*`)
- [x] Tests y demo interactivo

**Archivos creados:**
```
backend/
├── services/
│   ├── knowledge_graph.py      # Core del KG con Neo4j
│   ├── entity_extractor.py     # Extracción con GPT-4o
│   └── relation_builder.py     # Constructor de relaciones
├── models/
│   └── graph_models.py         # Modelos Pydantic completos
├── api/
│   └── graph_routes.py         # Endpoints REST
└── tests/
    └── test_knowledge_graph.py # Tests + demo
docker-compose.yml              # + Neo4j container
```

**Endpoints disponibles:**
- `GET /graph/health` - Health check de Neo4j
- `GET /graph/stats` - Estadísticas del grafo
- `POST /graph/initialize` - Inicializar schema
- `POST /graph/search/entities` - Búsqueda de entidades
- `POST /graph/search/frames` - Búsqueda en frames
- `POST /graph/search/advanced` - Búsqueda con graph expansion
- `POST /graph/expand` - Expandir contexto de un nodo
- `POST /graph/timeline` - Timeline de una entidad
- `POST /graph/extract/frame` - Extraer entidades de imagen
- `GET /graph/video/{id}` - Obtener subgrafo de video
- `DELETE /graph/video/{id}` - Eliminar grafo de video

**Comandos:**
```bash
# Iniciar Neo4j
docker-compose up -d neo4j

# URLs
# - Neo4j Browser: http://localhost:7474 (neo4j/qprisma123)
# - Bolt: bolt://localhost:7687

# Tests
cd backend
python tests/test_knowledge_graph.py --demo
```

---

### ✅ 2.2 Graph-Enhanced Retrieval (COMPLETADA)

**Estado:** ✅ COMPLETADA (9 Enero 2026)

**Objetivo:** Búsqueda que combina similitud vectorial con traversal de grafo.

**Algoritmo implementado:**
```
1. Query → Embedding (Azure OpenAI text-embedding-3-large)
2. Vector search → Top-K candidatos (Neo4j vector index)
3. Para cada candidato:
   a. Expandir vecinos en grafo (configurable hops)
   b. Calcular relevancia contextual
   c. Full-text matching con boost
4. Combinar scores con pesos configurables:
   - Vector: 0.4 (similitud semántica)
   - Fulltext: 0.2 (keyword matching)
   - Graph: 0.25 (centralidad y conexiones)
   - Temporal: 0.15 (proximidad temporal)
5. Re-ranking con contexto expandido
6. Retornar resultados ordenados con metadata
```

**Implementado:**
- [x] `EmbeddingService` - Azure OpenAI text-embedding-3-large (3072 dims)
- [x] Batch embedding generation con rate limiting
- [x] Cache de embeddings por hash de contenido
- [x] Vector indexes en Neo4j para búsqueda rápida
- [x] `GraphSearchService` - Servicio de búsqueda híbrida
- [x] Scoring híbrido con pesos configurables
- [x] Re-ranking con expansión de contexto
- [x] Temporal awareness en scoring
- [x] Cross-video entity matching
- [x] API endpoints completos
- [x] Tests y demo interactivo

**Archivos creados:**
```
backend/
├── services/
│   ├── embedding_service.py      # Azure OpenAI embeddings
│   └── graph_search_service.py   # Búsqueda híbrida
├── api/
│   └── graph_routes.py           # + nuevos endpoints
└── tests/
    └── test_graph_search.py      # Tests de búsqueda
```

**Endpoints nuevos:**
- `POST /graph/search/hybrid` - Búsqueda híbrida (vector + graph + fulltext)
- `POST /graph/search/cross-video` - Búsqueda entre múltiples videos
- `POST /graph/embeddings/initialize` - Crear índices vectoriales en Neo4j
- `POST /graph/embeddings/generate` - Generar embeddings en bulk
- `GET /graph/embeddings/stats` - Estadísticas del servicio de embeddings

**Configuración de pesos:**
```python
DEFAULT_WEIGHTS = {
    "vector": 0.4,      # Similitud semántica
    "fulltext": 0.2,    # Keyword matching
    "graph": 0.25,      # Centralidad y conexiones
    "temporal": 0.15,   # Proximidad temporal
}
```

**Comandos:**
```bash
# Tests de Graph Search
cd backend
python tests/test_graph_search.py --check      # Verificar servicios
python tests/test_graph_search.py --embeddings # Probar embeddings
python tests/test_graph_search.py --demo       # Demo completo
```

---

### ✅ 2.3 Hierarchical Context Encoding (COMPLETADA)

**Estado:** ✅ COMPLETADA (9 Enero 2026)

**Objetivo:** Representar videos largos (100+ horas) eficientemente con jerarquía multinivel.

**Jerarquía implementada:**
```
Video (1 embedding + summary)
  └── Chapters (N embeddings + summaries)
        └── Scenes (M embeddings + summaries)
              └── Keyframes (K embeddings + descriptions)
```

**Implementado:**
- [x] `HierarchicalContextService` - Servicio completo de encoding jerárquico
- [x] Estrategias de pooling de embeddings (MEAN, WEIGHTED_MEAN, MAX_POOL)
- [x] Compresión de embeddings a dimensiones menores (3072 → 1024/512)
- [x] Generación de embeddings en cada nivel (video, chapter, scene)
- [x] Almacenamiento jerárquico en Neo4j Knowledge Graph
- [x] Búsqueda drill-down (video → chapter → scene)
- [x] Lazy loading de niveles inferiores
- [x] Navegación breadcrumb (path from root)
- [x] API endpoints completos
- [x] Tests y demo interactivo

**Archivos creados:**
```
backend/
├── services/
│   └── hierarchical_context_service.py  # Servicio completo
├── api/
│   └── graph_routes.py                  # + endpoints jerárquicos
└── tests/
    └── test_hierarchical_context.py     # Tests de jerarquía
```

**Endpoints nuevos:**
- `POST /graph/hierarchy/process` - Procesar jerarquía completa de video
- `POST /graph/hierarchy/search/drill-down` - Búsqueda jerárquica drill-down
- `POST /graph/hierarchy/children` - Carga lazy de hijos
- `GET /graph/hierarchy/stats/{video_id}` - Estadísticas de jerarquía
- `GET /graph/hierarchy/path/{node_id}` - Ruta desde raíz (breadcrumb)

**Configuración:**
```python
HierarchicalConfig(
    scene_threshold=0.3,           # Detección de escenas
    max_scenes_per_chapter=5,      # Agrupación de chapters
    pool_strategy=WEIGHTED_MEAN,   # Pooling de embeddings
    compress_chapter_embeddings=False,
    compressed_dimensions=1024,    # Si se habilita compresión
)
```

**Comandos:**
```bash
# Tests de Hierarchical Context
cd backend
python tests/test_hierarchical_context.py --check      # Verificar servicios
python tests/test_hierarchical_context.py --embeddings # Probar embeddings
python tests/test_hierarchical_context.py --demo       # Demo completo
```

---

### ✅ 2.4 VideoRAG-Style Improvements (COMPLETADA)

**Estado:** ✅ COMPLETADA (10 Enero 2026)

**Objetivo:** Implementar mejoras inspiradas en VideoRAG para búsqueda semántica multimodal.

**Mejoras implementadas:**

1. **AudioSegment Embeddings**
   - Generación de embeddings para transcripciones de audio
   - Vector index `audiosegment_embedding` en Neo4j
   - Búsqueda semántica en contenido hablado

2. **VideoRAG-style Hybrid Search**
   - Chat y Search ahora usan `hybrid_search()` en lugar de keyword matching
   - Combina 4 señales de relevancia:
     - Vector similarity (40%) - embeddings semánticos
     - Fulltext matching (20%) - keywords
     - Graph proximity (25%) - conexiones en el grafo
     - Temporal relevance (15%) - proximidad temporal

3. **UI Mejorada para Sources**
   - Iconos distintivos por tipo de fuente (Visual 👁️, Audio 🎤, Entity 🏷️)
   - Colores por tipo (Azul/Verde/Púrpura)
   - Score de relevancia mostrado como porcentaje
   - Input del chat con texto visible (corregido)

**Archivos modificados:**
```
backend/
├── services/
│   └── graph_search_service.py    # + AudioSegment vector index
├── api/
│   ├── dependencies.py            # + get_graph_search_service()
│   └── routes/
│       ├── chat_routes.py         # Usa hybrid_search()
│       └── graph_routes.py        # AudioSegment text field fix

frontend/
└── app/video/[id]/page.tsx        # UI mejorada para sources
```

**Uso:**
```bash
# Generar embeddings para AudioSegments
POST /graph/embeddings/generate
{
  "node_type": "AudioSegment",
  "batch_size": 50
}

# Búsqueda híbrida automática en chat
POST /chat
{
  "message": "What happens with Dragon SpaceX?",
  "media_id": "video-id"
}
```

---

## Fase 3: Optimización de Costos Azure

**Prioridad:** MEDIA-ALTA
**Estado:** 🔄 EN PROGRESO (40%)

### 3.1 Batch API Integration ✅ COMPLETADO (10-11 Enero 2026)

**Implementado:**
- [x] `BatchProcessor` simplificado - siempre usa Batch API (50% ahorro)
- [x] Integración con Celery worker (`process_video_pipeline`)
- [x] Integración con API routes (`process_video_ffmpeg`)
- [x] `BatchJobModel` en PostgreSQL para tracking
- [x] API endpoints para gestión de batch:
  - `GET /batch/status/{id}` - Estado del job
  - `GET /batch/jobs` - Lista de jobs del usuario
  - `POST /batch/cancel/{id}` - Cancelar job pendiente
  - `GET /batch/cost-summary` - Resumen de costos
  - `GET /batch/estimate` - Estimación de costos
- [x] Configuración via environment variables:
  ```bash
  AZURE_OPENAI_DEPLOYMENT_GPT_BATCH=gpt-4o-global-batch
  ```

**Nota:** Requiere un deployment tipo "Global Batch" en Azure OpenAI Studio para el 50% de descuento.

### 3.2 Code Cleanup ✅ COMPLETADO (11 Enero 2026)

**Código eliminado (~300 líneas):**

**video_processor.py:**
- [x] `delete_video()` - no se usaba
- [x] `process_video()` - legacy, reemplazado por `process_video_ffmpeg()`
- [x] `process_image()` - legacy, no se usaba
- [x] `_process_with_parallel()` - nunca se llamaba (Batch API único path)
- [x] `_process_single_frame_no_embedding()` - solo usado por método eliminado
- [x] `_process_objects()` - stub deshabilitado
- [x] Imports no usados: `io`, `ThreadPoolExecutor`, `as_completed`

**batch_processor.py:**
- [x] `submit_batch_job_tracked()` - no se usaba
- [x] `sync_batch_status()` - no se usaba
- [x] Imports no usados: `datetime`, `timedelta`

**processing_routes.py:**
- [x] Eliminado parámetro `use_batch_api` (siempre usa Batch)

**Docker optimizations (sesión anterior):**
- [x] Agregados `.dockerignore` para frontend y backend
- [x] Eliminadas dependencias pesadas: `ultralytics`, `transformers[torch]`, `langchain*`
- [x] Cambiado `opencv-python` → `opencv-python-headless`
- [x] **Reducción de imagen Docker:** 8.5GB → 1.1GB (87%)

### 3.3 Database Fixes ✅ COMPLETADO (11 Enero 2026)

- [x] Renombrado `metadata` → `batch_metadata` en `BatchJobModel` (SQLAlchemy reserved)
- [x] Agregado `session.expunge()` a todos los métodos de database_service
- [x] Agregada columna `audio_data` (JSON) en `MediaModel` para transcripciones
- [x] Fixed auth flow para auto-crear usuarios demo en PostgreSQL
- [x] Fixed frontend: `full_name` → `name` en registro

### 3.4 Frontend UX Redesign ✅ COMPLETADO (11 Enero 2026)

**Inspirado en:** [Vimo Desktop](https://github.com/HKUDS/VideoRAG/tree/main/Vimo-desktop) - Chat-centric video analysis UI

**Nuevo diseño implementado:**

1. **Layout de 3 Columnas**
   - Sidebar (280px): Selector de modo, conversaciones, perfil
   - Main Content (flex): Chat o Upload
   - Video Panel (40%): Player, chapters, transcript

2. **Dos Modos de Chat**
   - **Single Video**: Chat con un video específico
   - **Library Mode**: Búsqueda semántica en toda la biblioteca

3. **Componentes Creados:**
   ```
   frontend/components/
   ├── layout/
   │   ├── Sidebar.tsx          # Navegación y modo selector
   │   ├── VideoPanel.tsx       # Player con chapters/transcript
   │   └── AppLayout.tsx        # Layout wrapper
   ├── chat/
   │   ├── WelcomeScreen.tsx    # Pantalla inicial con sugerencias
   │   ├── MessageList.tsx      # Lista de mensajes con timestamps
   │   ├── ChatInput.tsx        # Input con attachments
   │   ├── ChatContainer.tsx    # Lógica principal del chat
   │   └── TimestampBadge.tsx   # Badges clickeables
   ├── upload/
   │   ├── UploadZone.tsx       # Drag & drop upload
   │   ├── ProcessingCard.tsx   # Progreso en tiempo real (7 pasos)
   │   └── ProcessingStep.tsx   # Paso individual
   └── library/
       ├── VideoCard.tsx        # Thumbnail de video
       └── VideoGrid.tsx        # Grid con búsqueda/filtros
   ```

4. **Páginas Nuevas:**
   - `/chat` - Nueva conversación con selector de video
   - `/chat/[id]` - Conversación existente
   - `/library` - Biblioteca de videos
   - `/upload` - Página dedicada de upload

5. **WebSocket Real-Time Updates:**
   - ProcessingCard con 7 pasos visuales de procesamiento
   - Conexión WebSocket para eventos de Celery
   - Fallback polling cada 5 segundos si WebSocket falla
   - Mapeo de stages backend → frontend (downloading → upload, etc.)

6. **Fixes Críticos:**
   - [x] NEXT_PUBLIC_* env vars baked at Docker build time
   - [x] Stage name mapping (backend uses Spanish, frontend English)
   - [x] Structure API response parsing (`structure.structure.scenes`)
   - [x] Redis Pub/Sub → WebSocket event propagation
   - [x] Celery tasks use sync Redis (no async event loop issues)

**Archivos de diseño:**
- `FRONTEND_UX_REDESIGN.md` - Documento de diseño completo

### 3.5 Storage Tiering Automático (Pendiente)
- [ ] Lifecycle policies en Blob Storage
- [ ] Metadata tracking de último acceso
- [ ] Rehydration automático

### 3.6 Embedding Deduplication (Pendiente)
- [ ] Perceptual hashing mejorado (ya implementado básico)
- [ ] Índice de hashes en Redis
- [ ] Métricas de deduplication savings

### 3.7 Agentic Chat System ✅ COMPLETADO

**Objetivo:** Transformar el chat de un simple RAG a un sistema agentic inteligente que puede razonar, planificar y usar múltiples herramientas.

**Inspiración:** LangGraph patterns (StateGraph, ReAct loop, tool calling)

**Implementación:**

1. **Arquitectura del Agente:**
   ```
   User Message → Agent (GPT-4o) → Tool Calls → Execute → Agent → Response
                        ↑                           ↓
                        └───────────────────────────┘
   ```

2. **Estructura de Archivos:**
   ```
   backend/agent/
   ├── __init__.py          # Exports VideoAgent, VideoAgentState
   ├── state.py             # TypedDict state, AgentConfig
   ├── prompts.py           # System prompts
   ├── video_agent.py       # Main agent with ReAct loop
   ├── memory.py            # Redis-backed conversation memory
   └── tools/
       ├── __init__.py      # ALL_TOOLS, TOOL_DEFINITIONS
       ├── base.py          # BaseTool class with OpenAI schema
       ├── search_tools.py  # search_video, find_entity
       ├── navigation_tools.py  # get_transcript, describe_scene
       ├── structure_tools.py   # list_chapters, get_video_info, get_summary
       └── graph_tools.py   # get_related_content, navigate_timeline
   ```

3. **9 Herramientas Disponibles:**
   | Tool | Descripción |
   |------|-------------|
   | `search_video` | Búsqueda híbrida (vector + fulltext + graph) |
   | `find_entity` | Encontrar personas, objetos, conceptos |
   | `get_transcript` | Obtener transcripción de un rango de tiempo |
   | `describe_scene` | Descripción visual detallada de un timestamp |
   | `list_chapters` | Listar capítulos/secciones del video |
   | `get_video_info` | Información básica del video |
   | `get_summary` | Resumen a nivel video, capítulo o rango |
   | `get_related_content` | Explorar relaciones en el Knowledge Graph |
   | `navigate_timeline` | Navegar a un punto específico del video |

4. **Características Clave:**
   - **ReAct Loop:** El agente decide qué herramientas usar basado en la pregunta
   - **Max Iterations:** Límite de 5 iteraciones para evitar loops infinitos
   - **Session Memory:** Persistencia de conversaciones en Redis
   - **Tool Definitions:** Schema OpenAI function calling
   - **Dynamic Model:** Usa `AZURE_OPENAI_DEPLOYMENT_GPT` env var

5. **Nuevo Endpoint:** `POST /chat/agent`
   ```json
   // Request
   {
     "message": "Search for AI in this video",
     "media_id": "uuid",
     "chat_history": [...],
     "session_id": "uuid"  // optional, for memory
   }
   
   // Response
   {
     "response": "I found AI mentioned at [2:34]...",
     "sources": [...],
     "tool_calls_made": 2,
     "session_id": "uuid"
   }
   ```

6. **Streaming Endpoint:** `POST /chat/agent/stream`
   Server-Sent Events (SSE) streaming for real-time responses:
   ```
   Event Types:
   - session    → { session_id: "uuid" }
   - thinking   → { iteration: 0 }
   - tool_start → { tool: "search_video", tool_call_id: "..." }
   - tool_end   → { tool: "search_video", success: true }
   - token      → { token: "word" }  // Streaming response
   - sources    → { sources: [...] }
   - done       → { response: "...", sources: [...], tool_calls_made: 2 }
   - error      → { error: "..." }
   ```

7. **Frontend Integration:**
   - Streaming response display in ChatContainer
   - Active tools indicator with status badges
   - Session memory persistence
   - Real-time token streaming

8. **Tests:** 12 tests passing
   - Tool definitions validation
   - State management
   - Agent loop with mocked LLM
   - Tool execution
   - Memory operations

9. **Bug Fix (v0.11.1):** Corregido acceso a transcripciones
   - Las herramientas `get_transcript` y `describe_scene` usaban queries incorrectas
   - AudioSegments usan relación `:HAS_TRANSCRIPT` (no `:CONTAINS`)
   - AudioSegments usan campos `start_time`/`end_time` (no `timestamp`)
   - El agente ahora puede acceder correctamente al contenido hablado

---

## Fase 4: Observabilidad y Operaciones

**Prioridad:** MEDIA

- [ ] Azure Application Insights
- [ ] Custom metrics con OpenTelemetry
- [ ] Dashboard en Azure Monitor
- [ ] Alertas automáticas
- [ ] Structured logging con correlation IDs
- [ ] Health checks profundos
- [ ] Circuit breaker para servicios externos

---

## Fase 5: Escalabilidad Horizontal

**Prioridad:** MEDIA

- [ ] Dockerfile optimizado (multi-stage build)
- [ ] Kubernetes manifests (AKS)
- [ ] Helm chart
- [ ] Horizontal Pod Autoscaler
- [ ] Multi-region deployment
- [ ] Azure Front Door

---

## Fase 6: Características Avanzadas

**Prioridad:** BAJA

- [ ] Streaming video processing
- [ ] Multi-modal conversations
- [ ] Collaborative features
- [ ] Anotaciones compartidas

---

## Fase 3.8: Mejoras de Procesamiento de Video (EN PROGRESO)

**Prioridad:** ALTA
**Fecha inicio:** 12 Enero 2026

### Objetivos
Mejorar la calidad y configurabilidad del procesamiento de video, especialmente para videos largos (>1 hora).

### 3.8.1 Extracción Adaptativa por Duración ✅

**Implementado:**
- [x] Nuevo método de extracción `ADAPTIVE` que ajusta automáticamente según duración
- [x] Función `get_adaptive_config(duration)` que calcula parámetros óptimos:
  - < 5 min: 1 frame/2s, max 150 frames
  - 5-30 min: 1 frame/3s, max 400 frames
  - 30-60 min: Modo HYBRID, max 600 frames
  - 1-2 hrs: Modo HYBRID, max 800 frames
  - > 2 hrs: Modo HYBRID con scene detection, max 1000 frames

### 3.8.2 Modo Híbrido (Scene Detection + Uniform Fill) ✅

**Implementado:**
- [x] Nuevo método `HYBRID` que combina lo mejor de ambos mundos
- [x] Fase 1: Detecta cambios de escena (captura transiciones importantes)
- [x] Fase 2: Rellena gaps largos con frames uniformes (no perder contenido estático)
- [x] Parámetros configurables:
  - `hybrid_scene_ratio`: Proporción escenas vs fill (default 0.6)
  - `hybrid_min_gap_seconds`: Gap mínimo antes de insertar fill frames (default 10s)
- [x] Función `_calculate_hybrid_timestamps()` implementada
- [x] Función `_detect_scene_timestamps()` para detección de escenas con FFmpeg

### 3.8.3 Nuevos Presets de Procesamiento ✅

**Implementado:**
- [x] `DEEP_ANALYSIS`: Para videos largos, máxima cobertura (1000 frames, modo híbrido)
- [x] `INTERVIEW_MODE`: Prioriza audio, menos frames visuales (1 frame/10s, 200 max)
- [x] `ACTION_MODE`: Más frames en escenas con movimiento (threshold 0.2, 800 frames)
- [x] `ADAPTIVE`: Preset que usa `get_adaptive_config()` automáticamente

### 3.8.4 Métricas de Cobertura ✅

**Implementado:**
- [x] Función `calculate_coverage_metrics()` que analiza calidad de extracción
- [x] Métricas calculadas:
  - `coverage_score`: 0-100, qué tan bien cubierto está el video
  - `average_gap`: Gap promedio entre frames
  - `max_gap`: Gap máximo (indica posibles "puntos ciegos")
  - `gaps_over_threshold`: Lista de gaps problemáticos
  - `density_per_minute`: Frames por minuto
- [x] Thresholds dinámicos según duración del video
- [x] Recomendaciones automáticas para mejorar cobertura
- [x] Función `get_recommended_preset()` para sugerir preset óptimo

### 3.8.5 Two-Pass Processing (PENDIENTE)

**Por implementar:**
- [ ] Pass 1 (rápido): Análisis de estructura + audio transcription
- [ ] Pass 2 (selectivo): Extracción de más frames en escenas importantes
- [ ] Identificar escenas con mucho diálogo vs visuales
- [ ] Priorizar frames en momentos clave detectados en Pass 1

### 3.8.6 Mejoras Futuras (Inspiradas en Edconv)

**Ideas de [Edconv](https://github.com/edneyosf/Edconv) para futuras versiones:**
- [ ] **VMAF Analysis**: Métricas de calidad de video perceptual
- [ ] **PSNR/SSIM**: Análisis de calidad frame-by-frame
- [ ] **Queue System**: Cola de jobs visualizable con progreso en tiempo real
- [ ] **Custom FFmpeg Arguments**: Permitir argumentos FFmpeg personalizados
- [ ] **Codec Selection**: Soporte para H.265/HEVC, VP9, AV1
- [ ] **HDR Processing**: Conversión HDR→SDR mejorada
- [ ] **Audio Normalization**: Normalización de audio con loudnorm
- [ ] **Batch Processing**: Procesar múltiples videos en cola
- [ ] **Format Detection**: Auto-detección de formato óptimo de salida

### Archivos Modificados

```
backend/
├── models/
│   └── ffmpeg_config.py           # Nuevos métodos y presets
├── services/
│   └── ffmpeg_processor.py        # Lógica híbrida y métricas
```

---

## Cómo Ejecutar (Estado Actual)

### Desarrollo Básico
```bash
# 1. Iniciar Redis + PostgreSQL + Neo4j
docker-compose up -d redis postgres neo4j

# 2. Iniciar API
cd backend
python api/main.py

# 3. Iniciar Frontend
cd frontend
npm run dev
```

### Con Procesamiento Async
```bash
# 1. Iniciar todo (Redis + PostgreSQL + Neo4j + Worker + Flower)
docker-compose --profile worker up -d

# 2. Iniciar API
cd backend
python api/main.py

# URLs:
# - API: http://localhost:8000/docs
# - Flower: http://localhost:5555
# - Neo4j Browser: http://localhost:7474
# - Frontend: http://localhost:3000
```

### Tests
```bash
cd backend

# Cache
python tests/test_cache_service.py

# Celery
python tests/test_celery_tasks.py --check

# WebSocket
python tests/test_websocket.py --interactive
```

---

## Arquitectura Actual (Post Fase 2.4 + Migración PostgreSQL)

```
┌─────────────────────────────────────────────────────────────────┐
│                         FRONTEND                                 │
│                     (Next.js + React)                           │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────┐ │
│  │   Upload    │  │   Search    │  │   useJobWebSocket Hook  │ │
│  └──────┬──────┘  └──────┬──────┘  └────────────┬────────────┘ │
└─────────┼────────────────┼──────────────────────┼───────────────┘
          │                │                      │ WebSocket
          ▼                ▼                      ▼
┌─────────────────────────────────────────────────────────────────┐
│                        FASTAPI                                   │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────────┐│
│  │  /upload │  │ /search  │  │  /jobs   │  │    /graph/*      ││
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────────┬─────────┘│
│       │             │             │                  │          │
│       ▼             ▼             ▼                  ▼          │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │                    SERVICE LAYER                             ││
│  │  VideoProcessor │ CacheService │ KnowledgeGraph │ Database  ││
│  └─────────────────────────────────────────────────────────────┘│
└─────────┬───────────────┬───────────────┬───────────────┬───────┘
          │               │               │               │
          ▼               ▼               ▼               ▼
┌─────────────────┐ ┌───────────┐ ┌─────────────┐ ┌─────────────┐
│  CELERY WORKER  │ │   REDIS   │ │   NEO4J     │ │ POSTGRESQL  │
│  ┌───────────┐  │ │  ┌─────┐  │ │ Knowledge   │ │  (Metadata) │
│  │video_tasks│  │ │  │Cache│  │ │   Graph     │ └─────────────┘
│  └───────────┘  │ │  ├─────┤  │ │             │
│                 │ │  │Queue│  │ │ Entities    │ ┌─────────────┐
│  Rate Limited   │ │  ├─────┤  │ │ Relations   │ │ AZURE BLOB  │
│  Retry Policy   │ │  │WS PS│  │ │ Traversal   │ │  STORAGE    │
└────────┬────────┘ │  └─────┘  │ └─────────────┘ └──────┬──────┘
         │          └─────┬─────┘                        │
         └────────────────┘                              │
              Broker                              ┌──────▼──────┐
                                                  │ AZURE OPENAI│
                                                  │ (GPT-4o)    │
                                                  └─────────────┘
```

**Cambios Fase 2.5 (Migración de Base de Datos):**
- ✅ PostgreSQL reemplaza Cosmos DB (ahorro ~80% en costos)
- ✅ SQLAlchemy como ORM
- ✅ Modelos: UserModel, MediaModel, JobModel
- ✅ Eliminado azure-cosmos de dependencias
- ✅ Eliminado Azure AI Search (redundante con Neo4j vector search)

---

## Changelog

| Fecha | Versión | Cambios |
|-------|---------|---------|
| 2026-01-11 | 0.11.1 | **Audio/Transcript Fix**: Corregida query de AudioSegments usando `:HAS_TRANSCRIPT` relationship y campos `start_time`/`end_time` en navigation_tools.py |
| 2026-01-11 | 0.11.0 | **Streaming Integration**: SSE endpoint `/chat/agent/stream`, frontend streaming display, active tools indicator, real-time tokens |
| 2026-01-11 | 0.10.0 | **Fase 3.7 Completada**: Agentic Chat System con 9 herramientas, ReAct loop, session memory Redis, endpoint `/chat/agent`, 12 tests |
| 2026-01-11 | 0.9.0 | **Fase 3.4 Completada**: Frontend UX Redesign inspirado en Vimo, layout 3 columnas, ProcessingCard con WebSocket real-time, chat modes, video panel con chapters/transcript |
| 2026-01-11 | 0.8.0 | **Fase 3 Progress**: Batch API en Celery, limpieza de código (~300 líneas), Docker 87% más pequeño, fix transcripciones, fix auth |
| 2026-01-10 | 0.7.0 | **Migración PostgreSQL**: Reemplazo de Cosmos DB por PostgreSQL, eliminación de Azure AI Search, SQLAlchemy ORM |
| 2026-01-10 | 0.6.0 | **Fase 2.4 Completada**: VideoRAG-style Hybrid Search, AudioSegment Embeddings, UI mejorada para sources |
| 2026-01-09 | 0.5.0 | **Fase 2.3 Completada**: Hierarchical Context Encoding, Drill-down Search, Lazy Loading, Embedding Pooling |
| 2026-01-09 | 0.4.0 | **Fase 2.2 Completada**: Graph-Enhanced Retrieval, Hybrid Search, Embeddings Service, Cross-video Search |
| 2026-01-09 | 0.3.0 | **Fase 2.1 Completada**: Neo4j Knowledge Graph, Entity Extraction, Relation Builder |
| 2026-01-08 | 0.2.0 | **Fase 1 Completada**: Redis Cache, Celery Tasks, WebSockets |
| 2026-01-08 | 0.1.0 | Documento inicial con roadmap |

---

## Próxima Sesión

**Continuar con:** Fase 4 - Observabilidad y Operaciones

**Tareas sugeridas:**
1. Integrar frontend con nuevo endpoint `/chat/agent`
2. Implementar Azure Application Insights para telemetría
3. Agregar OpenTelemetry para tracing distribuido
4. Dashboard de métricas en Azure Monitor
5. Lifecycle policies en Azure Blob Storage (Fase 3.5)

**Preparación:**
1. Tener servicios corriendo: `docker-compose --profile full up -d`
2. Frontend accesible en: http://localhost:3000/chat
3. API docs en: http://localhost:8000/docs

**Nuevo endpoint para probar:**
```bash
# Test agentic chat
curl -X POST http://localhost:8000/chat/agent \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"message": "Search for AI topics", "media_id": "<video-uuid>"}'
```

**Resumen Fase 3.7 Completada:**
```
✅ Fase 3.1: Batch API Integration
   - BatchProcessor simplificado (siempre Batch)
   - Integración con Celery worker
   - API endpoints para gestión

✅ Fase 3.2: Code Cleanup
   - Eliminadas ~300 líneas de código duplicado/no usado
   - Docker images 87% más pequeñas (8.5GB → 1.1GB)
   - Eliminadas dependencias pesadas (PyTorch, langchain)

✅ Fase 3.3: Database Fixes
   - SQLAlchemy session management
   - Audio transcription storage
   - Auth flow fixes

✅ Fase 3.4: Frontend UX Redesign
   - Layout 3 columnas inspirado en Vimo Desktop
   - ProcessingCard con WebSocket real-time (7 pasos)
   - Two chat modes: Single Video / Library
   - Video Panel con chapters, transcript, scenes
   - Celery → Redis Pub/Sub → WebSocket pipeline

✅ Fase 3.7: Agentic Chat System
   - VideoAgent con ReAct loop
   - 9 herramientas especializadas
   - Session memory en Redis
   - SSE streaming + frontend integration
   - **Fix v0.11.1**: Acceso correcto a transcripciones (AudioSegments)

⏳ Fase 3.5: Storage Tiering (pendiente)
⏳ Fase 3.6: Embedding Deduplication (pendiente)
```

---

*Este documento es un plan vivo que será actualizado conforme avance el desarrollo.*
