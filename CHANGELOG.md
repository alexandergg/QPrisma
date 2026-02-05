# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
