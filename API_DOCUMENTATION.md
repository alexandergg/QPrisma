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

#### Chat with Media
```http
POST /chat
Content-Type: application/json

{
  "message": "What safety issues are present in the video?",
  "video_id": "uuid",
  "session_id": "chat-session-uuid"
}
```

**Response (Streaming):**
```
data: {"type": "text", "content": "I found several safety issues:\n"}
data: {"type": "text", "content": "1. Worker without helmet at 00:45\n"}
data: {"type": "reference", "timestamp": 45.2, "description": "..."}
data: {"type": "done"}
```

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
