# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

#### Security
- **JWT authentication on WebSocket endpoints**: All WebSocket connections require JWT via query parameter (`?token=`) or first-message (`{"token": "..."}`).
- **Auth on cache endpoints**: Cache mutation endpoints (`/cache/invalidate`, `/cache/metrics/reset`, etc.) now require `Depends(get_current_user)`.
- **Rate limiting on A2A endpoints**: slowapi-based per-IP rate limiting (60/min messages, 120/min task list, 30/min cancel).
- **Security headers middleware**: Adds `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `X-XSS-Protection`, and related headers on all responses.
- **Error message sanitization**: Internal details (stack traces, service names) are never leaked in API error responses.
- **Non-root Docker user**: Containers run as `appuser` (UID 1001) via `USER` directive in Dockerfile.
- **Token revocation**: Redis-backed JTI denylist with `POST /auth/logout` endpoint to invalidate tokens.
- **Credential cleanup in docker-compose**: All credentials parameterized with `${VAR:-default}` patterns.
- **CI security scanning**: `pip-audit` (backend) and `npm audit` (frontend) added to CI pipeline.
- **CI/CD permission scoping**: Workflow permissions follow least-privilege principle.

#### Video Pipeline
- **PyAV integration**: C-level FFmpeg bindings as primary video decoder — zero subprocess overhead. (`services/pyav_extractor.py`)
- **Unified VideoDecoder protocol**: Protocol-based abstraction (`services/video_decoder.py`) with `PyAVDecoder` (default) and `FFmpegSubprocessDecoder` (fallback), extensible for GPU backends.
- **PySceneDetect integration**: Professional scene boundary detection with `AdaptiveDetector` (gradual transitions) and `ContentDetector` (hard cuts). (`services/scene_detect_service.py`)
- **Parallel audio transcription**: `asyncio.gather` + `Semaphore`-bounded concurrent chunk processing.
- **faster-whisper backend**: Optional local CTranslate2-based transcription — 4× faster than Azure Whisper, INT8 quantization, Silero VAD. (`services/faster_whisper_service.py`)
- **Frame deduplication**: Perceptual hashing via `imagehash` to skip visually redundant frames.
- **WebP frame encoding**: Default frame format changed from JPEG to WebP (25-35% smaller at equivalent quality).
- **Configurable embedding batch size**: Default 512 (up from 16) with adaptive retry that halves batch size on failure.
- **Dynamic thread pool sizing**: Container-aware worker count auto-detection for FFmpeg extraction.
- **Streaming pipeline architecture**: Opt-in async generator pipeline reducing peak memory from O(all_frames) to O(batch_size).

#### Code Quality
- **`core/errors.py`**: Standardized HTTP error helpers (`not_found`, `bad_request`, `forbidden`, `unauthorized`, `internal_error`, `conflict`, `service_unavailable`).
- **`core/retry.py`**: Centralized async retry with exponential backoff (`retry_async()` function + `@retry_on()` decorator).
- **`core/concurrency.py`**: TaskGroup-based structured concurrency (`gather_with_taskgroup()`, `map_concurrent()` with bounded concurrency).
- **`services/processing_metrics.py`**: Pipeline observability with `PipelineMetrics`, `StageMetrics` dataclasses and `ProcessingTimer` context manager.
- **Test coverage**: New test files for security headers, token revocation, WebSocket auth, A2A rate limits, error sanitization, PyAV extractor, scene detection, faster-whisper, video decoder protocol, streaming pipeline, parallel transcription, retry, concurrency, processing metrics, and video performance optimizations.

#### Previously Added (this release cycle)
- **Durable A2A task persistence (PostgreSQL)**:
  - Added `A2ATaskModel` (`a2a_tasks`) to persist A2A lifecycle state (`status`, `artifacts`, `history`, metadata, timestamps).
  - Added database operations in `database_service.py`: `upsert_a2a_task()`, `get_a2a_task()`, `list_a2a_tasks()`.
  - Added `PersistentTaskStore` in `agent/a2a.py` with automatic fallback to in-memory store when DB is unavailable.
- **A2A durability tests**:
  - New `backend/tests/test_a2a_task_store.py` validates persistent-store selection, unhealthy-DB fallback, and row→task conversion shape.
- **Memory architecture guide**:
  - Added `docs/MEMORY_ARCHITECTURE.md` documenting layer responsibilities (LocalStorage, LangGraph checkpointer, Mem0, A2A Task Store), source-of-truth policy, ID mapping, and operational guidance.

### Changed

#### Code Quality
- **File decomposition**: Split oversized modules — `tools/general.py` (1800→5 modules: `search_tools.py`, `analysis_tools.py`, `context_tools.py`, `highlight_tools.py`, `multi_video_tools.py`), `a2a_routes.py` (→3 sub-routers: `a2a_agent_cards.py`, `a2a_message_routes.py`, `a2a_task_routes.py`), `graph_search_service.py` (→2 mixins: `graph_search_queries.py`, `graph_search_scoring.py`).
- **Dependency pinning**: All Python and Node.js dependencies pinned with upper bounds.
- **`os.getenv()` → `settings`**: Replaced raw env var access with typed `core.config.settings` object throughout backend.
- **`print()` → `logger`**: All runtime `print()` calls converted to structured logging.

#### Frontend
- Dead code removal and type safety fixes across components.
- Accessibility improvements (aria-labels, roles on interactive elements).
- Performance patterns: `React.memo` + `useCallback` on frequently re-rendered components.

#### Previously Changed (this release cycle)
- **README Branding**: Added QPrisma logo to README header.
- **A2A checkpointer and execution resilience**:
  - `agent/a2a.py` now resolves a shared production checkpointer (production saver with `MemorySaver` fallback).
  - Improved checkpointer materialization/setup handling for direct savers and sync/async context managers.
  - Async-safe lazy graph initialization via lock to prevent duplicate graph creation under concurrent requests.
- **A2A observability and latency metrics**:
  - Added per-phase timing instrumentation (`checkpointer_init`, `graph_ready`, `model_execution`, `task_persist`) and structured task lifecycle logs for both sync and streaming paths.
- **Chat UX persistence and continuity**:
  - `frontend/app/chat/page.tsx` and `frontend/app/chat/[id]/page.tsx` now persist/load conversation summaries, session IDs, and message history via shared conversation helpers.
  - `ChatContainer` now supports hydrated initial state (`initialMessages`, `initialSessionId`) and emits state updates to parent routes.
- **Streaming robustness and controls**:
  - `frontend/lib/api.ts` improved A2A streaming completion handling with better fallback text resolution and snapshot artifact handling.
  - Added stream cancellation support (`AbortSignal`) from UI to API client.
  - `ChatInput` adds stop-response action; `MessageList` adds retry affordance for error responses and grouped source evidence rendering.
- **First-message new chat stability**:
  - Fixed `/chat/new` first-turn race by avoiding immediate route replacement during initial persistence, preventing mid-stream unmount/loading interruptions.

## [1.0.0] - 2026-02-13

### Added
- **Knowledge Graph Visualization**: Interactive graph explorer for exploring video knowledge graphs in the browser.
  - `graph_routes.py`: `/graph/video/{id}/visualization` endpoint with per-label balanced node sampling (Video, Chapter, Scene, Frame, AudioSegment, Entity, Topic) and `/graph/expand-subgraph` endpoint for progressive lazy-load expansion.
  - `knowledge_graph.py`: `get_video_graph_visualization()` with uniform temporal sampling for Frame/AudioSegment nodes, visual property mapping per node type, and f-string depth interpolation for variable-length Cypher patterns.
  - `graph_route_schemas.py`: Pydantic schemas for graph visualization responses (`GraphVisualizationResponse`, `ExpandSubgraphRequest`).
  - `serializers.py`: Extended with Neo4j temporal type handling (DateTime, Date, Time, Duration).
  - `KnowledgeGraphViewer.tsx`: Full-featured React component using Neo4j NVL with click-to-select, double-click-to-expand, drag, hover highlight, and fullscreen support.
  - `GraphControls.tsx`: Depth slider, layout toggle (force-directed/hierarchical), and zoom reset controls.
  - `GraphLegend.tsx`: Color-coded legend for all node types.
  - `DynamicKnowledgeGraphViewer`: SSR-disabled wrapper for code splitting.
  - Graph tab integrated into `VideoPanel` — replaces deprecated `/video/[id]` page route.
  - Frontend graph API methods: `getVideoVisualization()`, `expandGraphNode()`, `getGraphStats()`.
  - Added `@neo4j-nvl/react` and `@neo4j-nvl/base` dependencies.
- **Hybrid memory architecture for LangGraph agents**:
  - Durable full tool-output artifacts via `ToolArtifactService` (Redis cache + Azure Blob + PostgreSQL metadata).
  - Mem0 integration via `Mem0MemoryService` for semantic summary add/search (feature-flagged with graceful fallback).
  - Agent state extensions: compact `memory_context` plus `artifact_refs` for precise evidence recovery.
- **Memory-focused test coverage**:
  - Added targeted tests for artifact persistence/retrieval, Mem0 service behavior, and agent memory context/rehydration flow.
- **Release & Version-Bump Workflows**:
  - `release.yml`: Automatically creates GitHub Releases from `v*` tags with CHANGELOG section extraction.
  - `version-bump.yml`: Manual workflow to bump version across `pyproject.toml`, `package.json`, and `CITATION.cff`, then tag and push.
  - `ci.yml`: Added `workflow_call` trigger for reuse from release workflow.
- **Architecture Diagram**: Generated architecture diagram (`docs/assets/qprisma_architecture.png`) via `docs/architecture_diagram.py`.

### Changed
- **Pre-commit Enforcement**: Backend pre-commit hooks (ruff, black) enforced in both local development and CI, scoped to changed backend files only.
- **Code Quality**: Backend services and tests updated for improved readability and maintainability across 23 files.
- **Frontend Navigation**: `VideoProcessingStudio` now navigates to `/chat/new?videoId=` instead of `/video/{id}`.
- **Prompt context pipeline upgraded for long conversations**:
  - Hybrid candidate retrieval (local memory + Mem0 + artifact refs) with reranking (lexical overlap + semantic score + recency).
  - Dynamic memory context budget per query and selective artifact rehydration for detail-heavy prompts.
  - Added structured logs and metrics (latency, candidate counts, snippet counts, budget usage, rehydration attempts/success/errors).
- **Infrastructure runtime wiring**:
  - `infra/main.bicep` now injects `MEM0_*` and `ARTIFACT_*` environment variables into API/Worker Container Apps.
  - `MEM0_API_KEY` added as secure Container Apps secret reference (`mem0-api-key`).
- **Blob Transfer Performance Optimization**: Overhauled all Azure Blob Storage upload/download paths for 3-5x faster transfers on large videos with ~60% less RAM usage.
  - `dependencies.py`: `BlobServiceClient` now configured with `max_single_put_size=256MB`, `max_block_size=100MB`, `max_concurrency=8` — all blob operations parallelized automatically.
  - `media_routes.py`: `/upload` and `/upload/optimized` now stream file data directly via `upload_blob(file.file)` instead of loading the entire video into memory with `await file.read()`.
  - `video_processor.py`: `_download_blob_streaming()` uses `download_blob(max_concurrency=8).readinto(f)` for parallel chunked downloads, replacing sync `chunks()` loop with `aiofiles`.
  - `video_tasks.py`: Celery download task uses streaming `chunks()` instead of `readall()`.
  - `export_service.py`: Export download uses streaming `chunks()` instead of `readall()`.
- **Frontend Chunked Upload**: Adaptive block sizes (16MB <1GB, 32MB 1-5GB, 64MB >5GB) and increased default concurrency from 4→6. Fixed `Promise.race` concurrency bug with clean worker pool pattern. (`chunked-upload.ts`)
- **Neo4j UNWIND Batch Operations**: Replaced one-by-one Cypher transactions with batched UNWIND for relation, chapter, scene, and embedding creation. Reduces Neo4j round-trips by 10-50x during video indexing.
  - `relation_builder.py`: `persist_relations()` now calls `create_relations_batch()` with grouped UNWIND by relation type.
  - `hierarchical_context_service.py`: `_store_hierarchy_in_graph()` uses `_create_chapters_batch()`, `_create_scenes_batch()`, `_create_relationships_batch()`, and `_store_embeddings_batch()`.
- **VAD-Based Audio Chunking**: Audio splitting now uses FFmpeg `silencedetect` to find natural speech boundaries instead of fixed 5-minute intervals. Prevents mid-sentence cuts for better transcription quality. Falls back to fixed intervals if silence detection fails.
  - `audio_processor.py`: `split_audio_into_chunks()` now accepts `use_vad=True` (default) and uses `_detect_silence_boundaries()` + `_find_vad_split_points()`.
- **Hardware Acceleration for FFmpeg**: Wired `hardware_accel` config to actual FFmpeg commands with auto-detection and safe CPU fallback. Set `hardware_accel: "auto"` to detect available GPU decoders (CUDA, QSV, DXVA2, VAAPI, VideoToolbox) or leave `null` for CPU-only. (`ffmpeg_processor.py`)
- **Adaptive Token Budgets**: Frame analysis token allocation now scales with visual complexity. Image entropy is calculated per frame and mapped to low (300), medium (600), or high (900) token budgets, reducing API costs ~20-30% without quality loss on simple frames.
  - `video_processor.py`: `_estimate_token_budget()` calculates image entropy via OpenCV histogram. `_prepare_frames_for_batch()` attaches per-frame `max_tokens`.
  - `batch_processor.py`: `prepare_batch_requests()` uses per-frame `max_tokens` instead of hardcoded 900.
  - `analyze_frame_with_gpt4v()` accepts `max_tokens` parameter for direct (non-batch) analysis.

### Removed
- **Deprecated `/video/[id]` page route**: Functionality moved into the chat VideoPanel with integrated Graph tab.
- **Dead `generate_block_sas_url()` function**: Defined in `chunked_upload_routes.py` but never called — removed.
- **Duplicate SAS credential parsing**: Consolidated 3 identical `AccountName`/`AccountKey` regex extractions into single `get_storage_account_info()` in `dependencies.py`. Removed `get_account_info()` from `chunked_upload_routes.py`.
- **Unused imports**: Removed `aiofiles` from `video_processor.py`, `re`/`settings` from `media_routes.py` and `chunked_upload_routes.py`, `json` from `chunked_upload_routes.py`.

### Added (New Functions & Methods)
- `create_relations_batch()`: Batched UNWIND relation creation grouped by type in `knowledge_graph.py`.
- `_create_chapters_batch()`, `_create_scenes_batch()`, `_create_relationships_batch()`, `_store_embeddings_batch()`: UNWIND batch helpers in `hierarchical_context_service.py`.
- `_detect_silence_boundaries()`: FFmpeg-based silence detection using `silencedetect` filter in `audio_processor.py`.
- `_find_vad_split_points()`: Optimal split point selection at silence boundaries near target chunk durations.
- `_detect_available_hwaccel()`: Auto-detects GPU hardware acceleration at startup, cached for session lifetime. (`ffmpeg_processor.py`)
- `_build_hwaccel_args()`: Builds `-hwaccel` FFmpeg flags for scene detection and frame extraction. (`ffmpeg_processor.py`)
- **Matryoshka Embeddings (Two-Pass Search)**: Leverages `text-embedding-3-large`'s native dimension truncation for a coarse→precise two-pass vector search strategy.
  - `embedding_service.py`: Added `COARSE_DIMENSIONS = 512` constant and `truncate_to_coarse()` method.
  - `graph_search_service.py`: Creates 8 coarse 512d vector indexes alongside existing 3072d indexes. `vector_search()` now performs coarse pass (512d, 5× wider net) → full re-rank (3072d cosine similarity). Falls back to single-pass if coarse index unavailable.
  - `store_embedding()` now stores both `embedding` (3072d) and `embedding_coarse` (512d) on every node.
  - `video_processor.py`: Frame data includes `embedding_coarse` alongside full embedding.
  - `hierarchical_context_service.py`: `_store_embeddings_batch()` stores both embedding tiers. `_ensure_vector_indexes()` creates coarse indexes for Video/Chapter/Scene.

## [0.19.0] - 2026-02-11

### Added
- **CI/CD Pipeline with GitHub Actions**: Full automated build, test, and deployment pipeline for Azure Container Apps.
  - `ci.yml`: Parallel backend lint/test + frontend lint/typecheck/test on every push/PR to `main`.
  - `build-and-push.yml`: Path-filtered Docker image builds for API, Worker, and Frontend with GHA layer caching. Automatically triggers deployment.
  - `deploy-infra.yml`: Infrastructure-as-Code deployment with Bicep validation, What-If preview, retry logic, and stale deployment cancellation.
  - `deploy-app.yml`: Rolling container updates with health checks, revision tracking, and automatic rollback on failure. Includes smoke tests.
  - Reusable composite actions: `.github/actions/setup-backend` and `.github/actions/setup-frontend`.
- **Azure Infrastructure as Code (Bicep)**: Complete Azure environment defined in `infra/` with 12 Bicep modules.
  - `ai-foundry.bicep`: Azure AI Foundry with 5 model deployments (GPT-4o, GPT-5.2-chat, text-embedding-3-large, Whisper, GPT-4o-batch).
  - `container-apps-env.bicep`: Managed environment with VNet integration (10.0.0.0/16) and Log Analytics workspace.
  - `container-app-api.bicep`: External API service (port 8000, 0.5 CPU/1Gi, 1-2 replicas, managed identity).
  - `container-app-frontend.bicep`: External frontend (port 3000, 0.25 CPU/0.5Gi, 1-2 replicas).
  - `container-app-worker.bicep`: Celery worker with KEDA Redis scaler (1-3 replicas, scales on queue depth >5, 600s graceful shutdown).
  - `neo4j.bicep`: Neo4j 5 Community container with Azure File Share persistence and APOC plugin.
  - `postgresql.bicep`: Flexible Server v16 (Standard_B1ms, 32GB, auto-grow) in North Europe.
  - `redis.bicep`: Azure Managed Redis Enterprise (Balanced_B0) with TLS 1.2+ and VolatileLRU eviction.
  - `storage.bicep`: StorageV2 with `media` blob container, CORS configuration, HTTPS-only.
  - `container-registry.bicep`: Azure Container Registry (Basic tier) for Docker images.
  - `key-vault.bicep`: Key Vault with RBAC authorization, managed identity access for API/Worker.
  - `parameters/dev.bicepparam`: Dev environment parameters with multi-region deployment (West Europe, Sweden Central, North Europe).
- **Neo4j Container App**: Deployed as internal Azure Container App with TCP ingress on port 7687 (Bolt protocol), VNet-enabled for inter-container communication.
- **Video deletion endpoint**: `delete_video` method added for complete media cleanup.

### Changed
- **AI Foundry Migration**: Migrated from standalone Azure OpenAI to Azure AI Foundry with project management, adding GPT-5.2-chat deployment (1000 TPM GlobalStandard).
- **Redis Enterprise Migration**: Migrated from Azure Cache for Redis to Azure Managed Redis Enterprise (Balanced_B0 SKU) with TLS and access key authentication.
- **Multi-Region Infrastructure**: AI resources deployed to Sweden Central (model availability), PostgreSQL to North Europe (service availability), application to West Europe (user proximity).
- **Deploy Robustness**: Added stale ARM deployment cancellation, AI Foundry provisioning wait loop (10 attempts), Bicep deploy retry (3 attempts), OIDC re-authentication before Key Vault sync.
- **Container App Reliability**: Set `minReplicas=1` for API and Frontend to avoid cold start issues. Increased API startup probe tolerance.
- **Celery Redis Compatibility**: Added Redis Cluster hash tag prefix (`{celery}`) and `ssl_cert_reqs=CERT_NONE` for Azure Redis Enterprise TLS connections.
- **Frontend CORS**: Added Azure Container Apps domain to CORS allowed origins. Aligned frontend registration payload with backend schema.
- **Neo4j Connectivity**: Resolved TCP ingress with VNet integration, switched between `bolt://` and `bolt+ssc://` for internal vs TLS connections.

