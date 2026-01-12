# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**QPrisma** is an intelligent multimedia processing platform for analyzing video and image content using AI. It combines computer vision, LLMs, and advanced RAG to provide automatic content processing, conversational search, and semantic analysis of multimedia content.

Inspired by the NVIDIA Video Search and Summarization Blueprint, QPrisma uses Azure cloud services for scalable multimedia processing.

## Architecture

### Multi-Tier Architecture

```
Frontend (Next.js 16) ←→ Backend API (FastAPI) ←→ Azure Services
                              ↓
                      Processing Services
                    (Video, Audio, Vision AI)
                              ↓
                      Storage & Indexing
                   (Blob, PostgreSQL, Neo4j)
```

### Core Components

**Backend (Python)**
- **API Layer** (`backend/api/main.py`): FastAPI application with lazy-initialized Azure clients
- **Routes** (`backend/api/routes/`): Modular route files for API organization
  - `auth_routes.py`: Authentication and user management
  - `batch_routes.py`: Azure OpenAI Batch API management and cost tracking
  - `media_routes.py`: Upload, list, delete, search media
  - `processing_routes.py`: FFmpeg, batch, pipeline processing
  - `graph_routes.py`: Knowledge Graph operations
  - `chat_routes.py`: Conversational AI interfaces
  - `structure_routes.py`: Video structure and scene analysis
  - `cache_routes.py`: Cache management
  - `jobs_routes.py`: Background job tracking
  - `websocket_routes.py`: Real-time updates
- **Processing Services** (`backend/services/`):
  - `video_processor.py`: Frame extraction, GPT-4V analysis, embeddings
  - `ffmpeg_processor.py`: Ultra-fast video processing with FFmpeg
  - `audio_processor.py`: Audio transcription with Whisper
  - `batch_processor.py`: Azure OpenAI Batch API integration (50% cost savings)
  - `knowledge_graph.py`: Neo4j Knowledge Graph persistence
  - `graph_search_service.py`: Graph-based retrieval (hybrid search)
  - `embedding_service.py`: Text embeddings with caching
  - `cache_service.py`: Redis cache layer
- **Models** (`backend/models/`): Configuration models using Pydantic
- **Tasks** (`backend/tasks/`): Celery background tasks
- **Tests** (`backend/tests/`): API and service tests

**Frontend (TypeScript/React)**
- **Next.js 16** with App Router
- **Components** (`frontend/components/`):
  - `VideoProcessingStudio.tsx`: Main video processing interface
  - `VideoUpload.tsx`: Upload handling with progress tracking
  - `ProcessingConfig.tsx`: FFmpeg and processing configuration UI
  - `PipelineVisualizer.tsx`: Visual pipeline flow display
  - `VideoOverlay.tsx`: Video annotation and overlay tools
- **Pages** (`frontend/app/`):
  - `page.tsx`: Home/upload page
  - `video/[id]/page.tsx`: Video detail and processing page

**Azure Integration**
- Azure OpenAI: GPT-4o for vision analysis, text-embedding-3-large for embeddings
- Azure Blob Storage: Media file storage
- PostgreSQL: Metadata storage (replaces Cosmos DB)
- Neo4j: Knowledge Graph for retrieval
- Redis: Cache and Celery task queue

## Development Commands

### Backend

```bash
# Navigate to backend
cd backend

# Install dependencies (using uv - fast Python package manager)
uv pip install -e .

# Activate virtual environment
source .venv/bin/activate  # Linux/Mac
.venv\Scripts\activate     # Windows

# Run API server (development mode with auto-reload)
cd backend
python api/main.py
# Server runs at http://localhost:8000
# API docs at http://localhost:8000/docs

# Run tests
cd backend
pytest tests/

# Specific test files
pytest tests/test_api.py
pytest tests/test_azure_openai.py

# Run with FFmpeg processing test
python tests/create_test_video.py  # Creates test video
```

### Frontend

```bash
# Navigate to frontend
cd frontend

# Install dependencies
npm install

# Development server
npm run dev
# Runs at http://localhost:3000

# Production build
npm run build
npm run start

# Linting
npm run lint
```

## Environment Configuration

### Backend `.env` (backend/.env)

Required environment variables for Azure services:

```bash
# Azure Storage
AZURE_STORAGE_CONNECTION_STRING=<connection_string>
AZURE_STORAGE_CONTAINER_NAME=media

# Azure OpenAI
AZURE_OPENAI_ENDPOINT=https://<resource-name>.openai.azure.com/
AZURE_OPENAI_API_KEY=<your_key>
AZURE_OPENAI_DEPLOYMENT_GPT=gpt-4o
AZURE_OPENAI_DEPLOYMENT_EMBEDDING=text-embedding-3-large
AZURE_OPENAI_API_VERSION=2024-08-01-preview

# PostgreSQL (metadata storage)
DATABASE_URL=postgresql://qprisma:qprisma123@localhost:5432/qprisma

# Neo4j Knowledge Graph
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=qprisma123

# Redis
REDIS_URL=redis://localhost:6379/0

# JWT Authentication
JWT_SECRET_KEY=<your-secret-key>
```

