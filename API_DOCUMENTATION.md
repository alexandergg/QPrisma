# QPrisma API Documentation

## Overview

QPrisma exposes a comprehensive REST API built with FastAPI. All endpoints are documented interactively at **http://localhost:8000/docs** (Swagger UI) when the backend is running.

## Base URL

```
Development: http://localhost:8000
Production: https://your-domain.com
```

## Authentication

QPrisma uses **Microsoft Entra ID** (formerly Azure AD) for authentication via the MSAL v5 popup flow. The frontend acquires tokens using `@azure/msal-browser`, and the backend validates them against the configured tenant and audience.

### Authentication Flow

```
┌──────────┐     ┌──────────────┐     ┌──────────────┐
│ Frontend │────▶│  Entra ID    │────▶│   Backend    │
│ (MSAL)   │◀────│  (OAuth2)    │     │  (Validate)  │
└──────────┘     └──────────────┘     └──────────────┘
```

1. The frontend initiates an **MSAL popup login** against the configured Entra ID tenant.
2. On success, the browser receives an **access token** scoped to the QPrisma API.
3. The token is sent as a `Bearer` token in the `Authorization` header on every API request.
4. The backend validates the token signature, issuer, audience, and expiry using **PyJWT** with `jwt.PyJWKClient`.

### Using Authentication

Include the Entra ID access token in the Authorization header:
```http
Authorization: Bearer eyJ0eXAiOiJKV1Qi...
```

### Token Details

| Property | Value |
|----------|-------|
| Token type | OAuth 2.0 access token (JWT) |
| Issuer | `https://login.microsoftonline.com/{tenant_id}/v2.0` |
| Audience | QPrisma API Application ID URI |
| Lifetime | Configurable (default ~1 hour, managed by Entra ID) |

### User Provisioning

On first login, the backend automatically provisions the user from the Entra ID token claims (`oid`, `preferred_username`, `name`). No explicit `/auth/register` call is needed.

### Auth Endpoints

The authentication routes currently exposed by the backend are:

| Method | Route | Description |
|--------|-------|-------------|
| GET | `/auth/me` | Get the current user profile from token claims |
| GET | `/auth/config` | Get frontend authentication configuration for Entra ID/MSAL |

> **Note**: Authentication uses Entra ID access tokens. There are no documented local email/password login or logout endpoints in the current backend routes.

### Endpoint Authorization Contract

QPrisma uses a small set of endpoint scopes so operational APIs do not look like
regular user-facing product APIs:

| Scope | Contract |
|-------|----------|
| Public health/discovery | No bearer token required. Limited to readiness or public A2A discovery data. |
| Authenticated user | Requires `Authorization: Bearer <token>` and operates on the caller's own profile or library. |
| Owner-scoped media/graph | Requires authentication and validates referenced `media_id`, `media_ids`, or graph node ownership. Superusers may access any media where explicitly supported. |
| Superuser operational | Requires an authenticated superuser. Used for process-local cache mutation, account-level lifecycle policy generation, graph-wide clear, and global embedding diagnostics. |
| Benchmark operator | Requires an authenticated superuser or the configured benchmark automation token. Used only by benchmark ingest/status/manifest automation. |

Current high-risk operational endpoints:

| Route family | Scope |
|--------------|-------|
| `GET /cache/health`, `GET /storage/health`, `/`, `/health`, `/config`, `GET /a2a/health`, A2A agent card discovery | Public health/discovery |
| `/media/*`, `/upload`, `/upload/optimized`, `/upload/chunked/*`, `/storage/media/{media_id}/*`, `/graph/video/{video_id}*`, `/graph/search/*`, `/graph/hierarchy/*` | Owner-scoped media/graph |
| `/cache/metrics`, `/cache/metrics/reset`, `/cache/invalidate`, `/cache/video/{video_id}`, `/cache/config`, `/storage/lifecycle-policy`, `/graph/embeddings/stats`, hidden `DELETE /graph/clear` | Superuser operational |
| `POST /graph/embeddings/generate` | Owner-scoped when `video_id` is supplied; superuser-only for global generation without `video_id` |
| `/benchmark/*` | Benchmark operator |