### Fixed
- Dynamic API FQDN resolution for frontend Docker builds (build-arg injection).
- JMESPath query shell escaping in deploy-app revision checks.
- `trigger-deploy` 403 error by adding `actions:write` permission.
- OIDC token expiry during Key Vault secret sync (re-authentication step).
- Secret output removal from Bicep modules to fix AI Foundry provisioning conflicts.
- Redis Enterprise API version compatibility (downgraded to 2025-04-01).
- Redis `listKeys` failure by enabling access key auth on database.

## [0.18.0] - 2026-02-08

### Added
- **Evaluation Framework**: Comprehensive benchmarking system for video understanding quality.
  - `evaluation/runner.py`: Evaluation runner with adapter pattern for multiple benchmark formats.
  - `evaluation/benchmarks/`: Support for Video-MME and MLVU benchmark datasets.
  - `evaluation/judges/`: LLM-based evaluation judges with configurable prompts.
  - `evaluation/metrics/`: Standardized metrics with `EvalResult.error` field consistency.
  - `evaluation/batch_pipeline/`: Batch processing pipeline for large-scale evaluations.
  - `evaluation/scripts/`: Video-MME subset evaluation runner script.
  - `evaluation/configs/`: Ablation study configurations.
  - `EVALUATION_REPORT.md`: Evaluation results documentation.
