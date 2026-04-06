# QPrisma Architecture & Technical Deep Dive

This document provides a comprehensive technical analysis of the QPrisma platform. It details the system architecture, processing pipelines, knowledge graph implementation, and the algorithmic foundations inspired by state-of-the-art VideoRAG research.

## 1. System Architecture Overview

QPrisma implements a **Microservices-based Modular Architecture** designed for scalability and high-throughput multimedia processing.

```mermaid
graph TD
    User([User]) -->|Next.js 16| Frontend[Frontend UI]
    Frontend -->|REST / WebSocket| Gateway[API Gateway / FastAPI]

    subgraph "Processing Core"
        Gateway -->|Async Task| TaskMgr[Celery Task Manager]
        TaskMgr -->|Orchestrates| Pipeline[Video Pipeline]
        Pipeline -->|1. Extract| FFmpeg[FFmpeg Service]
        Pipeline -->|2. Analyze| Vision[GPT-4o Vision Agent]
        Pipeline -->|3. Transcribe| Whisper[Whisper Service]
        Pipeline -->|4. Structure| Summarizer[Hierarchical Summarizer]
    end

    subgraph "Knowledge Engine"
        Pipeline -->|5. Embed| Embedder[Vector Embedding Service]
        Pipeline -->|6. Graph| Builder[Relation Builder]
        Builder -->|Write| Neo4j[(Neo4j Knowledge Graph)]
        Builder -->|Vector Index| Neo4j
    end

    subgraph "Retrieval & Generation"
        Gateway -->|Query| Agent[LangGraph Video Agent]
        Agent -->|Plan| Planner[ReAct Planner]
        Planner -->|Search| Hybrid[Hybrid Search Engine]
        Hybrid -->|Graph Traversal| Neo4j
        Hybrid -->|Vector Sim| Neo4j
        Agent -->|Synthesize| LLM[GPT-4o]
    end
```

### Core Technologies
- **Runtime**: Python 3.11+ (Backend), Node.js 20+ (Frontend)
- **Frameworks**: FastAPI, Next.js 16, LangGraph, Celery
- **AI/ML**: Azure AI Foundry (GPT-4o, GPT-5.2-chat, Whisper, text-embedding-3-large)
- **Databases**: PostgreSQL (Metadata), Neo4j (Graph + Vector), Redis Enterprise (Cache/Queue)
- **Infrastructure**: Azure Container Apps, Azure Bicep IaC, GitHub Actions CI/CD
- **Storage**: Azure Blob Storage

---

## 2. Video Processing Pipeline (The "Dual-Channel" Approach)

QPrisma employs a sophisticated "Dual-Channel" processing pipeline designed to balance **speed**, **cost**, and **semantic depth**.

### 2.1. Ingestion & Extraction
*   **High-Performance Upload**: Chunked upload handling for 1GB+ files directly to Azure Blob Storage.
*   **Adaptive Frame Extraction**:
    *   **PyAV (Primary)**: In-process FFmpeg bindings (C-level) for zero-serialisation frame access.
    *   **FFmpeg subprocess (Fallback)**: Pipe-to-memory subprocess extraction when PyAV is unavailable.
*   **Scene Detection**: PySceneDetect with AdaptiveDetector (gradual transitions) and ContentDetector (hard cuts).
*   **Audio Separation**: Concurrent audio stream extraction for independent transcription.

### 2.2. Visual Analysis (Batch API Optimization)
To mitigate the high cost and latency of frame-by-frame analysis, QPrisma utilizes the **Azure OpenAI Batch API**.
*   **Cost Reduction**: ~50% savings vs. standard synchronous API.
*   **Throughput**: Parallel processing of thousands of frames without hitting standard rate limits.
*   **Prompt Engineering**: A shared system prompt (`ENTITY_EXTRACTION_SYSTEM_PROMPT`) drives both image and text extraction paths. Entities are requested in a structured table format with explicit type definitions and confidence calibration. The prompt extracts:
    *   Scene Description (Lighting, Environment)
    *   On-screen Text (OCR)
    *   Detected Entities — 8 types: `person`, `object`, `location`, `action`, `concept`, `text`, `brand`, `event`
    *   Typed Relationships with strength (1-10) between entities
    *   Actions/Narrative Flow
*   **Entity Type Normalization**: A `_normalize_entity_type()` function maps 30+ LLM-produced aliases to valid `EntityType` enum values (e.g., `"lighting"→CONCEPT`, `"vehicle"→OBJECT`, `"logo"→BRAND`). Unknown types gracefully fall back to `CONCEPT` instead of raising errors.
*   **Multi-Pass Gleaning**: After the initial extraction, a continuation prompt (`GLEANING_PROMPT`) asks the LLM to identify missed entities. New entities are deduplicated by normalized name before merging. Configurable via `settings.processing.max_gleanings` (default=1, max=3).

