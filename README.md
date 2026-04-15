<p align="left">
  <img src="docs/assets/logo.png" alt="QPrisma Logo" width="600">
</p>


[![OpenSSF Best Practices](https://bestpractices.coreinfrastructure.org/projects/1/badge)](https://bestpractices.coreinfrastructure.org/projects/1)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Next.js 16](https://img.shields.io/badge/Next.js-16-black)](https://nextjs.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.135+-009688.svg)](https://fastapi.tiangolo.com/)
[![Azure OpenAI](https://img.shields.io/badge/Azure-OpenAI-0078D4)](https://azure.microsoft.com/en-us/products/ai-services/openai-service)

<p align="center">
  <a href="#what-qprisma-solves">What QPrisma Solves</a> •
  <a href="#core-capabilities">Core Capabilities</a> •
  <a href="#architecture">Architecture</a> •
  <a href="#quick-start-local">Quick Start</a> •
  <a href="#azure-deployment">Azure Deployment</a> •
  <a href="#documentation">Documentation</a>
</p>

---

> [!IMPORTANT]
> **Responsible AI**: QPrisma uses Azure OpenAI models (including multimodal and transcription models). You are responsible for compliant, ethical use in your organization. See the [Azure OpenAI Transparency Note](https://learn.microsoft.com/en-us/legal/cognitive-services/openai/transparency-note).

## What QPrisma Solves

QPrisma is a personal project for exploring Microsoft Azure AI Foundry and AI services in general through a practical video intelligence and knowledge retrieval workflow.

It ingests media, extracts visual/audio context, builds semantic and graph indexes, and lets teams query the content in natural language for fast investigation, compliance verification, and decision support.

### Typical outcomes

- Reduce time-to-insight from hours of manual review to conversational lookup.
- Improve traceability with timestamped evidence from video and audio.
- Reuse institutional knowledge through structured memory and retrieval.

## Core Capabilities

- **Video understanding**: Frame-level analysis, scene structure, and multimodal interpretation.
- **Conversational retrieval (RAG)**: Ask natural language questions across one or many videos.
- **Knowledge graph enrichment**: Entity type normalization (30+ alias mappings with CONCEPT fallback), description enrichment (up to 5 accumulated descriptions per entity), semantic relation storage (evidence_count, weight), and multi-pass gleaning extraction for improved recall.
- **Community detection**: Leiden-based hierarchical entity clustering (multi-resolution, leidenalg/igraph) with LLM-generated thematic summaries, integrated into hybrid search. Louvain fallback when leidenalg is unavailable.
- **Graph hierarchy**: Chapter nodes (Video→Chapter→Scene with LLM titles/summaries), Topic graph nodes (ABOUT edges to Video and Entity), cross-video entity resolution (SAME_ENTITY edges with similarity scores), and LLM-calibrated relationship strength weights (1–10 → 0.1–1.0) on semantic edges.
- **Dense temporal chains**: Graph-native time walking via NEXT_FRAME / NEXT_SEGMENT / NEXT_SCENE relationships with temporal adjacency scoring.
- **Multi-video chat**: Compare findings across selected assets in one query flow.
- **Async processing at scale**: Queue-based background processing with live status updates.
- **Cost-aware processing**: Batch-friendly architecture for non-urgent workloads.

### Memory and Context Engineering

QPrisma uses layered memory to maintain answer quality on long workflows:

- **Operational state** via LangGraph checkpointer (resume/retry continuity).
- **Full tool payload artifacts** in Redis + Blob + PostgreSQL metadata.
- **Long-term user memory** via Azure AI Foundry Memory Store (per-user, Entra ID scoped).
- **Server-side conversation history** via Foundry Conversations API.
- **Prompt-time ranking** with recency and semantic/lexical signals.

## Architecture

> Multi-region deployment: **West Europe** (compute + AI Foundry), **North Europe** (PostgreSQL). Full infrastructure defined as code with [Azure Bicep](infra/main.bicep). See [Infrastructure docs](docs/INFRASTRUCTURE.md) for details.

### Key architecture views

<table>
  <tr>
    <td width="33%" valign="top">
      <a href="docs/ARCHITECTURE_PORTFOLIO.md">
        <img src="docs/assets/architecture/qprisma-system-context.svg" alt="QPrisma system context diagram" width="100%">
      </a>
      <br>
      <strong>System context</strong><br>
      Users, platform boundary, Azure dependencies, and delivery boundary.<br>
      <a href="docs/ARCHITECTURE_PORTFOLIO.md">Portfolio guide</a> · <a href="docs/assets/architecture/qprisma-system-context.svg">SVG asset</a>
    </td>
    <td width="33%" valign="top">
      <a href="docs/VIDEO_INGESTION_ARCHITECTURE.md">
        <img src="docs/assets/architecture/video-ingestion-pipeline.svg" alt="QPrisma video ingestion pipeline diagram" width="100%">
      </a>
      <br>
      <strong>Video ingestion</strong><br>
      Upload, queueing, worker processing, enrichment, and persistence flow.<br>
      <a href="docs/VIDEO_INGESTION_ARCHITECTURE.md">Architecture doc</a> · <a href="docs/assets/architecture/video-ingestion-pipeline.svg">SVG asset</a>
    </td>
    <td width="33%" valign="top">
      <a href="docs/HOSTED_AGENT_RETRIEVAL_ARCHITECTURE.md">
        <img src="docs/assets/architecture/agent-search-rag-flow.svg" alt="QPrisma hosted agent retrieval diagram" width="100%">
      </a>
      <br>
      <strong>Hosted agent retrieval</strong><br>
      Request handling, tool routing, hybrid retrieval, and grounded response flow.<br>
      <a href="docs/HOSTED_AGENT_RETRIEVAL_ARCHITECTURE.md">Architecture doc</a> · <a href="docs/assets/architecture/agent-search-rag-flow.svg">SVG asset</a>
    </td>
  </tr>
</table>

See the [Architecture Portfolio](docs/ARCHITECTURE_PORTFOLIO.md) for the full set of diagrams and narratives, including [Azure deployment](docs/INFRASTRUCTURE.md), [data and knowledge lifecycle](docs/DATA_KNOWLEDGE_ARCHITECTURE.md), and [security and trust boundaries](docs/SECURITY_IDENTITY_ARCHITECTURE.md).

### Technology Stack

| Area | Technology |
|---|---|
| Frontend | Next.js 16, React 19, Tailwind |
| Backend | FastAPI, Python 3.11+, Pydantic |
| Agent Runtime | LangGraph (video agent) |
| AI | Azure OpenAI multimodal/chat/embedding/transcription models |
| Video Decode | PyAV (C-level FFmpeg bindings), FFmpeg subprocess fallback |
| Scene Detection | PySceneDetect (AdaptiveDetector + ContentDetector) |
| Transcription | Azure Whisper (default), faster-whisper (optional, 4× faster, INT8/Silero VAD) |
| Graph Intelligence | Community detection (Leiden via leidenalg/igraph, Louvain fallback), dense temporal chains, cross-video entity resolution, entity normalization |
| Data | PostgreSQL, Neo4j, Redis |
| Storage | Azure Blob Storage |
| Infrastructure | Bicep, GitHub Actions, Azure Container Apps |

## Security

QPrisma includes multiple layers of security hardening:

- **Microsoft Entra ID authentication** (MSAL v5 popup flow) on protected REST and WebSocket endpoints; some operational endpoints remain public, including `GET /cache/health`
- **Token/session invalidation** is handled by Microsoft Entra ID and the client-side MSAL token lifecycle; there is no backend `POST /auth/logout` route or Redis-backed JTI denylist
- **Rate limiting** (slowapi) on auth, A2A, and media endpoints
- **Security headers** middleware (X-Content-Type-Options, X-Frame-Options, X-XSS-Protection, etc.)
- **Dev autologin guard** — `allow_dev_autologin` is rejected in production/staging by config validators
- **Error sanitization** — no internal details leaked in API error responses
- **Non-root Docker containers** (`appuser`, UID 1001)
- **Parameterized credentials** in docker-compose (`${VAR:-default}`)
- **CI security scanning** with `pip-audit`, `npm audit`, and CodeQL
- **CI/CD least-privilege permissions** scoped per workflow with OIDC federated credentials

## Quick Start (Local)

### Prerequisites

- Python 3.11+
- Node.js 20+
- Docker Desktop
- Azure subscription and Azure OpenAI access

### 1) Start local infrastructure

```bash
git clone https://github.com/alexandergg/QPrisma.git
cd QPrisma
docker-compose up -d
```

### 2) Configure environment files

```bash
# from repository root
cp backend/.env.example backend/.env
cp frontend/.env.local.example frontend/.env.local
```

Update `backend/.env` with your Azure settings and required service credentials.

### 3) Run backend

```bash
cd backend
python -m pip install uv
uv venv

# Windows
.venv\Scripts\activate

# macOS/Linux
# source .venv/bin/activate

uv pip install -e .
python api/main.py
```

### 4) Run frontend

```bash
cd frontend
npm install
npm run dev
```

### Local endpoints

- Frontend: http://localhost:3000
- API docs: http://localhost:8000/docs
- Neo4j Browser: http://localhost:7474

## Repository Layout

```text
backend/
  api/           # FastAPI routes and dependency wiring
  agent/         # LangGraph graphs, nodes, tools, prompts
  core/          # Config, errors, retry, concurrency, logging
  services/      # Business logic services
  models/        # Pydantic/DB models
  tasks/         # Celery workers
  evaluation_foundry/  # Azure AI Foundry evaluation (data, custom evaluators)
frontend/
  app/           # Next.js App Router
  components/    # React components
  lib/           # API client and utilities
infra/
  main.bicep     # Root IaC orchestrator
  modules/       # Azure resource modules
  parameters/    # Environment parameter files
```

## Troubleshooting

### Backend cannot start

- Ensure virtual environment is activated.
- Reinstall dependencies with `uv pip install -e .`.
- Verify Docker services are running: `docker ps`.

### Frontend cannot reach backend

- Confirm backend is up at http://localhost:8000/docs.
- Verify `NEXT_PUBLIC_API_URL` in `frontend/.env.local`.

### Azure OpenAI errors

- Validate endpoint/key/API version in `backend/.env`.
- Confirm model deployments exist and names match configuration.

## Development Scripts

The `scripts/` directory contains utilities for development and maintenance:

| Script | Purpose |
|--------|---------|
| `reset_all_data.py` | Wipe all data from Blob Storage, Neo4j, PostgreSQL, and Redis for a fresh start |
| `deploy_agent.py` | Deploy QPrisma hosted agent to Microsoft AI Foundry |
| `setup_entra_apps.ps1` | Set up Entra ID (Azure AD) applications for authentication |
| `migrate_entra_auth.sql` | Database migration for Entra ID authentication |
| `setup_memory_store.py` | Provision Foundry Memory Store for long-term agent memory |
| `resolve_agent_version.py` | Resolve the current agent version for deployment tagging |

### Resetting all data

> **⚠️ Warning:** This script permanently deletes data and cannot be undone.
> Only use against **development** environments. The script refuses to run
> against production/staging unless `--allow-production` is explicitly passed.

```bash
# Dry-run — shows what would be deleted without touching anything
python scripts/reset_all_data.py

# Execute the reset (interactive confirmation)
python scripts/reset_all_data.py --execute

# Skip specific stores
python scripts/reset_all_data.py --execute --skip-blob --skip-redis

# Non-interactive mode (CI / automation)
python scripts/reset_all_data.py --execute --yes
```

## Azure Deployment

QPrisma includes production-oriented Azure deployment assets:

- **IaC**: Bicep modules under `infra/`
- **Runtime**: Azure Container Apps (API, Frontend, Worker)
- **CI/CD**: GitHub Actions workflows for test, build, infra deploy, and app deploy

### CI/CD workflows

| Workflow | Purpose |
|---|---|
| `ci.yml` | Backend + frontend quality checks (lint, typecheck, test) |
| `build-and-push.yml` | Build and push container images to ACR |
| `deploy-infra.yml` | Provision/update Azure infrastructure (Bicep) |
| `deploy-app.yml` | Deploy application revisions with health checks and rollback |
| `deploy-ai-foundry.yml` | Deploy AI Foundry resources and model deployments |
| `deploy-hosted-agent.yml` | Deploy QPrisma hosted agent to AI Foundry |
| `evaluate-agent.yml` | Run automated agent evaluation with custom evaluators |
| `release.yml` | Create GitHub Releases from version tags |
| `version-bump.yml` | Bump version across pyproject.toml, package.json, CITATION.cff |
| `codeql.yml` | CodeQL security analysis |
| `copilot-setup-steps.yml` | Copilot development environment setup |

For full details, see [docs/INFRASTRUCTURE.md](./docs/INFRASTRUCTURE.md).

## Evaluation

QPrisma uses **Azure AI Foundry** for automated agent evaluation. The hosted agent (`qprisma-video-agent`) is evaluated using the `microsoft/ai-agent-evals` GitHub Action with built-in and custom evaluators.

**Triggers**: Runs automatically after agent deployment, weekly for regression monitoring, and on-demand via `workflow_dispatch`.

**Evaluators**:
- **Built-in**: Coherence, fluency, groundedness, task adherence, tool call accuracy, safety (6 categories)
- **Custom**: Temporal specificity (video timestamp quality), source grounding (video evidence citation)

```bash
# Generate evaluation data files locally (dry-run)
cd backend
python -m evaluation_foundry.generate_eval_data --dry-run

# Register custom evaluators with Foundry
python -m evaluation_foundry.register_evaluators --dry-run
```

See `.github/workflows/evaluate-agent.yml` for the full CI/CD evaluation pipeline.

## Documentation

### Architecture

- [Architecture Portfolio Index](./docs/ARCHITECTURE_PORTFOLIO.md) - Solution Architect entry point and reading map
- [Architecture Deep Dive](./docs/ARCHITECTURE.md) - System overview, ingestion, graph, retrieval, and deployment summary
- [Backend Technical Architecture](./docs/BACKEND_ARCHITECTURE.md) - Backend modules, API layer, agent runtime, services, and tasks
- [Memory Architecture](./docs/MEMORY_ARCHITECTURE.md) - Checkpointer, artifacts, and Foundry Memory Store status
- [Infrastructure Guide](./docs/INFRASTRUCTURE.md) - Azure resources, Bicep, CI/CD, security, and deployment flow

### Architecture Deep Dives

- [Video Ingestion Architecture](./docs/VIDEO_INGESTION_ARCHITECTURE.md) - Blob-first upload, queue-based orchestration, and multimodal enrichment
- [Hosted Agent Retrieval Architecture](./docs/HOSTED_AGENT_RETRIEVAL_ARCHITECTURE.md) - Foundry hosted agent, LangGraph loop, hybrid retrieval, and prompt-time context
- [Data and Knowledge Architecture](./docs/DATA_KNOWLEDGE_ARCHITECTURE.md) - Data lifecycle, graph hierarchy, embeddings, lineage, and ownership
- [Security and Identity Architecture](./docs/SECURITY_IDENTITY_ARCHITECTURE.md) - Entra ID, WebSocket auth, managed identities, secrets, and trust boundaries
- [Operations, NFRs, and Trade-offs](./docs/OPERATIONS_NFRS_ARCHITECTURE.md) - Reliability, scaling, observability, cost, and runbook-oriented review
- [Solution Architect Playbook](./docs/SOLUTION_ARCHITECT_PLAYBOOK.md) - Reusable documentation and diagramming guidance for Data and AI solutions

### Reference

- [API Documentation](./API_DOCUMENTATION.md)
- [Testing Guide](./TESTING.md)
- [Contributing Guide](./CONTRIBUTING.md)
- [Changelog](./CHANGELOG.md)
- [Security Policy](./SECURITY.md)
- [Code of Conduct](./CODE_OF_CONDUCT.md)

## Contributing

Contributions are welcome. Please review [CONTRIBUTING.md](./CONTRIBUTING.md) before opening a pull request.

## License

This project is licensed under the [MIT License](./LICENSE).

## Disclaimer

QPrisma is a solution accelerator provided "as-is" without warranties. It is intended as a foundation for custom enterprise implementations.