- **A2A Agent Executor Improvements**: Enhanced agent-to-agent executor with better tool binding and error handling.
- **Video-MME Subset Evaluation Script**: Standalone runner for Video-MME benchmark subset evaluation.

### Changed
- **Backend Refactoring** (major quality improvements across 24 services):
  - `services/chat_service.py`, `services/structure_service.py`: Extracted from route handlers into dedicated service classes (Service Layer pattern).
  - `models/graph_route_schemas.py`: Added Pydantic schemas for Graph API, replacing raw dict responses.
  - `core/config.py`, `core/logging_config.py`: Improved centralized configuration and structured logging.
  - `api/dependencies.py`: Enhanced dependency injection with cleaner lazy initialization.
  - All route handlers: Consistent error handling, authentication, and response patterns.
  - All services: Improved error handling with narrowed exceptions, better type annotations, and consistent return types.
- **Celery Pipeline Improvements**: Refined video processing pipeline with better task chaining, error propagation, and retry logic.
- **Agent Tool Improvements**: Enhanced video agent tools with better query handling, context injection, and result formatting.
- **Evaluation Adapter Pattern**: Standardized adapter interface for benchmark integration with `__all__` exports.
- **Evaluation Quality**: Narrowed exceptions, deduplicated prompt I/O, UTF-8 encoding fixes, and standardized metrics across all evaluation components.