## A2A Protocol (Agent-to-Agent)

QPrisma implements the [A2A Protocol](https://a2a-protocol.org/) as the canonical API for the Azure AI Foundry hosted video agent. Legacy `/chat/agent` access has been removed. The classic `/chat` VideoRAG endpoint remains as a deprecated compatibility path for direct non-agentic chat clients.

> **Rate Limiting**: All A2A endpoints are rate-limited via slowapi. Message endpoints allow 60 requests/minute; task listing allows 120/minute; task cancellation allows 30/minute.
>
> **Authentication and ownership**: Agent discovery endpoints are public. Message and task lifecycle endpoints require `Authorization: Bearer <token>`. The server validates `media_id`/`media_ids` ownership, overwrites client-supplied `user_id`, and returns 404 for cross-user task or conversation continuation attempts.

### Agent Discovery

#### Get Agent Card
```http
GET /.well-known/agent-card.json
```

**Response:**
```json
{
  "name": "QPrisma Video Agent",
  "description": "Intelligent video analysis and search agent",
  "url": "http://localhost:8000",
  "version": "1.0.0",
  "capabilities": {
    "streaming": true,
    "pushNotifications": false,
    "stateTransitionHistory": true
  },
  "securitySchemes": {
    "bearerAuth": {
      "type": "http",
      "scheme": "bearer",
      "bearerFormat": "JWT"
    }
  },
  "security": [{"bearerAuth": []}],
  "skills": [
    {
      "id": "video-search",
      "name": "Video Search",
      "description": "Search video content semantically",
      "tags": ["search", "semantic", "video"]
    }
  ]
}
```

#### Video Agent Card
```http
GET /a2a/agent-card.json
```

### Message Operations

#### Send Message (Sync)
```http
POST /a2a/message:send
Content-Type: application/json
Authorization: Bearer eyJhbGc...

{
  "message": {
    "contextId": "optional-session-id",
    "role": "ROLE_USER",
    "parts": [{"text": "Find all safety violations in this video"}],
    "metadata": {"media_id": "video-uuid"}
  }
}
```

**Response:**
```json
{
  "task": {
    "id": "task-uuid",
    "contextId": "session-uuid",
    "status": {"state": "TASK_STATE_COMPLETED"},
    "artifacts": [
      {
        "artifactId": "artifact-uuid",
        "name": "Agent Response",
        "parts": [{"text": "I found 3 safety violations..."}]
      }
    ]
  }
}
```

#### Send Message (Streaming)
```http
POST /a2a/message:stream
Content-Type: application/json
Authorization: Bearer eyJhbGc...

{
  "message": {
    "contextId": "session-uuid",
    "role": "ROLE_USER",
    "parts": [{"text": "What happens at the beginning of the video?"}],
    "metadata": {"media_id": "video-uuid"}
  }
}
```

**Response (SSE Stream):**
```
data: {"task":{"id":"task-id","contextId":"ctx-id","status":{"state":"TASK_STATE_SUBMITTED"}}}
data: {"statusUpdate":{"taskId":"task-id","status":{"state":"TASK_STATE_WORKING"}}}
data: {"statusUpdate":{"taskId":"task-id","status":{"state":"TASK_STATE_WORKING","message":{"parts":[{"text":"Using tool: search_video_content"}]}}}}
data: {"artifactUpdate":{"taskId":"task-id","artifact":{"parts":[{"text":"The video begins with"}]},"append":true}}
data: {"artifactUpdate":{"taskId":"task-id","artifact":{"parts":[{"text":" an introduction..."}]},"append":true}}
data: {"statusUpdate":{"taskId":"task-id","status":{"state":"TASK_STATE_COMPLETED"}}}
```

### Task Operations

#### Get Task
```http
GET /a2a/tasks/{task_id}?historyLength=10
Authorization: Bearer eyJhbGc...
```

**Response:**
```json
{
  "id": "task-uuid",
  "contextId": "session-uuid",
  "status": {"state": "TASK_STATE_COMPLETED"},
  "artifacts": [...],
  "history": [...]
}
```

#### List Tasks
```http
GET /a2a/tasks?contextId=session-uuid&status=TASK_STATE_COMPLETED&pageSize=20
Authorization: Bearer eyJhbGc...
```

#### Cancel Task
```http
POST /a2a/tasks/{task_id}:cancel
Authorization: Bearer eyJhbGc...
```

#### Subscribe to Task Updates
```http
POST /a2a/tasks/{task_id}:subscribe
Authorization: Bearer eyJhbGc...
```

**Response (SSE Stream):**
```
data: {"statusUpdate":{"taskId":"task-id","status":{"state":"TASK_STATE_WORKING"}}}
data: {"artifactUpdate":{"taskId":"task-id","artifact":{...}}}
data: {"statusUpdate":{"taskId":"task-id","status":{"state":"TASK_STATE_COMPLETED"}}}
```

### A2A Task States

| State | Description |
|-------|-------------|
| `TASK_STATE_SUBMITTED` | Task received and queued |
| `TASK_STATE_WORKING` | Task is being processed |
| `TASK_STATE_COMPLETED` | Task finished successfully |
| `TASK_STATE_FAILED` | Task failed with error |
| `TASK_STATE_CANCELED` | Task was canceled |
| `TASK_STATE_INPUT_REQUIRED` | Waiting for user input |

## Core Endpoints

### Media Management

#### Upload Media
```http
POST /media/upload
Content-Type: multipart/form-data

file: <video_file>
metadata: {
  "title": "My Video",
  "description": "Video description"
}
```

**Response:**
```json
{
  "video_id": "uuid-here",
  "filename": "video.mp4",
  "size": 12345678,
  "duration": 120.5,
  "status": "uploaded"
}
```

#### List Media
```http
GET /media
```

**Query Parameters:**
- `page`: Page number (default: 1)
- `per_page`: Items per page (default: 20)
- `status`: Filter by status (processing, completed, failed)

**Response:**
```json
{
  "items": [
    {
      "id": "uuid",
      "filename": "video.mp4",
      "status": "completed",
      "created_at": "2024-01-20T10:00:00Z"
    }
  ],
  "total": 50,
  "page": 1,
  "per_page": 20
}
```

#### Get Media Details
```http
GET /media/{video_id}
```

**Response:**
```json
{
  "id": "uuid",
  "filename": "video.mp4",
  "duration": 120.5,
  "frame_count": 240,
  "status": "completed",
  "metadata": {
    "width": 1920,
    "height": 1080,
    "fps": 30,
    "codec": "h264"
  },
  "analysis": {
    "scenes": 12,
    "objects_detected": 150,
    "transcript_available": true
  }
}
```

#### Delete Media
```http
DELETE /media/{video_id}
```

**Response:**
```json
{
  "message": "Video and related data deleted successfully"
}
```

### Video Processing

Video processing is queued from the media upload endpoints. All video processing is dispatched via **Azure Service Bus** to the Databricks pipeline consumer.

**Configuration:**
- `PROCESSING_BACKEND` (environment variable, optional): Accepts `servicebus` (default) or legacy `databricks` alias. Both values dispatch via Service Bus. The `databricks` setting is deprecated but remains supported for backwards compatibility with existing deployments.

**Operational Note:** The backend records the canonical `servicebus` processing method. The legacy `databricks` value is accepted as input for existing deployments, but does not change the dispatch mechanism.

The old local processing preview, `/jobs/*`, and Azure OpenAI Batch management routes have been retired from the FastAPI app. Status projection now comes from the Databricks outbox/bridge into the media status fields.

#### Upload and Dispatch Video
```http
POST /upload
Content-Type: multipart/form-data
```

`/upload/optimized` accepts the same video upload plus processing form fields such as `preset`, `max_frames`, `use_scene_detection`, `use_hierarchical_summary`, `scene_threshold`, and `max_scenes_per_chapter`.

**Presets:**
- `fast`: 1 FPS, 720p, optimized for speed
- `balanced`: 2 FPS, 1080p (default)
- `quality`: 5 FPS, original resolution
- `custom`: User-defined configuration

**Response:**
```json
{
  "media_id": "media-id",
  "blob_name": "media-id.mp4",
  "media_type": "video",
  "file_size": 1048576,
  "job_id": "dbx-dispatch-id",
  "status": "queued",
  "pipeline": "databricks"
}
```

**Databricks Processing Pipeline:**

1. **Register manifest** from the explicit `source_media` storage contract.
2. **Validate/probe media** and write Bronze quality data to Delta.
3. **Extract audio and frames** with Databricks-local FFmpeg helpers.
4. **Run frame analysis** with Florence and ASR with faster-whisper.
5. **Detect scenes/windows** and run Databricks model reasoning for scene summaries.
6. **Build Gold `processing_result`**, graph upsert rows, Neo4j projection, and outbox/status events.

**Frame Analysis Output (v0.16.0):**
Each frame result now includes both a flattened text `analysis` (for embeddings) and an `analysis_structured` JSON object:

```json
{
  "frame_number": 0,
  "timestamp": 5.0,
  "analysis": "Scene: Indoor office. Lighting: bright. ...",
  "analysis_structured": {
    "scene_description": {
      "setting": "Indoor office with modern furniture",
      "lighting": "Bright fluorescent overhead",
      "atmosphere": "Professional, focused",
      "visual_style": "Corporate presentation"
    },
    "people": [
      {
        "description": "Male, 30s, blue shirt",
        "role": "presenter",
        "emotion": "confident",
        "name": "John Smith"
      }
    ],
    "ocr_text": ["Q3 Revenue Report", "Revenue: $4.2M"],
    "visual_elements": ["laptop", "projection screen", "bar chart"],
    "actions": "Presenting quarterly revenue results with slide deck",
    "topics": ["quarterly results", "revenue growth", "financial report"],
    "keywords": ["Q3 report", "revenue", "John Smith", "presenting"],
    "questions_answered": ["What were Q3 revenues?", "Who presented?"]
  },
  "tokens_used": 650,
  "embedding": [0.123, ...]
}
```

#### Get Processing Status
```http
GET /media/{media_id}/status
```

**Response:**
```json
{
  "media_id": "media-id",
  "processing_status": "processing",
  "processing_progress": 45,
  "processing_message": "Analyzing scene windows",
  "processing_method": "servicebus",
  "job_id": "dbx-dispatch-id"
}
```

**Status Values:**
- `pending`: Job queued
- `processing`: Job in progress
- `completed`: Job finished successfully
- `failed`: Job encountered an error

### Storage Tiering

> **Note**: Storage tiering endpoints are designed for cost optimization of archived videos. Per-media operations require authentication and validate media ownership. Superusers can manage tier for any media. `/storage/lifecycle-policy` is superuser-only because it generates an account-level Azure Storage management policy.

#### Get Storage Health
```http
GET /storage/health
```

**No authentication required.** Returns service connectivity status.

#### Get Media Tier
```http
GET /storage/media/{media_id}/tier
```

#### Change Media Tier
```http
POST /storage/media/{media_id}/tier
Content-Type: application/json

{
  "target_tier": "Cool",
  "rehydrate_priority": "Standard"
}
```

#### Rehydrate Archived Media
```http
POST /storage/media/{media_id}/rehydrate
Content-Type: application/json

{
  "priority": "High",
  "target_tier": "Hot"
}
```

#### Tier Recommendation
```http
GET /storage/media/{media_id}/recommendation
```

#### Storage Cost Analysis
```http
GET /storage/cost-analysis
```

#### Generate Lifecycle Policy
```http
POST /storage/lifecycle-policy
Content-Type: application/json

{
  "cool_days": 30,
  "cold_days": 90,
  "archive_days": 180,
  "prefix_filter": "videos/"
}
```

### Search & Chat

#### Semantic Search
```http
POST /search
Content-Type: application/json

{
  "query": "show me safety violations",
  "video_ids": ["uuid1", "uuid2"],
  "limit": 10
}
```

**Response:**
```json
{
  "results": [
    {
      "video_id": "uuid",
      "frame_id": "frame-uuid",
      "timestamp": 45.2,
      "score": 0.92,
      "description": "Worker without safety helmet near machinery",
      "thumbnail_url": "https://..."
    }
  ],
  "total": 5
}
```

#### Chat with Media - A2A Protocol

**Single Video Chat:**
```http
POST /a2a/message:stream
Content-Type: application/json
Authorization: Bearer eyJhbGc...

{
  "message": {
    "contextId": "chat-session-uuid",
    "role": "ROLE_USER",
    "parts": [{"text": "What safety issues are present in the video?"}],
    "metadata": {"media_id": "uuid"}
  }
}
```

**Multi-Video Chat (2-10 videos):**
```http
POST /a2a/message:stream
Content-Type: application/json
Authorization: Bearer eyJhbGc...

{
  "message": {
    "contextId": "chat-session-uuid",
    "role": "ROLE_USER",
    "parts": [{"text": "Which videos contain safety violations?"}],
    "metadata": {"media_ids": ["uuid1", "uuid2", "uuid3"]}
  }
}
```

> **Note**: Both `media_id` and `media_ids` can be provided simultaneously. They will be merged, deduplicated, and capped at 10 videos maximum.
> The server validates every referenced media item against the authenticated user. Continue a hosted-agent session by passing the returned Foundry `contextId`; cross-user continuation attempts are hidden as 404.

**Response (Streaming A2A Format):**
```
data: {"task":{"id":"task-uuid","contextId":"chat-session-uuid","status":{"state":"TASK_STATE_SUBMITTED"}}}
data: {"statusUpdate":{"taskId":"task-uuid","status":{"state":"TASK_STATE_WORKING"}}}
data: {"artifactUpdate":{"taskId":"task-uuid","artifact":{"parts":[{"text":"I found several safety issues:"}]},"append":true}}
data: {"artifactUpdate":{"taskId":"task-uuid","artifact":{"parts":[{"data":{"sources":[{"timestamp":45.2,"type":"visual","video_id":"uuid1"}]}}]}}}
data: {"statusUpdate":{"taskId":"task-uuid","status":{"state":"TASK_STATE_COMPLETED"}}}
```

**Multi-Video Tools:**

When using `media_ids`, the agent has access to specialized cross-video tools:
- `search_across_videos`: Search for content across all selected videos
- `compare_videos`: Compare specific aspects between videos
- `find_common_entities`: Find entities that appear in multiple videos
- `get_library_overview`: Get high-level overview of video collection

### Hosted Agent Deployment RBAC

The hosted agent container runs with a dedicated Microsoft Entra runtime identity. When Foundry returns `instance_identity.principal_id` during deployment, `deploy-hosted-agent.yml` assigns the runtime roles QPrisma needs: `Azure AI User` at the Foundry project scope and `Cognitive Services OpenAI User` at the Foundry account scope for account-scoped OpenAI calls. The lookup is best-effort by default and does not block registration after the agent version is active; re-run the workflow or enable `REQUIRE_AGENT_IDENTITY_RBAC=1` for deployments that must fail until custom runtime RBAC is assigned.

### Knowledge Graph

#### Graph Search
```http
POST /graph/search/hybrid
Content-Type: application/json

{
  "query": "find all scenes with people and machinery",
  "video_id": "uuid",
  "limit": 10,
  "use_graph_expansion": true
}
```

**Multi-Video Graph Search:**
```http
POST /graph/search/hybrid
Content-Type: application/json

{
  "query": "find common entities across videos",
  "video_ids": ["uuid1", "uuid2", "uuid3"],
  "limit": 10,
  "use_reranking": true
}
```

**Response:**
```json
{
  "nodes": [
    {
      "id": "node-uuid",
      "type": "scene",
      "properties": {
        "timestamp": 45.2,
        "description": "..."
      }
    }
  ],
  "relationships": [
    {
      "from": "node1",
      "to": "node2",
      "type": "CONTAINS"
    },
    {
      "from": "entity1",
      "to": "entity2",
      "type": "INTERACTS_WITH",
      "properties": {
        "weight": 0.8,
        "evidence_count": 3,
        "description": "person using object"
      }
    }
  ]
}
```

#### Get Video Hierarchy Stats
```http
GET /graph/hierarchy/stats/{video_id}
```

Hierarchy drill-down and lazy child loading use `POST /graph/hierarchy/search/drill-down`
and `POST /graph/hierarchy/children`. All hierarchy endpoints require media
ownership for the referenced video or node.

**Response:**
```json
{
  "video": {
    "id": "uuid",
    "title": "Safety Inspection"
  },
  "scenes": [
    {
      "id": "scene-1",
      "timestamp": 0.0,
      "duration": 30.5,
      "frames": [...]
    }
  ]
}
```

### Community Detection

Community detection runs automatically as the final stage of video processing. It clusters co-occurring entities via Leiden (`RBConfigurationVertexPartition` with hierarchical multi-resolution, `hierarchical_levels=2`; Louvain fallback if `leidenalg` is unavailable) and generates LLM thematic summaries stored as `Community` nodes in Neo4j. Configuration: `algorithm="leiden"`, `resolution=1.0`, `min_community_size=3`, `max_communities_per_video=20`.

Community nodes participate in hybrid search — the `COMMUNITY` node type is included in the default search scope. Each community carries an embedding of its summary, enabling semantic matching against user queries.

### Dense Temporal Chains

After graph indexing, the pipeline creates deterministic adjacency edges for graph-native time walking:

| Relationship | Nodes | Ordering |
|---|---|---|
| `NEXT_FRAME` | Frame → Frame | `frame_number` |
| `NEXT_SEGMENT` | Segment → Segment | `start_time` |
| `NEXT_SCENE` | Scene → Scene | `scene_index` |

These chains enable forward/backward traversal without timestamp arithmetic. The search scoring layer applies a **temporal adjacency boost** — results whose timestamps fall within 15 seconds of other high-scoring results receive an additive score increase.

### Knowledge Graph Service Architecture

The Knowledge Graph backend follows a layered architecture:

| Layer | Service | Responsibility |
|---|---|---|
| **Facade** | `KnowledgeGraphService` | Public API, connection management, `execute_query()` gateway |
| **Domain Mixins** | `services/graph/*.py` (7 mixins) | Neo4j operations grouped by domain (video, frame, entity, audio, relation, community, agent) |
| **Query Utilities** | `cypher_filters.py`, `graph_search_queries.py` | Keyword sanitization, Lucene escaping, fulltext query building |
| **Resilience** | `neo4j_resilience.py` | Read/write retry decorators, transient vs permanent error classification |
| **Types** | `graph/types.py` | Shared TypedDicts (`MultimodalSearchResult`, `SubgraphResult`, `ExpandContextNodes`) |
| **Hierarchical Orchestrator** | `HierarchicalContextService` | Pipeline coordination, embedding pooling, storage orchestration |
| **Hierarchical Storage** | `HierarchyNodeFactory` | Neo4j persistence for hierarchy nodes |
| **Hierarchical Query** | `HierarchicalQueryService` | Drill-down search, stats, level navigation |
| **Search** | `GraphSearchService` + `GraphSearchScoring` | Hybrid vector/fulltext search with scoring |
| **Structure** | `StructureService` | Scene/chapter extraction from graph data |

All Neo4j access is funneled through `KnowledgeGraphService.execute_query()`, ensuring centralized retry handling and error classification. Direct `_driver.session()` usage is confined to `knowledge_graph.py`.

### Cache Management

QPrisma uses a local in-process cache for search and graph hot paths. It is
scoped to a single API replica and is not a source of truth. `GET /cache/health`
is public for lightweight readiness checks; all other `/cache/*` endpoints are
operational diagnostics and require an authenticated superuser.

#### Cache Health
```http
GET /cache/health
```

**Response:**
```json
{
  "status": "healthy",
  "backend": "memory",
  "connected": true,
  "message": "Cache operational"
}
```

#### Cache Metrics
```http
GET /cache/metrics
Authorization: Bearer <superuser-token>
```

**Response:**
```json
{
  "connected": true,
  "backend": "memory",
  "hits": 15420,
  "misses": 3210,
  "errors": 0,
  "hit_rate": "82.79%",
  "bytes_saved": 0,
  "api_calls_saved": 12300,
  "estimated_cost_saved": "$1.23"
}
```

#### Invalidate Cache
```http
POST /cache/invalidate
Authorization: Bearer <superuser-token>
Content-Type: application/json

{
  "patterns": ["media:*", "search:video-uuid:*"]
}
```

> `GET /cache/health` is public (no auth required). All other cache endpoints
> (`/cache/metrics`, `/cache/metrics/reset`, `/cache/invalidate`,
> `/cache/video/{video_id}`, `/cache/config`) require an authenticated
> superuser and affect only the current API replica.

### Video Structure

#### Get Video Structure
```http
GET /media/{media_id}/structure
```

Returns the scene and chapter structure for a processed video.

**Response:**
```json
{
  "media_id": "uuid",
  "chapters": [
    {
      "id": "chapter-1",
      "title": "Introduction",
      "summary": "Overview of the quarterly report",
      "start_time": 0.0,
      "end_time": 45.5,
      "scenes": [
        {
          "scene_index": 0,
          "start_time": 0.0,
          "end_time": 22.3,
          "description": "Opening title sequence"
        }
      ]
    }
  ]
}
```

## Processing Status Polling

The frontend tracks processing progress by polling the persisted media status:

```javascript
const response = await fetch('http://localhost:8000/media/{media_id}/status', {
  headers: { Authorization: `Bearer ${accessToken}` },
});

const data = await response.json();
console.log('Status:', data.processing_status);
console.log('Progress:', data.processing_progress);
```

**Response Shape:**
```json
{
  "media_id": "abc-123",
  "processing_status": "processing",
  "processing_message": "Analyzing frames",
  "processing_progress": 45,
  "processed": false,
  "frames_analyzed": 32,
  "last_updated": "2026-05-06T13:00:00Z"
}
```

## Error Responses

All errors follow this structured format:

```json
{
  "error": {
    "code": "MEDIA_NOT_FOUND",
    "message": "Media with id 'abc-123' not found",
    "context": {
      "resource_type": "media",
      "resource_id": "abc-123"
    }
  }
}
```

Structured error codes are generated by factory functions in `core/exceptions.py`:
- `not_found_error(resource, id)` → 404
- `access_denied_error(resource, id)` → 403
- `validation_error(message)` → 400
- `service_unavailable_error(service)` → 503

**Common Status Codes:**
- `400`: Bad Request - Invalid input
- `401`: Unauthorized - Missing/invalid authentication
- `403`: Forbidden - Insufficient permissions
- `404`: Not Found - Resource doesn't exist
- `422`: Unprocessable Entity - Validation error
- `429`: Too Many Requests - Rate limit exceeded
- `500`: Internal Server Error - Server-side error

## Rate Limiting

Rate limits are enforced per-IP via slowapi:

- **Auth endpoints**: 5-10 requests/minute
- **A2A message endpoints**: 60 requests/minute
- **A2A task list**: 120 requests/minute
- **A2A task cancel/subscribe**: 30-60 requests/minute
- **Upload endpoint**: 20 uploads/minute
- **Standard endpoints**: 100 requests/minute

> **Cache endpoints**: `GET /cache/health` is public. Cache diagnostics and
> mutation endpoints require an authenticated superuser and affect only the
> current API replica's in-process cache.

Rate limit headers:
```http
X-RateLimit-Limit: 100
X-RateLimit-Remaining: 95
X-RateLimit-Reset: 1642684800
```

## Pagination

Endpoints that return lists support pagination:

**Query Parameters:**
- `page`: Page number (default: 1)
- `per_page`: Items per page (default: 20, max: 100)

**Response includes:**
```json
{
  "items": [...],
  "total": 500,
  "page": 1,
  "per_page": 20,
  "pages": 25
}
```

## Best Practices

### 1. Use Databricks Processing for Large Workloads
For processing 100+ frames, keep the workload on the Databricks pipeline and pass processing preferences through upload/dispatch configuration:
```json
{
  "preset": "deep_analysis",
  "max_frames": 1000,
  "use_hierarchical_summary": true
}
```

### 2. Enable Caching
Include cache headers to improve performance:
```http
Cache-Control: max-age=3600
```

### 3. Compress Uploads
Use gzip compression for large video uploads:
```http
Content-Encoding: gzip
```

### 4. Stream Large Responses
Use chunked transfer encoding for large responses:
```http
Transfer-Encoding: chunked
```

### 5. Handle Webhooks
Register webhook URLs for async notifications:
```json
{
  "webhook_url": "https://your-domain.com/webhooks/processing",
  "events": ["processing.completed", "processing.failed"]
}
```

## SDK Examples

### Python

```python
import requests

# Login
response = requests.post(
    'http://localhost:8000/auth/login',
    json={'email': 'user@example.com', 'password': 'password'}
)
token = response.json()['access_token']

# Upload video
headers = {'Authorization': f'Bearer {token}'}
files = {'file': open('video.mp4', 'rb')}
response = requests.post(
    'http://localhost:8000/media/upload',
    headers=headers,
    files=files
)
video_id = response.json()['video_id']

# Process video
response = requests.post(
    f'http://localhost:8000/processing/ffmpeg/{video_id}',
    headers=headers,
    json={'preset': 'balanced'}
)
job_id = response.json()['job_id']
```

### JavaScript/TypeScript

```typescript
// Login
const login = await fetch('http://localhost:8000/auth/login', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ email: 'user@example.com', password: 'password' })
});
const { access_token } = await login.json();

// Upload video
const formData = new FormData();
formData.append('file', videoFile);

const upload = await fetch('http://localhost:8000/media/upload', {
  method: 'POST',
  headers: { 'Authorization': `Bearer ${access_token}` },
  body: formData
});
const { video_id } = await upload.json();

// Process video
const process = await fetch(`http://localhost:8000/processing/ffmpeg/${video_id}`, {
  method: 'POST',
  headers: {
    'Authorization': `Bearer ${access_token}`,
    'Content-Type': 'application/json'
  },
  body: JSON.stringify({ preset: 'balanced' })
});
const { job_id } = await process.json();
```

## Support

- **Interactive API Docs**: http://localhost:8000/docs
- **GitHub Issues**: https://github.com/alexandergg/QPrisma/issues
- **Discussions**: https://github.com/alexandergg/QPrisma/discussions
