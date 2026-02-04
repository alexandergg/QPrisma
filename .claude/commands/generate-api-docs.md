# Generate API Documentation

Generate and update OpenAPI documentation for QPrisma endpoints.

## Usage
```
/generate-api-docs [--format openapi|markdown|sdk] [--output <path>]
```

## OpenAPI Generation

### Export OpenAPI Schema
```bash
# Generate OpenAPI JSON
curl http://localhost:8000/openapi.json > docs/openapi.json

# Or via Python
python -c "
from api.main import app
import json
print(json.dumps(app.openapi(), indent=2))
" > docs/openapi.json
```

### FastAPI Documentation Patterns

#### Route Documentation
```python
from fastapi import APIRouter, Path, Query, Body, status
from pydantic import BaseModel, Field

router = APIRouter(
    prefix="/media",
    tags=["Media"],
    responses={
        401: {"description": "Not authenticated"},
        403: {"description": "Not authorized"},
    },
)


class MediaUploadResponse(BaseModel):
    """Response model for media upload."""

    media_id: str = Field(..., description="Unique identifier for uploaded media")
    status: str = Field(..., description="Upload status", examples=["uploaded"])
    url: str = Field(..., description="URL to access the media")

    model_config = {"json_schema_extra": {"example": {
        "media_id": "abc-123",
        "status": "uploaded",
        "url": "https://storage.blob.core.windows.net/media/abc-123.mp4"
    }}}


@router.post(
    "/upload",
    response_model=MediaUploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload media file",
    description="""
Upload a video or image file for processing.

## Supported Formats
- **Video**: MP4, MOV, AVI, WebM
- **Image**: JPEG, PNG, WebP

## Size Limits
- Maximum file size: 5GB
- For files > 100MB, chunked upload is recommended

## Processing
After upload, call `/processing/ffmpeg/{media_id}` to start analysis.
""",
    responses={
        201: {"description": "Media uploaded successfully"},
        400: {"description": "Invalid file format"},
        413: {"description": "File too large"},
    },
)
async def upload_media(
    file: UploadFile = File(..., description="Media file to upload"),
    title: str = Form(None, description="Optional title for the media"),
    description: str = Form(None, description="Optional description"),
    current_user: User = Depends(get_current_user),
) -> MediaUploadResponse:
    """Upload a media file for processing."""
    ...
```

#### Query Parameters Documentation
```python
@router.get(
    "/search",
    response_model=SearchResponse,
    summary="Search media content",
)
async def search_media(
    q: str = Query(
        ...,
        min_length=1,
        max_length=500,
        description="Search query in natural language",
        examples=["person speaking at podium"],
    ),
    media_id: str | None = Query(
        None,
        description="Filter by specific media ID",
    ),
    limit: int = Query(
        10,
        ge=1,
        le=100,
        description="Maximum number of results",
    ),
    offset: int = Query(
        0,
        ge=0,
        description="Number of results to skip",
    ),
    sort: SortOrder = Query(
        SortOrder.RELEVANCE,
        description="Sort order for results",
    ),
) -> SearchResponse:
    ...
```

#### Path Parameters Documentation
```python
@router.get(
    "/{media_id}",
    response_model=MediaDetails,
    summary="Get media details",
    responses={
        200: {"description": "Media details retrieved"},
        404: {"description": "Media not found"},
    },
)
async def get_media(
    media_id: str = Path(
        ...,
        description="Unique media identifier",
        examples=["abc-123-def-456"],
        pattern=r"^[a-z0-9-]+$",
    ),
) -> MediaDetails:
    ...
```