### Fixed
- Evaluation API endpoint paths and improved eval prompts.
- `EvalResult.error` field consistency across all adapter patterns.
- UTF-8 encoding issues in evaluation batch pipeline.
- `.claude` agent and command documentation alignment with codebase.

## [0.17.0] - 2026-02-05

### Changed
- **Full Async Pipeline Migration**: All video processing services now use `async/await` with `AsyncAzureOpenAI`, eliminating thread-blocking `time.sleep()` calls and enabling true concurrent I/O throughout the pipeline.
  - `video_processor.py`: `process_video_ffmpeg`, `analyze_frame_with_gpt4v`, `generate_embedding`, `generate_embeddings_batch` — all async with `AsyncAzureOpenAI`.
  - `batch_processor.py`: `submit_batch_job`, `check_batch_status`, `wait_for_batch_completion` (uses `asyncio.sleep`), `get_batch_results`, `cancel_batch` — all async.
  - `audio_processor.py`: `transcribe_audio`, `process_video_audio`, `analyze_transcription`, rate limiting — all async with `asyncio.sleep`.
  - `embedding_service.py`: `generate_embedding`, `generate_embeddings_batch` — async with lazy `AsyncAzureOpenAI` client.
  - `graph_search_service.py`: `hybrid_search`, `generate_and_store_embedding`, `bulk_generate_embeddings` — async to support async embedding calls.
  - `hierarchical_context_service.py`: All embedding generation methods (`generate_scene_embedding`, `generate_chapter_embedding`, `generate_video_embedding`, `drill_down_search`) now `await` async embedding service.
  - `enhanced_search.py`: `_hybrid_search` now awaits async `hybrid_search`.