See `backend/.env.example` for template.

### Frontend `.env.local` (frontend/.env.local)

```bash
NEXT_PUBLIC_API_URL=http://localhost:8000
```

## Key Technical Decisions

### Video Processing Pipeline

The platform uses **two processing approaches**:

1. **FFmpeg-based** (Ultra-fast, configurable):
   - Uses `FFmpegVideoProcessor` from `services/ffmpeg_processor.py`
   - Configured via `FFmpegProcessingConfig` presets (fast, balanced, quality, custom)
   - Supports hardware acceleration, parallel processing
   - See `models/ffmpeg_config.py` for configuration options

2. **OpenCV-based** (Traditional, more control):
   - Direct frame extraction with cv2
   - Used for legacy workflows

### Processing Presets

- **Fast**: 1 FPS, 720p, optimized for speed
- **Balanced**: 2 FPS, 1080p, good quality/speed trade-off (default)
- **Quality**: 5 FPS, original resolution, max quality
- **Custom**: User-defined configuration

### Azure OpenAI Integration

- **Global Batch API**: Siempre se usa para análisis de frames (50% más barato)
  - Requiere deployment tipo "Global Batch" en Azure OpenAI Studio
  - Sin rate limits restrictivos
  - PostgreSQL tracking opcional para monitoreo

#### Configuración de Global Batch

1. Azure OpenAI Studio → Deployments → Deploy model
2. Seleccionar "gpt-4o" → Tipo: **"Global Batch"**
3. Nombrar (ej: `gpt-4o-global-batch`)
4. Añadir a `.env`:
   ```bash
   AZURE_OPENAI_DEPLOYMENT_GPT_BATCH=gpt-4o-global-batch
   ```

#### Endpoints de Batch

- `GET /batch/status/{id}`: Estado del job
- `GET /batch/jobs`: Lista jobs del usuario
- `POST /batch/cancel/{id}`: Cancelar job
- `GET /batch/cost-summary`: Resumen de costos
- `GET /batch/estimate?frame_count=50`: Estimación de costo

### Object Detection (Currently Disabled)

The codebase includes infrastructure for:
- YOLO v8 object detection
- CLIP embeddings for multi-modal search
- Moondream service for vision tasks

These are currently disabled (`enable_object_detection = False` in VideoProcessor) but can be enabled for future features.

## Code Architecture Patterns

### Lazy Initialization

Azure clients use lazy initialization to avoid startup overhead:

```python
# In api/main.py
_blob_service = None
_db_service = None

def get_blob_service():
    global _blob_service
    if _blob_service is None:
        conn_string = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
        if conn_string:
            _blob_service = BlobServiceClient.from_connection_string(conn_string)
    return _blob_service

def get_database_service():
    global _db_service
    if _db_service is None:
        from services.database_service import get_database_service as get_db
        _db_service = get_db()
    return _db_service
```

### Pydantic Configuration Models

Processing configuration uses Pydantic for type safety and validation:
- `FFmpegProcessingConfig`: Video processing settings
- `ProcessingPreset`: Enum for preset configurations
- `ProcessingStatus`: Job status tracking
- See `backend/models/ffmpeg_config.py`

### Service Layer Pattern

Each processing capability is isolated in a service:
- Services are stateful (maintain Azure clients)
- Services are initialized once and reused
- Services expose clear interfaces for specific tasks

## API Endpoints

The API is organized into modular route files in `backend/api/routes/`:

**Media Operations** (`/media/*`):
- `POST /upload`: Upload video/image with optional processing config
- `GET /media`: List all processed videos
- `GET /media/{video_id}`: Get video metadata and analysis
- `DELETE /media/{video_id}`: Delete video and all related data

**Processing** (`/processing/*`):
- `POST /processing/ffmpeg/{video_id}`: Process video with FFmpeg pipeline
- `GET /processing/presets`: Get available processing presets
- `POST /processing/batch`: Submit batch processing job

**Knowledge Graph** (`/graph/*`):
- `POST /graph/search`: Semantic search in graph
- `GET /graph/{video_id}/hierarchy`: Get video structure hierarchy
- `POST /graph/expand`: Expand context from a node

**Chat** (`/chat/*`):
- `POST /chat`: Conversational search with RAG

**Authentication** (`/auth/*`):
- `POST /auth/login`: User authentication
- `POST /auth/register`: User registration

See http://localhost:8000/docs for interactive API documentation (60+ endpoints).