#### Request Body Documentation
```python
class ProcessingConfig(BaseModel):
    """Configuration for video processing."""

    preset: ProcessingPreset = Field(
        ProcessingPreset.BALANCED,
        description="Processing preset to use",
    )
    fps: float | None = Field(
        None,
        ge=0.1,
        le=30,
        description="Frames per second (overrides preset)",
    )
    enable_audio: bool = Field(
        True,
        description="Extract and transcribe audio",
    )
    use_batch_api: bool = Field(
        False,
        description="Use batch API for 50% cost savings",
    )

    model_config = {"json_schema_extra": {"example": {
        "preset": "balanced",
        "fps": 2.0,
        "enable_audio": True,
        "use_batch_api": True
    }}}


@router.post("/{media_id}/process")
async def process_media(
    media_id: str = Path(...),
    config: ProcessingConfig = Body(
        ...,
        description="Processing configuration",
        embed=True,
    ),
) -> ProcessingResponse:
    ...
```

## Markdown Documentation

### Generate from OpenAPI
```python
def generate_markdown_docs(openapi_spec: dict) -> str:
    """Generate markdown documentation from OpenAPI spec."""
    md = ["# QPrisma API Reference\n"]

    for path, methods in openapi_spec["paths"].items():
        for method, details in methods.items():
            md.append(f"## {method.upper()} {path}\n")
            md.append(f"{details.get('summary', '')}\n")
            md.append(f"\n{details.get('description', '')}\n")

            # Parameters
            if params := details.get("parameters"):
                md.append("\n### Parameters\n")
                md.append("| Name | In | Type | Required | Description |")
                md.append("|------|-----|------|----------|-------------|")
                for p in params:
                    md.append(
                        f"| {p['name']} | {p['in']} | "
                        f"{p['schema'].get('type', 'any')} | "
                        f"{'Yes' if p.get('required') else 'No'} | "
                        f"{p.get('description', '')} |"
                    )

    return "\n".join(md)
```

### Endpoint Documentation Template
```markdown
## POST /media/{media_id}/process

Start processing a previously uploaded video.

### Path Parameters

| Name | Type | Description |
|------|------|-------------|
| media_id | string | UUID of the uploaded media |

### Request Body

```json
{
  "preset": "balanced",
  "fps": 2.0,
  "enable_audio": true,
  "use_batch_api": true
}
```

### Response

**201 Created**

```json
{
  "job_id": "job-123",
  "status": "processing",
  "estimated_frames": 240
}
```

### Errors

| Status | Code | Description |
|--------|------|-------------|
| 404 | MEDIA_NOT_FOUND | Media ID does not exist |
| 422 | INVALID_CONFIG | Invalid processing configuration |
| 429 | RATE_LIMITED | Too many requests |

### Example

```bash
curl -X POST "https://api.qprisma.app/media/abc123/process" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"preset": "balanced", "use_batch_api": true}'
```
```

## SDK Generation

### Python SDK Template
```python
"""QPrisma Python SDK - Auto-generated from OpenAPI spec."""

from typing import Any
import httpx


class QPrismaClient:
    """QPrisma API client."""

    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url.rstrip("/")
        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=30.0,
        )

    async def upload_media(
        self,
        file: bytes,
        filename: str,
        title: str | None = None,
    ) -> dict[str, Any]:
        """
        Upload a media file for processing.

        Args:
            file: File content as bytes
            filename: Original filename
            title: Optional title

        Returns:
            Upload response with media_id
        """
        response = await self.client.post(
            "/media/upload",
            files={"file": (filename, file)},
            data={"title": title} if title else {},
        )
        response.raise_for_status()
        return response.json()

    async def process_media(
        self,
        media_id: str,
        preset: str = "balanced",
        use_batch_api: bool = False,
    ) -> dict[str, Any]:
        """
        Start processing a media file.

        Args:
            media_id: ID from upload response
            preset: Processing preset (fast, balanced, quality)
            use_batch_api: Use batch API for cost savings

        Returns:
            Processing job details
        """
        response = await self.client.post(
            f"/media/{media_id}/process",
            json={
                "preset": preset,
                "use_batch_api": use_batch_api,
            },
        )
        response.raise_for_status()
        return response.json()

    async def search(
        self,
        query: str,
        media_id: str | None = None,
        limit: int = 10,
    ) -> dict[str, Any]:
        """
        Search video content.

        Args:
            query: Natural language search query
            media_id: Optional filter by video
            limit: Maximum results

        Returns:
            Search results with timestamps
        """
        response = await self.client.get(
            "/media/search",
            params={
                "q": query,
                "media_id": media_id,
                "limit": limit,
            },
        )
        response.raise_for_status()
        return response.json()

    async def close(self):
        """Close the client."""
        await self.client.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()


# Usage example
async def main():
    async with QPrismaClient(
        base_url="https://api.qprisma.app",
        api_key="your-api-key",
    ) as client:
        # Upload
        with open("video.mp4", "rb") as f:
            result = await client.upload_media(f.read(), "video.mp4")

        # Process
        job = await client.process_media(
            result["media_id"],
            preset="balanced",
            use_batch_api=True,
        )

        # Search
        results = await client.search(
            "person speaking",
            media_id=result["media_id"],
        )
```