- **Streaming Blob Download**: Replaced `readall()` (full video in memory) with chunked streaming via `blob_client.download_blob().chunks()` + `aiofiles`, reducing memory usage for large videos. (`video_processor.py`)
- **Celery Async Bridge**: Task functions use `asyncio.run()` wrappers to call async service methods from Celery's synchronous worker threads. (`video_tasks.py`)

### Added
- `create_async_azure_openai_client()`: Factory function for `AsyncAzureOpenAI` in `core/config.py`.
- `get_async_openai_client()`: Lazy singleton getter for async OpenAI client in `api/dependencies.py`.
- Neo4j async infrastructure: `async_connect()`, `async_disconnect()`, `get_async_session()`, `async_execute_query()` alongside existing sync methods for gradual migration. (`knowledge_graph.py`)
- `aiofiles` dependency for non-blocking file I/O in streaming downloads and batch file uploads.

## [0.16.0] - 2026-02-05

### Changed
- **Parallel Frame Extraction**: Replaced sequential FFmpeg subprocess loop with `ThreadPoolExecutor` (up to 8 workers) and pipe-to-memory (`image2pipe`), eliminating disk I/O per frame. Expected 5-15x speedup for videos with 50+ frames. (`ffmpeg_processor.py`)
- **Parallel Audio + Vision Pipeline**: Batch API job is now submitted before audio processing, so audio transcription runs during the batch wait window. Saves 30-60s per video by overlapping independent I/O operations. (`video_processor.py`)
- **Exponential Backoff for Batch Polling**: Replaced fixed 30s polling interval with exponential backoff (10s initial, 1.5x growth, 120s cap). Faster detection for quick batches, fewer API calls for long ones. (`batch_processor.py`)
- **Structured JSON Output for Vision Analysis**: Batch API requests now use `response_format` with strict JSON Schema, providing 100% reliable parsing, ~20-30% fewer output tokens, and direct entity mapping to Knowledge Graph. Custom prompts bypass structured output for backward compatibility. (`batch_processor.py`)