## Processing Flow

1. **Upload**: Video uploaded to Azure Blob Storage
2. **Metadata Creation**: Record created in PostgreSQL
3. **Frame Extraction**: FFmpeg extracts frames based on config
4. **Vision Analysis**: GPT-4o analyzes each frame (standard or batch API)
5. **Audio Processing**: Whisper transcribes audio track
6. **Embedding Generation**: text-embedding-3-large creates vectors
7. **Indexing**: Frames/scenes persisted in Neo4j Knowledge Graph

## Development Workflow

### Adding a New Processing Service

1. Create service file in `backend/services/`
2. Initialize in `api/main.py` with lazy loading pattern
3. Add configuration model to `backend/models/` if needed
4. Create route file in `api/routes/` and register in `api/routes/__init__.py`
5. Include router in `api/main.py`
6. Add tests in `backend/tests/`

### Frontend Component Development

- Use TypeScript for all components
- Follow Next.js 16 App Router patterns
- Use Tailwind CSS for styling
- Leverage React 19 features (compiler, actions)
- Components should be client-side (`'use client'`) if they use state/effects

## Testing

### Backend Testing Strategy

- Unit tests for individual services
- Integration tests for Azure service calls
- API endpoint tests with FastAPI TestClient
- Test files in `backend/tests/`

### Creating Test Media

```bash
cd backend/tests
python create_test_video.py  # Creates synthetic test video
```

## Cost Optimization

### Batch API Usage

For processing 100+ frames, use Batch API (50% savings):
- Configured via `use_batch_api: true` in processing config
- Automatic batching and result polling in `BatchProcessor`

### Storage Lifecycle

Videos are stored in Blob Storage with lifecycle policies:
- **Hot tier**: Recent/frequently accessed
- **Cool tier**: Archive after 90 days (recommended)
- See DECISIONES_TECNICAS.md for optimization strategies

## Azure Resource Setup

See `QUICK_START.md` for detailed Azure infrastructure setup including:
- Resource group creation
- Azure OpenAI deployment
- Neo4j configuration
- Cosmos DB setup
- Storage account configuration

## Deployment Strategy

### Recommended Evolution

1. **MVP**: Azure Container Apps (serverless, simple)
2. **Growth**: Azure Kubernetes Service (AKS) for scale
3. **Enterprise**: Multi-region AKS with full observability

See `ARQUITECTURA_QPRISMA.md` for complete deployment architecture.

## Technology Stack

**Backend**:
- Python 3.11+
- FastAPI (async web framework)
- OpenAI SDK (Azure OpenAI integration)
- OpenCV, Pillow (image processing)
- FFmpeg (video processing)
- Pydantic (configuration & validation)
- uv (fast package management)

**Frontend**:
- Next.js 16 (App Router)
- React 19
- TypeScript 5
- Tailwind CSS 4
- Lucide React (icons)
- Axios (HTTP client)
- ReactFlow (pipeline visualization)

**Services**:
- Azure OpenAI (GPT-4o, Embeddings, Whisper)
- Azure Blob Storage
- PostgreSQL (metadata storage)
- Neo4j Knowledge Graph
- Redis (cache and Celery)

## Important Notes

### FFmpeg Dependency

Backend requires FFmpeg installed on system:
```bash
# Ubuntu/Debian
sudo apt-get install ffmpeg

# macOS
brew install ffmpeg

# Windows
# Download from https://ffmpeg.org/download.html
```

### Development Mode

FastAPI runs with uvicorn auto-reload in development:
```python
# In api/main.py
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
```

### CORS Configuration

API allows all origins in development. Restrict in production:
```python
# In api/main.py
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Change to specific origins in production
    ...
)
```

## Documentation Reference

- `README.md`: Project overview and quick start
- `ARQUITECTURA_QPRISMA.md`: Complete system architecture and tech stack
- `DECISIONES_TECNICAS.md`: Technical decisions, comparisons, cost analysis
- `QUICK_START.md`: Step-by-step Azure setup guide
- `FFMPEG_README.md`: FFmpeg processing documentation
- `AUDIO_PROCESSING.md`: Audio transcription details
- `VIDEO_UPLOAD_SYSTEM.md`: Upload system architecture
- `PARALLEL_PROCESSING.md`: Parallel processing strategies
- `IMPLEMENTATION_SUMMARY.md`: Implementation status and roadmap

## Common Development Tasks

### Recreate Search Index
```bash
cd backend/tests
python recreate_index.py
```

### Test Azure OpenAI Connection
```bash
cd backend/tests
python test_azure_openai.py
```

### Test Batch Vision Processing
```bash
cd backend/tests
python test_batch_vision.py
```

### Configure CORS for Production
```bash
cd backend/scripts
python configure_cors.py
```