### 2.3. Hierarchical Context Encoding
Inspired by [VideoRAG](https://github.com/HKUDS/VideoRAG), QPrisma builds context at multiple levels to handle the "Lost in the Middle" phenomenon in long videos.

1.  **Frame Level**: Raw visual embeddings and dense captions.
2.  **Scene Level**: Aggregated summaries of sequential frames with high visual similarity.
3.  **Chapter Level**: Adaptive grouping of 2-5 consecutive scenes into chapters. `HierarchicalSummarizer` uses LLM to generate titles and summaries for each chapter. Chapter→CONTAINS→Scene edges encode the grouping.
4.  **Video Level**: Global executive summary and topic extraction. Topics are stored as first-class `TopicNode` entries in the graph (see §3.1).

**Full node hierarchy**: `Video → Chapter → Scene → Frame → Entity`

**Technique**: `HierarchicalSummarizer` service recursively summarizes lower levels to build higher-level representations, ensuring global queries ("What is this video about?") are as fast as specific ones.

---

## 3. Knowledge Graph Architecture

QPrisma moves beyond simple Vector RAG by implementing a **GraphRAG** approach using Neo4j. This allows capturing structured relationships that vector similarity misses.

QPrisma uses **one managed Neo4j database**, not a physically separate graph per video. Isolation is logical and enforced through the data model: operational graph nodes persist `user_id`, `Entity` and `Topic` identities are scoped per video, and graph reads validate ownership plus `user_id` filters before traversing Neo4j.

### 3.1. Graph Schema
The graph models the video structure and its semantic contents explicitly:

```cypher
// ── Node hierarchy ──
(:Video {video_id, user_id})-[:CONTAINS]->(:Chapter {video_id, user_id})
(:Chapter {video_id, user_id})-[:CONTAINS]->(:Scene {video_id, user_id})
(:Scene {video_id, user_id})-[:CONTAINS]->(:Frame {video_id, user_id})
(:Frame {video_id, user_id})-[:CONTAINS]->(:Entity {video_id, user_id, normalized_name, entity_type})

// ── Topic graph ──
(:Video {video_id, user_id})-[:ABOUT]->(:Topic {video_id, user_id, normalized_name})
(:Entity {video_id, user_id})-[:ABOUT]->(:Topic {video_id, user_id})

// ── Entity relationships ──
(:Entity)-[:APPEARS_WITH]->(:Entity)       // Co-occurrence in same frame
(:Entity)-[:INTERACTS_WITH]->(:Entity)     // Direct interaction
(:Entity)-[:CONTAINS]->(:Entity)           // Spatial containment
(:Entity)-[:CAUSES]->(:Entity)             // Causal link
(:Entity)-[:CAUSED_BY]->(:Entity)
(:Entity)-[:RELATES_TO]->(:Entity)         // General semantic connection
(:Entity)-[:SIMILAR_TO]->(:Entity)         // Visual/conceptual similarity
(:Entity)-[:MENTIONED_IN]->(:Entity)

// ── Cross-video links ──
(:Entity)-[:SAME_ENTITY {similarity_score}]->(:Entity)  // Across videos

// ── Community detection ──
(:Entity)-[:IN_COMMUNITY]->(:Community)
(:Community)-[:SUMMARIZES]->(:Video)

// ── Dense Temporal Chains ──
(:Frame)-[:NEXT_FRAME]->(:Frame)
(:AudioSegment)-[:NEXT_SEGMENT]->(:AudioSegment)
(:Scene)-[:NEXT_SCENE]->(:Scene)
```

**Isolation rules**:
- `Video`, `Scene`, `Frame`, `AudioSegment`, `Entity`, `Topic`, and `Community` nodes persist `user_id`
- `Entity` uniqueness is enforced on `(video_id, normalized_name, entity_type)`
- `Topic` uniqueness is enforced on `(video_id, normalized_name)`
- Node-ID graph routes resolve `node_id -> video_id` and enforce ownership before query execution

**Node types** (8): `Video`, `Chapter`, `Scene`, `Frame`, `Entity`, `AudioSegment`, `Topic`, `Community`.

**Entity types** (8 values in `EntityType` enum): `person`, `object`, `location`, `action`, `concept`, `text`, `brand`, `event`.

### 3.2. Relationship Extraction (`RelationBuilder` / `EntityExtractor`)
Edges between nodes are inferred and persisted using three strategies:
1.  **Temporal**: `BEFORE`, `AFTER`, `DURING` (based on timestamps).
2.  **Co-occurrence**: `APPEARS_WITH` (entities appearing in the same frame). On `MERGE`, a co-occurrence `count` is incremented.
3.  **Semantic (LLM-extracted)**: The LLM extracts typed relationships (`INTERACTS_WITH`, `CONTAINS`, `CAUSES`, `CAUSED_BY`, `RELATES_TO`, `SIMILAR_TO`, `MENTIONED_IN`, `APPEARS_WITH`) with a `strength` score (1-10) that is normalized to a 0.1-1.0 `weight` on the Neo4j edge. Semantic edges are stored via `create_semantic_relations_batch` using `MERGE` to deduplicate, with:
    *   `evidence_count` — incremented on repeated observations.
    *   `description` — textual description of the relationship.
    *   `first_seen` / `last_seen` — timestamps tracking temporal span.
    *   `weight` — ON MATCH keeps the highest observed weight.

**Entity description enrichment**: On `MERGE`, `description_list` accumulates up to 5 unique descriptions per entity. The canonical `description` field is updated to the longest variant.

**Relation type normalization**: Unmapped LLM relation types (e.g., `NEAR`, `ON`, `USES`, `WEARS`) are mapped to valid semantic types via `_normalize_relation_type()`. Unknown types fall back to `RELATES_TO`.

### 3.3. Dense Temporal Chains
After graph indexing, deterministic adjacency edges are created for graph-native time walking:
*   `NEXT_FRAME` — ordered by `frame_number`
*   `NEXT_SEGMENT` — ordered by `start_time`
*   `NEXT_SCENE` — ordered by `scene_index`

These chains enable forward/backward traversal without timestamp arithmetic. The search scoring layer applies a **temporal adjacency boost** — results within 15 seconds of other high-scoring results receive an additive score increase.

### 3.4. Community Detection
After entities and relationships are indexed, **Leiden** community detection clusters co-occurring entities into thematic groups:
1.  Entity co-occurrence graph is extracted from Neo4j into NetworkX.
2.  **Leiden algorithm** (`leidenalg.RBConfigurationVertexPartition`) partitions entities into communities with hierarchical multi-resolution support. The graph is converted to igraph, and multiple resolution levels (`resolution × 2^level`) produce hierarchical communities. Communities are deduplicated across levels. Falls back gracefully to **Louvain** (`python-louvain`) if `leidenalg` is not installed, and to connected components if neither is available.
3.  LLM generates a title, summary, and themes for each community.
4.  `Community` nodes with summary embeddings are stored back into Neo4j. `Entity→IN_COMMUNITY→Community` and `Community→SUMMARIZES→Video` edges encode membership and provenance.

Configuration is centralized in `CommunitySettings`: algorithm (`leiden`/`louvain`/`connected_components`), resolution (default 1.0), hierarchical levels (default 2), min community size (default 3), max communities per video (default 20).

Community nodes participate in hybrid search alongside Frame, Scene, and Entity nodes.

### 3.5. Topic Graph Nodes
Topics extracted by `HierarchicalSummarizer` are stored as first-class `TopicNode` entries in Neo4j:
*   `Video→ABOUT→Topic` edges link videos to their topics.
*   `Entity→ABOUT→Topic` edges are created by keyword matching: entity names/descriptions are compared against topic keywords and normalized names.
*   Topic nodes are merged on `(video_id, normalized_name)` so deletion and retrieval stay scoped to the source video.

### 3.6. Cross-Video Entity Resolution
After processing a new video, `resolve_cross_video_entities` finds entities from the new video that likely match entities in other videos:
*   Matches are based on `normalized_name` + `entity_type` within the same `user_id` (same type required).
*   Exact name matches receive `similarity_score = 1.0`; substring containment matches receive `0.7`.
*   Short names (≤3 characters) are filtered to avoid false positives.
*   `SAME_ENTITY` edges are created between matched pairs, with `source_video_id` and `target_video_id` properties.

### 3.7. Hybrid Indexing
QPrisma uses **Neo4j Vector Index** to store embeddings on `Frame` and `Scene` nodes.
*   **Vector Search**: Finds conceptually similar moments ("show me someone happy").
*   **Graph Traversal**: Navigates relationships ("who is the person happy *with*?").

---

## 4. Algorithmic Deep Dive: Retrieval-Augmented Generation (RAG)

### 4.1. Hybrid Search Strategy
The search engine (`EnhancedSearch`) combines results from three sources:
1.  **Vector Similarity**: `cosine_similarity(query_embedding, frame_embedding)`
2.  **Full-Text Search**: Keyword matching on OCR and Transcripts (BM25-like).
3.  **Graph Traversal**: 2-hop neighbor expansion to find contextually relevant entities.

**Formula**:
$$ Score_{final} = \alpha \cdot Score_{vector} + \beta \cdot Score_{text} + \gamma \cdot Score_{graph} $$

### 4.2. LangGraph Orchestration
The "Brain" of QPrisma is a **LangGraph StateGraph** that manages the cognitive architecture:

*   **Nodes**: `Planner`, `Search`, `Synthesize`, `Critique`.
*   **Edges**: Conditional logic to loop back if information is missing (ReAct pattern).
*   **Memory**: Redis-backed `CheckpointSaver` allows pausing/resuming long-running research tasks.

---

## 5. Technical Stack Details

### Backend (`backend/`)
*   **FastAPI**: For high-concurrency async endpoints.
*   **Pydantic**: Strict data validation and serialization.
*   **Celery**: Distributed task queue for long-running video processing.
*   **Redis Stack**: Used for Caching, Pub/Sub (WebSockets), and Vector storage (optional).

### Frontend (`frontend/`)
*   **Next.js 16 (App Router)**: Server-side rendering for performance.
*   **React 19**: Utilizing Server Components and Actions.
*   **Tailwind CSS 4**: Modern utility-first styling.
*   **ReactFlow**: Visualizing the Knowledge Graph pipelines.

---

## 6. Deployment Architecture

QPrisma deploys to **Azure Container Apps** using Infrastructure as Code (Bicep) and GitHub Actions CI/CD.

### 6.1. Azure Container Apps

Three application containers run in a VNet-enabled managed environment:

| Container | Role | Scaling | Ingress |
|-----------|------|---------|---------|
| **API** (FastAPI) | REST/WebSocket server | 1–2 replicas (HTTP concurrency) | External HTTPS |
| **Frontend** (Next.js) | SSR web application | 1–2 replicas (HTTP concurrency) | External HTTPS |
| **Worker** (Celery) | Background video processing | 1–3 replicas (KEDA Redis queue scaler) | Internal only |

Neo4j is consumed as an **external managed Neo4j Professional deployment** referenced through `NEO4J_URI`; production no longer runs Neo4j as a Container App.

### 6.2. CI/CD Pipeline

```
Code Push → CI (lint/test) → Build Docker Images → Push to ACR → Deploy to ACA
Infra Push → Validate Bicep → What-If → Deploy Azure Resources
```

Four GitHub Actions workflows form the pipeline:
1. **`ci.yml`**: 5 parallel jobs (backend lint/test, frontend lint/typecheck/test)
2. **`build-and-push.yml`**: Path-filtered builds, GHA layer caching, auto-triggers deployment
3. **`deploy-infra.yml`**: Bicep validation → What-If → Deploy with retry logic
4. **`deploy-app.yml`**: Rolling updates with health checks and automatic rollback

Key patterns: OIDC authentication, stale deployment cancellation, AI Foundry provisioning wait loop, revision-based rollback.

### 6.3. Multi-Region Strategy

| Region | Resources | Rationale |
|--------|-----------|-----------|
| West Europe | Container Apps, Redis, Storage, Key Vault, AI Foundry | User proximity, co-located compute + AI |
| North Europe | PostgreSQL Flexible Server | Service availability |

### 6.4. Security Architecture

- **Managed Identity**: API and Worker apps use system-assigned identities for Key Vault access
- **OIDC Federation**: GitHub Actions authenticate via federated credentials (no stored secrets)
- **Key Vault**: RBAC-authorized secrets for JWT keys, with "Key Vault Secrets User" role grants
- **TLS**: All external traffic encrypted; Redis Enterprise requires TLS 1.2+

For detailed infrastructure documentation, see [`docs/INFRASTRUCTURE.md`](./INFRASTRUCTURE.md).

---

## 7. References & Inspiration

This architecture draws inspiration from the following research:
*   **VideoRAG**: *"VideoRAG: Knowledge-Graph-Enhanced Retrieval-Augmented Generation for Video Understanding"* (HKUDS).
    *   *Adoption*: Graph-driven indexing and hierarchical encoding.
*   **GraphRAG**: Microsoft Research's approach to global dataset understanding.
    *   *Adoption*: Summary-based community detection (Chapters/Scenes).
*   **LangGraph**: LangChain's graph-based agent runtime.
    *   *Adoption*: Cyclic state management for the Video Agent.
