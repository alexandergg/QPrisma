# QPrisma

<p align="center">
  <strong>Intelligent Multimedia Processing Platform</strong>
</p>

<p align="center">
  <a href="#features">Features</a> •
  <a href="#architecture">Architecture</a> •
  <a href="#quick-start">Quick Start</a> •
  <a href="#documentation">Documentation</a> •
  <a href="#contributing">Contributing</a>
</p>

---

## Overview

**QPrisma** is an AI-powered multimedia processing platform for analyzing video and image content. It combines computer vision, large language models (LLMs), and advanced RAG (Retrieval-Augmented Generation) to provide automatic content processing, conversational search, and semantic analysis.

Inspired by the [NVIDIA Video Search and Summarization Blueprint](https://developer.nvidia.com/blog/build-a-video-search-and-summarization-agent-with-nvidia-nim-blueprints/), QPrisma leverages Azure cloud services for scalable, production-ready multimedia processing.

### Use Cases

- 🎥 **Video Search & Summarization** - Search through hours of video content using natural language
- 🏭 **Warehouse Automation** - Monitor and analyze operational procedures
- 🏢 **Smart Spaces** - Intelligent monitoring and analysis
- ✅ **SOP Validation** - Verify standard operating procedures through video analysis

## Features

- **🎬 Video Processing** - Frame extraction, scene detection, and visual analysis with GPT-4o Vision
- **🎵 Audio Transcription** - Whisper-powered audio-to-text transcription
- **🔍 Semantic Search** - Vector embeddings for intelligent content retrieval
- **🧠 Knowledge Graph** - Neo4j-based entity and relationship extraction
- **💬 Conversational AI** - Chat interface for querying video content
- **📊 Batch Processing** - Azure OpenAI Batch API integration (50% cost savings)
- **⚡ Real-time Updates** - WebSocket support for live processing status
- **🔐 Authentication** - JWT-based user authentication

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Frontend (Next.js 16)                    │
│                    React 19 + TypeScript + Tailwind             │
└─────────────────────────────┬───────────────────────────────────┘
                              │
┌─────────────────────────────▼───────────────────────────────────┐
│                     Backend API (FastAPI)                       │
│                    Python 3.11+ + Pydantic                      │
├─────────────────────────────────────────────────────────────────┤
│  Routes: auth | media | processing | chat | graph | batch       │
└─────────────────────────────┬───────────────────────────────────┘
                              │
┌─────────────────────────────▼───────────────────────────────────┐
│                    Processing Services                          │
│  video_processor | ffmpeg_processor | audio_processor           │
│  batch_processor | knowledge_graph | embedding_service          │
└─────────────────────────────┬───────────────────────────────────┘
                              │
┌─────────────────────────────▼───────────────────────────────────┐
│                     Azure Services                              │
│  OpenAI (GPT-4o, Whisper, Embeddings) | Blob Storage            │
├─────────────────────────────────────────────────────────────────┤
│                     Data Layer                                  │
│  PostgreSQL (metadata) | Neo4j (graph) | Redis (cache/queue)    │
└─────────────────────────────────────────────────────────────────┘
```

## Tech Stack

| Layer | Technology |
|-------|------------|
| **Frontend** | Next.js 16, React 19, TypeScript, Tailwind CSS |
| **Backend** | FastAPI, Python 3.11+, Celery |
| **AI/ML** | Azure OpenAI (GPT-4o, Whisper, text-embedding-3-large) |
| **Database** | PostgreSQL, Neo4j, Redis |
| **Storage** | Azure Blob Storage |
| **Video** | FFmpeg, OpenCV |

## Quick Start

### Prerequisites

- Python 3.11+
- Node.js 20+
- Docker & Docker Compose
- Azure account with OpenAI service

### 1. Clone the repository

```bash
git clone https://github.com/yourusername/qprisma.git
cd qprisma
```

### 2. Start infrastructure services

```bash
docker-compose up -d
```

This starts PostgreSQL, Neo4j, and Redis.

### 3. Configure environment

```bash
# Backend
cp backend/.env.example backend/.env
# Edit backend/.env with your Azure credentials

# Frontend
cp frontend/.env.local.example frontend/.env.local
```

### 4. Install and run backend

```bash
cd backend

# Install dependencies with uv (recommended)
pip install uv
uv pip install -e .

# Activate virtual environment
source .venv/bin/activate  # Linux/Mac
# .venv\Scripts\activate   # Windows

# Run API server
python api/main.py
```

API available at http://localhost:8000 (Swagger docs at `/docs`)

### 5. Install and run frontend

```bash
cd frontend

# Install dependencies
npm install

# Run development server
npm run dev
```

Frontend available at http://localhost:3000

## Project Structure

```
qprisma/
├── backend/
│   ├── api/
│   │   ├── main.py              # FastAPI application
│   │   └── routes/              # API route modules
│   ├── services/                # Business logic services
│   ├── models/                  # Pydantic models
│   ├── tasks/                   # Celery background tasks
│   └── tests/                   # Backend tests
├── frontend/
│   ├── app/                     # Next.js app router pages
│   ├── components/              # React components
│   ├── contexts/                # React contexts
│   ├── hooks/                   # Custom React hooks
│   └── lib/                     # Utilities and API client
├── scripts/                     # Deployment and utility scripts
├── docker-compose.yml           # Infrastructure services
└── README.md
```

## Documentation

- [Development Roadmap](./DEVELOPMENT_ROADMAP.md) - Project milestones and planned features
- [Frontend UX Redesign](./FRONTEND_UX_REDESIGN.md) - UI/UX design specifications
- [API Documentation](http://localhost:8000/docs) - OpenAPI/Swagger documentation (when running)

## Development

### Backend

```bash
cd backend

# Run tests
pytest tests/

# Format code
black .
ruff check --fix .

# Run with auto-reload
python api/main.py
```

### Frontend

```bash
cd frontend

# Development server
npm run dev

# Type checking
npm run typecheck

# Linting
npm run lint

# Production build
npm run build
```

## Environment Variables

### Backend (`backend/.env`)

| Variable | Description |
|----------|-------------|
| `AZURE_OPENAI_ENDPOINT` | Azure OpenAI endpoint URL |
| `AZURE_OPENAI_API_KEY` | Azure OpenAI API key |
| `AZURE_STORAGE_CONNECTION_STRING` | Azure Blob Storage connection |
| `DATABASE_URL` | PostgreSQL connection string |
| `NEO4J_URI` | Neo4j connection URI |
| `REDIS_URL` | Redis connection URL |
| `JWT_SECRET_KEY` | Secret key for JWT tokens |

See [`backend/.env.example`](./backend/.env.example) for all options.

## Contributing

We welcome contributions! Please see our [Contributing Guide](./CONTRIBUTING.md) for details.

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## License

This project is licensed under the MIT License - see the [LICENSE](./LICENSE) file for details.

## Acknowledgments

- [NVIDIA Video Search and Summarization Blueprint](https://developer.nvidia.com/blog/build-a-video-search-and-summarization-agent-with-nvidia-nim-blueprints/) - Inspiration for the architecture
- [Azure OpenAI Service](https://azure.microsoft.com/en-us/products/ai-services/openai-service) - AI/ML backbone
- [Neo4j](https://neo4j.com/) - Knowledge Graph database
