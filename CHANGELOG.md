# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Video editor with Chat-to-Edit functionality
- Storage tiering for cost optimization
- Agentic chat system with 9+ tools
- Export to multiple platforms (TikTok, Reels, Shorts, YouTube)
- Subtitle generation with multiple styles

### Changed
- Migrated from Cosmos DB to PostgreSQL
- Improved frontend UX with 3-column layout

### Fixed
- Audio transcript access in agent tools
- Session management for chat conversations

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