### TypeScript SDK Template
```typescript
/**
 * QPrisma TypeScript SDK - Auto-generated from OpenAPI spec
 */

export interface UploadResponse {
  media_id: string;
  status: string;
  url: string;
}

export interface ProcessingConfig {
  preset?: 'fast' | 'balanced' | 'quality';
  fps?: number;
  enable_audio?: boolean;
  use_batch_api?: boolean;
}

export class QPrismaClient {
  private baseUrl: string;
  private apiKey: string;

  constructor(baseUrl: string, apiKey: string) {
    this.baseUrl = baseUrl.replace(/\/$/, '');
    this.apiKey = apiKey;
  }

  private async fetch<T>(
    path: string,
    options: RequestInit = {}
  ): Promise<T> {
    const response = await fetch(`${this.baseUrl}${path}`, {
      ...options,
      headers: {
        Authorization: `Bearer ${this.apiKey}`,
        'Content-Type': 'application/json',
        ...options.headers,
      },
    });

    if (!response.ok) {
      throw new Error(`API error: ${response.status}`);
    }

    return response.json();
  }

  async uploadMedia(
    file: File,
    title?: string
  ): Promise<UploadResponse> {
    const formData = new FormData();
    formData.append('file', file);
    if (title) formData.append('title', title);

    const response = await fetch(`${this.baseUrl}/media/upload`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${this.apiKey}` },
      body: formData,
    });

    return response.json();
  }

  async processMedia(
    mediaId: string,
    config: ProcessingConfig = {}
  ): Promise<{ job_id: string; status: string }> {
    return this.fetch(`/media/${mediaId}/process`, {
      method: 'POST',
      body: JSON.stringify(config),
    });
  }

  async search(
    query: string,
    mediaId?: string,
    limit = 10
  ): Promise<{ results: Array<{ timestamp: number; description: string }> }> {
    const params = new URLSearchParams({ q: query, limit: String(limit) });
    if (mediaId) params.set('media_id', mediaId);

    return this.fetch(`/media/search?${params}`);
  }
}
```

## Documentation CI/CD

```yaml
# .github/workflows/docs.yml
name: Generate API Docs

on:
  push:
    paths:
      - 'backend/api/**'

jobs:
  generate-docs:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Generate OpenAPI
        run: |
          cd backend
          pip install -e .
          python -c "
          from api.main import app
          import json
          with open('../docs/openapi.json', 'w') as f:
              json.dump(app.openapi(), f, indent=2)
          "

      - name: Commit docs
        run: |
          git config user.name github-actions
          git config user.email github-actions@github.com
          git add docs/openapi.json
          git diff --staged --quiet || git commit -m "docs: update OpenAPI spec"
          git push
```

## Checklist
- [ ] All endpoints documented with summaries
- [ ] Request/response models have field descriptions
- [ ] Examples provided for complex types
- [ ] Error responses documented
- [ ] Authentication requirements specified
- [ ] OpenAPI spec exported
- [ ] SDK generated if needed
