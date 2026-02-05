# QPrisma API Documentation

## Overview

QPrisma exposes a comprehensive REST API built with FastAPI. All endpoints are documented interactively at **http://localhost:8000/docs** (Swagger UI) when the backend is running.

## Base URL

```
Development: http://localhost:8000
Production: https://your-domain.com
```

## Authentication

QPrisma uses JWT (JSON Web Tokens) for authentication.

### Login
```http
POST /auth/login
Content-Type: application/json

{
  "email": "user@example.com",
  "password": "your-password"
}
```

**Response:**
```json
{
  "access_token": "eyJhbGc...",
  "token_type": "bearer",
  "expires_in": 86400
}
```

### Using Authentication
Include the token in the Authorization header:
```http
Authorization: Bearer eyJhbGc...
```

## A2A Protocol (Agent-to-Agent)

QPrisma implements the [A2A Protocol](https://a2a-protocol.org/) for standardized agent communication. This enables interoperability with other A2A-compliant agents.

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

#### Editor Agent Card
```http
GET /a2a/editor/agent-card.json
```

### Message Operations

#### Send Message (Sync)
```http
POST /a2a/message:send
Content-Type: application/json

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

#### Editor Agent Message (Streaming)
```http
POST /a2a/editor/message:stream
Content-Type: application/json

{
  "message": {
    "role": "ROLE_USER",
    "parts": [{"text": "Create 5 viral clips from this video"}],
    "metadata": {"project_id": "project-uuid"}
  }
}
```

### Task Operations

#### Get Task
```http
GET /a2a/tasks/{task_id}?historyLength=10
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
```

#### Cancel Task
```http
POST /a2a/tasks/{task_id}:cancel
```

#### Subscribe to Task Updates
```http
POST /a2a/tasks/{task_id}:subscribe
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

#### Process Video with FFmpeg
```http
POST /processing/ffmpeg/{video_id}
Content-Type: application/json

{
  "preset": "balanced",
  "frame_extraction": {
    "method": "hybrid",
    "fps": 2,
    "max_frames": 100
  },
  "enable_audio": true,
  "enable_vision": true
}
```

**Presets:**
- `fast`: 1 FPS, 720p, optimized for speed
- `balanced`: 2 FPS, 1080p (default)
- `quality`: 5 FPS, original resolution
- `custom`: User-defined configuration

**Response:**
```json
{
  "job_id": "celery-task-id",
  "status": "processing",
  "estimated_time": 300
}
```

#### Get Processing Status
```http
GET /jobs/{job_id}
```

**Response:**
```json
{
  "job_id": "celery-task-id",
  "status": "processing",
  "progress": 45,
  "stage": "extracting_frames",
  "frames_processed": 45,
  "frames_total": 100,
  "message": "Extracting frame 45 of 100"
}
```

**Status Values:**
- `pending`: Job queued
- `processing`: Job in progress
- `completed`: Job finished successfully
- `failed`: Job encountered an error

### Video Editor (Chat-to-Edit)

#### Create Project
```http
POST /editor/projects
Content-Type: application/json

{
  "source_media_id": "media_abc123",
  "name": "My Podcast Ep.42 Clips",
  "description": "Viral clips from episode 42",
  "settings": {
    "target_aspect_ratio": "9:16",
    "target_resolution": "1080x1920",
    "default_subtitle_style": "hormozi"
  }
}
```

**Response:**
```json
{
  "id": "project_123",
  "user_id": "user_abc",
  "source_media_id": "media_abc123",
  "name": "My Podcast Ep.42 Clips",
  "status": "draft",
  "clips_count": 0
}
```

#### List Projects
```http
GET /editor/projects?limit=50&offset=0
```

#### Get Project (with clips and source media)
```http
GET /editor/projects/{project_id}
```

#### Create Clip
```http
POST /editor/projects/{project_id}/clips
Content-Type: application/json

{
  "start_time": 734.5,
  "end_time": 764.5,
  "title": "Introduction to AI",
  "notes": "Good hook at the start"
}
```

#### Reorder Clips
```http
POST /editor/projects/{project_id}/clips/reorder
Content-Type: application/json

{
  "clip_ids": ["clip_a", "clip_b", "clip_c"]
}
```

#### Subtitle Styles
```http
GET /editor/subtitle-styles
```

#### Generate Subtitles
```http
POST /editor/clips/{clip_id}/subtitles/generate
Content-Type: application/json

{
  "style": "hormozi"
}
```

#### Update Clip Subtitles
```http
PATCH /editor/clips/{clip_id}/subtitles
Content-Type: application/json

{
  "subtitles_enabled": true,
  "subtitle_style": "mrbeast"
}
```

#### Export Presets
```http
GET /editor/export/presets
```

#### Export Clip
```http
POST /editor/clips/{clip_id}/export
Content-Type: application/json

{
  "platform": "tiktok",
  "quality": "standard",
  "crop_mode": "center",
  "burn_subtitles": true
}
```

#### Batch Export
```http
POST /editor/projects/{project_id}/export/batch
Content-Type: application/json

{
  "clip_ids": ["clip_a", "clip_b"],
  "platform": "reels",
  "quality": "high"
}
```

#### Export Status
```http
GET /editor/clips/{clip_id}/export/status
```

#### Chat-to-Edit Stream (SSE) - A2A Protocol
```http
POST /a2a/editor/message:stream
Content-Type: application/json

{
  "message": {
    "contextId": "session-uuid",
    "role": "ROLE_USER",
    "parts": [{"text": "Create 3 viral clips of 30 seconds each"}],
    "metadata": {"project_id": "project-uuid"}
  }
}
```

**Response (Streaming A2A Format):**
```
data: {"task":{"id":"task-uuid","contextId":"session-uuid","status":{"state":"TASK_STATE_SUBMITTED"}}}
data: {"statusUpdate":{"taskId":"task-uuid","status":{"state":"TASK_STATE_WORKING"}}}
data: {"artifactUpdate":{"taskId":"task-uuid","artifact":{"parts":[{"text":"Analyzing video..."}]},"append":true}}
data: {"statusUpdate":{"taskId":"task-uuid","status":{"state":"TASK_STATE_COMPLETED"}}}
```

### Storage Tiering

#### Get Storage Health
```http
GET /storage/health
```

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
  "rehydrate_priority": "standard"
}
```

#### Rehydrate Archived Media
```http
POST /storage/media/{media_id}/rehydrate
Content-Type: application/json