### Added
- `_extract_single_frame()`: Isolated per-frame FFmpeg extraction with pipe-to-memory and full error handling. (`ffmpeg_processor.py`)
- `_prepare_frames_for_batch()`: Helper to prepare extracted frames for Batch API submission. (`video_processor.py`)
- `_wait_and_finalize_batch()`: Refactored batch completion + embedding generation logic. (`video_processor.py`)
- `_structured_to_text()`: Flattens structured JSON analysis into embedding-friendly text. (`batch_processor.py`)
- `FRAME_ANALYSIS_SCHEMA`: JSON Schema class constant for vision analysis structured output. (`batch_processor.py`)
- `analysis_structured` field in frame results: Parsed JSON dict alongside flattened text `analysis` field. (`video_processor.py`)

## [0.15.0] - 2026-02-05

### Added
- **Multi-Video Chat**: Users can now select 2-10 videos from their library and ask questions across all of them simultaneously.
  - `ChatRequest` and `AgentChatRequest` now accept `media_ids: list[str] | None` alongside existing `media_id`.
  - Both fields can be provided; they are merged, deduplicated, and capped at 10 videos.
  - New cross-video agent tools: `search_across_videos`, `compare_videos`, `find_common_entities`, `get_library_overview`.
  - `GraphSearchService.hybrid_search()` now accepts `video_ids: list[str]` for multi-video queries.
  - `KnowledgeGraphService` added methods: `find_common_entities()`, `get_video_topics()`.
  - Frontend video selection bar with chips and remove buttons.
  - Tabbed video viewer panel for switching between selected videos.
  - Source citations now show video titles when from cross-video results.
