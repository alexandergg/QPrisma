# Setup Development Environment

Complete setup guide for QPrisma local development.

## Usage
```
/setup-dev [--full] [--backend-only] [--frontend-only]
```

## Prerequisites

### Required Software
```bash
# Check versions
python --version    # 3.11+
node --version      # 20+
docker --version    # 24+
ffmpeg -version     # 6+

# Windows: Install via winget
winget install Python.Python.3.11
winget install OpenJS.NodeJS.LTS
winget install Docker.DockerDesktop
winget install Gyan.FFmpeg

# macOS: Install via brew
brew install python@3.11 node@20 ffmpeg
brew install --cask docker

# Linux (Ubuntu)
sudo apt install python3.11 nodejs npm ffmpeg docker.io
```

## Quick Start (Full Stack)

```bash
# 1. Clone repository
git clone https://github.com/your-org/qprisma.git
cd qprisma

# 2. Start infrastructure
docker-compose up -d redis postgres neo4j

# 3. Setup backend
cd backend
uv venv && source .venv/bin/activate  # Linux/Mac
uv venv && .venv\Scripts\activate     # Windows
uv pip install -e ".[dev]"
cp .env.example .env
# Edit .env with your Azure credentials

# 4. Setup frontend
cd ../frontend
npm install
cp .env.example .env.local

# 5. Run services
# Terminal 1: Backend
cd backend && python api/main.py

# Terminal 2: Frontend
cd frontend && npm run dev

# Terminal 3: Celery worker (optional)
cd backend && celery -A tasks.celery_app worker -l INFO
```

## Infrastructure Services

### Docker Compose
```bash
# Core services
docker-compose up -d redis postgres neo4j

# With Celery workers
docker-compose --profile full up -d

# With debug UIs (pgAdmin, Redis Commander, Neo4j Browser)
docker-compose --profile debug up -d

# View logs
docker-compose logs -f redis postgres neo4j
```

### Service Ports
| Service | Port | URL |
|---------|------|-----|
| API | 8000 | http://localhost:8000/docs |
| Frontend | 3000 | http://localhost:3000 |
| PostgreSQL | 5432 | - |
| Neo4j Browser | 7474 | http://localhost:7474 |
| Neo4j Bolt | 7687 | bolt://localhost:7687 |
| Redis | 6379 | - |
| pgAdmin | 5050 | http://localhost:5050 |
| Redis Commander | 8081 | http://localhost:8081 |
| Flower (Celery) | 5555 | http://localhost:5555 |

### Default Credentials
| Service | Username | Password |
|---------|----------|----------|
| PostgreSQL | qprisma | qprisma123 |
| Neo4j | neo4j | qprisma123 |
| pgAdmin | admin@qprisma.local | qprisma123 |
| Flower | admin | qprisma123 |

## Backend Setup

### Using uv (Recommended)
```bash
cd backend

# Create virtual environment
uv venv

# Activate
source .venv/bin/activate  # Linux/Mac
.venv\Scripts\activate     # Windows

# Install dependencies
uv pip install -e ".[dev]"
```

### Using pip
```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### Environment Variables
```bash
# backend/.env

# Azure OpenAI (required)
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_OPENAI_API_KEY=your-api-key
AZURE_OPENAI_DEPLOYMENT_GPT=gpt-4o
AZURE_OPENAI_DEPLOYMENT_EMBEDDING=text-embedding-3-large
AZURE_OPENAI_API_VERSION=2024-08-01-preview

# Azure Storage (required)
AZURE_STORAGE_CONNECTION_STRING=DefaultEndpointsProtocol=https;...
AZURE_STORAGE_CONTAINER_NAME=media

# Optional Azure deployments
AZURE_OPENAI_DEPLOYMENT_GPT_BATCH=gpt-4o-global-batch
AZURE_OPENAI_DEPLOYMENT_WHISPER=whisper

# Database connections
DATABASE_URL=postgresql://qprisma:qprisma123@localhost:5432/qprisma
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=qprisma123
REDIS_URL=redis://localhost:6379/0

# Auth
JWT_SECRET_KEY=your-secret-key-change-in-production

# Optional
LOG_LEVEL=INFO
CELERY_BROKER_URL=redis://localhost:6379/1
```

### Initialize Database
```bash
cd backend

# PostgreSQL migrations (if using Alembic)
alembic upgrade head

# Neo4j indexes
python -c "
from services.knowledge_graph import get_knowledge_graph_service
kg = get_knowledge_graph_service()
kg.create_indexes()
"
```

### Run Backend
```bash
cd backend
python api/main.py

# Or with uvicorn directly
uvicorn api.main:app --reload --host 0.0.0.0 --port 8000
```

## Frontend Setup

### Install Dependencies
```bash
cd frontend
npm install
```

### Environment Variables
```bash
# frontend/.env.local
NEXT_PUBLIC_API_URL=http://localhost:8000
```

### Run Frontend
```bash
npm run dev

# Production build
npm run build && npm start
```

## Verification

### Check Backend Health
```bash
# API health
curl http://localhost:8000/health

# Swagger docs
open http://localhost:8000/docs
```

### Check Services
```bash
# PostgreSQL
psql -h localhost -U qprisma -d qprisma -c "SELECT 1"

# Neo4j
cypher-shell -u neo4j -p qprisma123 "RETURN 1"

# Redis
redis-cli ping
```

### Run Tests
```bash
# Backend
cd backend && pytest tests/ -v

# Frontend
cd frontend && npm test
```

## IDE Setup

### VS Code Extensions
```json
{
  "recommendations": [
    "ms-python.python",
    "ms-python.vscode-pylance",
    "charliermarsh.ruff",
    "dbaeumer.vscode-eslint",
    "bradlc.vscode-tailwindcss",
    "prisma.prisma",
    "redhat.vscode-yaml"
  ]
}
```

### VS Code Settings
```json
{
  "python.defaultInterpreterPath": "./backend/.venv/bin/python",
  "python.formatting.provider": "none",
  "[python]": {
    "editor.defaultFormatter": "charliermarsh.ruff",
    "editor.formatOnSave": true
  },
  "ruff.lint.args": ["--config=backend/pyproject.toml"],
  "eslint.workingDirectories": ["frontend"],
  "typescript.preferences.importModuleSpecifier": "relative"
}
```

## Troubleshooting

### Docker Issues
```bash
# Reset all containers
docker-compose down -v
docker-compose up -d

# Check logs
docker-compose logs -f <service_name>
```

### Python Environment
```bash
# Recreate venv
rm -rf .venv
uv venv && uv pip install -e ".[dev]"
```

### Port Conflicts
```bash
# Find process using port
lsof -i :8000  # macOS/Linux
netstat -ano | findstr :8000  # Windows
```

### Neo4j Connection
```bash
# Verify Neo4j is ready
docker-compose logs neo4j | grep "Started"

# Reset Neo4j data
docker-compose down neo4j
docker volume rm qprisma_neo4j_data
docker-compose up -d neo4j
```

## Checklist
- [ ] Python 3.11+ installed
- [ ] Node.js 20+ installed
- [ ] Docker running
- [ ] FFmpeg installed
- [ ] Docker services started
- [ ] Backend .env configured with Azure credentials
- [ ] Frontend .env.local configured
- [ ] Backend running at http://localhost:8000
- [ ] Frontend running at http://localhost:3000
- [ ] All health checks passing