{
  "priority": "high",
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

#### Sync All Tiers
```http
POST /storage/sync-tiers
```

#### Record Media Access
```http
POST /storage/media/{media_id}/access
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

### Knowledge Graph

#### Graph Search
```http
POST /graph/search
Content-Type: application/json

{
  "query": "find all scenes with people and machinery",
  "video_id": "uuid",
  "depth": 2
}
```

**Multi-Video Graph Search:**
```http
POST /graph/search
Content-Type: application/json

{
  "query": "find common entities across videos",
  "video_ids": ["uuid1", "uuid2", "uuid3"],
  "depth": 2
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
    }
  ]
}
```

#### Get Video Hierarchy
```http
GET /graph/{video_id}/hierarchy
```

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

### Batch Processing (Azure OpenAI Batch API)

#### Submit Batch Job
```http
POST /batch/submit
Content-Type: application/json

{
  "video_ids": ["uuid1", "uuid2"],
  "operation": "vision_analysis",
  "priority": "low"
}
```

**Response:**
```json
{
  "batch_id": "batch-uuid",
  "status": "validating",
  "estimated_completion": "2024-01-20T15:00:00Z",
  "cost_estimate": {
    "frames": 500,
    "estimated_cost": 2.50
  }
}
```

#### Get Batch Status
```http
GET /batch/status/{batch_id}
```

**Response:**
```json
{
  "batch_id": "batch-uuid",
  "status": "completed",
  "progress": 100,
  "results": {
    "succeeded": 480,
    "failed": 20,
    "total": 500
  },
  "output_url": "https://..."
}
```

## WebSocket Endpoints

### Real-time Processing Updates

Connect to WebSocket for live updates:

```javascript
const ws = new WebSocket('ws://localhost:8000/ws/processing/{video_id}');

ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  console.log('Status:', data.status);
  console.log('Progress:', data.progress);
};
```

**Message Format:**
```json
{
  "type": "progress",
  "status": "processing",
  "progress": 45,
  "stage": "extracting_frames",
  "message": "Processing frame 45 of 100"
}
```

## Error Responses

All errors follow this format:

```json
{
  "detail": "Error message",
  "status_code": 400,
  "error_type": "ValidationError"
}
```

**Common Status Codes:**
- `400`: Bad Request - Invalid input
- `401`: Unauthorized - Missing/invalid authentication
- `403`: Forbidden - Insufficient permissions
- `404`: Not Found - Resource doesn't exist
- `422`: Unprocessable Entity - Validation error
- `429`: Too Many Requests - Rate limit exceeded
- `500`: Internal Server Error - Server-side error

## Rate Limiting

- **Standard endpoints**: 100 requests/minute
- **Upload endpoint**: 10 uploads/minute
- **Search endpoint**: 30 requests/minute

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

### 1. Use Batch Processing for Large Workloads
For processing 100+ frames, use the Batch API to save 50% on costs:
```json
{
  "use_batch_api": true,
  "priority": "low"
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