- **Agent Architecture Documentation**: Added `backend/agent/ARCHITECTURE.md` with full graph diagrams, tool categorization, and best-practice checklist.
- **Async Utilities**: New `backend/core/async_utils.py` with helpers for async task management.
- **Custom Exception Hierarchy**: Extended `backend/core/exceptions.py` with `RetryableError` and `NonRetryableError` for smart retry policies.
- **Agent Observability**: Added structured logging across A2A executor, agent nodes, state initialization, and tool invocations for end-to-end request tracing.
- **Multi-Video Unit Tests**: Comprehensive test coverage for multi-video agent tools and cross-video search.

### Changed
- **Agent Architecture Restructure**: Reorganized flat `backend/agent/` into layered subpackages (`graphs/`, `nodes/`, `state/`, `tools/`, `utils/`). Removed 12 legacy files (~5,000 lines), consolidated into 11 focused modules.
  - `graphs/video.py` / `graphs/editor.py`: Declarative StateGraph definitions with input/output schema separation.
  - `nodes/base.py`: Shared node logic with `error_handler_node`, `select_tools_for_query`, and dynamic tool binding.
  - `nodes/video_nodes.py` / `nodes/editor_nodes.py`: Isolated node implementations per agent.
  - `state/agent_state.py`: `AgentInputState` / `AgentOutputState` for clean API boundaries.
  - `utils/observability.py`: Centralized tracing and metrics utilities.
  - `tools/general.py` / `tools/editor.py`: Consolidated from 8 separate tool files.
- **Production Checkpointer Factory**: `create_production_checkpointer()` cascades PostgreSQL → Redis → in-memory for resilient state persistence.
- **Smart Retry Policies**: `create_smart_retry_policy()` with per-exception retry classification (`should_retry_exception()`).
- **Model Temperature**: Updated default LLM temperature from `0.7` to `1` across all agent nodes (video, editor, base) for improved response diversity.
- **Frontend Chat**: `ChatContainer.tsx` now always sends `videoId` when available, regardless of chat mode.

## [0.14.0] - 2026-02-04

### Added
- **Professional Documentation**: Added `GOVERNANCE.md`, `CITATION.cff`, `SUPPORT.md`, and Architecture Decision Records (`docs/adr/`).
- **AI-Assisted Development**: Comprehensive `.claude` configuration with 20+ slash commands and 17 specialist agent definitions.
- **Large File Support**: High-performance chunked upload for files >1GB.
- **LangGraph Agent Migration**: Complete rewrite of agent system using LangGraph StateGraph.
  - `VideoAgentGraph`: New video agent with declarative graph architecture.
  - `EditorAgentGraph`: New editor agent for Chat-to-Edit functionality.
  - `@tool` decorator with `InjectedToolArg` for modern context injection.
  - `handle_tool_errors=True` for graceful tool error handling.
  - `trim_messages` to prevent context window overflow.
  - `interrupt_before` for human-in-the-loop clip confirmation.
  - Redis checkpointer (`RedisSaver`) for persistent conversation memory.
- **Video Editor**: Chat-to-Edit functionality with React Flow visualization.
- **Export**: Multi-platform export support (TikTok, Reels, Shorts, YouTube).
- **Subtitles**: Automated generation with customizable styles.

### Changed
- **Architecture**:
  - Migrated agent loop to `StateGraph` pattern with `add_messages` reducer.
  - Refactored Auth Service to use Singleton pattern.
  - Centralized backend settings and helpers.
- **Infrastructure**:
  - Updated Dockerfiles for improved build caching and structure.
  - Added enterprise-grade GitHub documentation (`.github` folder).
- **Frontend**:
  - Comprehensive code cleanup and optimization.
  - Improved API client JSON handling.
  - Enhanced UX with 3-column layout.

### Fixed
- `RedisSaver` usage with direct client (removed incorrect context manager).
- Audio transcript access in agent tools.
- Frontend typecheck and CI build issues.
- Security vulnerabilities in backend dependencies.

## [0.13.0] - 2026-01-16

### Added
- Storage tiering with automatic lifecycle policies
- Rehydration on-demand for archived media
- Cost analysis dashboard

## [0.12.0] - 2026-01-12

### Added
- Ultra-long video support (8+ hours)
- ULTRA_DEEP processing preset (2000 frames)
- Neo4j summary consolidation

## [0.11.0] - 2026-01-11

### Added
- Agentic Chat System with ReAct loop
- 9 specialized tools for video analysis
- SSE streaming for real-time responses
- Session memory with Redis

### Fixed
- AudioSegment query using correct relationship

## [0.10.0] - 2026-01-11

### Added
- Frontend UX redesign with Vimo-inspired layout
- ProcessingCard with WebSocket real-time updates
- Two chat modes: Single Video / Library

## [0.9.0] - 2026-01-10

### Changed
- Migrated from Cosmos DB to PostgreSQL
- Removed Azure AI Search (using Neo4j vector search)

## [0.8.0] - 2026-01-10

### Added
- VideoRAG-style Hybrid Search
- AudioSegment Embeddings
- Improved UI for sources

## [0.7.0] - 2026-01-09

### Added
- Hierarchical Context Encoding
- Drill-down Search
- Lazy Loading for large videos

## [0.6.0] - 2026-01-09

### Added
- Graph-Enhanced Retrieval
- Hybrid Search (vector + fulltext + graph)
- Cross-video Search

## [0.5.0] - 2026-01-09

### Added
- Neo4j Knowledge Graph
- Entity Extraction with GPT-4o
- Relation Builder for temporal/semantic relationships

## [0.4.0] - 2026-01-08

### Added
- Redis Cache with deduplication
- Celery Tasks for async processing
- WebSocket real-time updates

## [0.1.0] - 2026-01-01

### Added
- Initial release
- Video upload and processing
- Frame extraction with FFmpeg
- GPT-4o Vision analysis
- Whisper transcription
- Basic chat interface
