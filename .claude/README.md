# Claude Code & AI Agent Configuration

This folder contains configuration for Claude Code and reference documentation for AI-assisted development.

## Structure

```
.claude/
├── README.md              # This file
├── settings.json          # Claude Code project settings
├── settings.local.json    # Local overrides (gitignored)
├── commands/              # Slash commands for Claude Code (21 commands)
│   ├── README.md          # Commands documentation
│   └── *.md               # Individual command files
└── agents/                # Reference docs for AI agents (17 specialists)
    ├── README.md          # Agents documentation
    └── *.md               # Individual agent files
```

## What Each File Does

| File/Folder | Used By | Purpose |
|-------------|---------|---------|
| `CLAUDE.md` (root) | Claude Code | Main project instructions - **always read** (includes current LangGraph memory/context architecture) |
| `settings.json` | Claude Code | Project paths, conventions, code style |
| `commands/*.md` | Claude Code | Slash commands (e.g., `/create-route`) |
| `agents/*.md` | Reference only | Specialist documentation (not auto-loaded) |
| `.github/copilot-instructions.md` | GitHub Copilot | Code style and patterns for Copilot (includes hybrid memory + rehydration patterns) |

## Commands (21 total)

### Code Generation
| Command | Description |
|---------|-------------|
| `/create-route` | Create FastAPI route module |
| `/create-service` | Create backend service with lazy init |
| `/create-tool` | Create LangGraph agent tool |
| `/create-component` | Create React component |
| `/create-test` | Generate pytest/Jest tests |

### Video Processing
| Command | Description |
|---------|-------------|
| `/process-video` | Process video through pipeline |
| `/analyze-video` | Query video with agent |
| `/search-knowledge-graph` | Query Neo4j graph |
| `/neo4j-query` | Direct Cypher query helper |

### Code Quality
| Command | Description |
|---------|-------------|
| `/code-review` | Comprehensive code review |
| `/run-tests` | Execute tests with coverage |
| `/security-check` | Security audit |
| `/optimize-performance` | Performance profiling |

### Development Operations
| Command | Description |
|---------|-------------|
| `/setup-dev` | Setup development environment |
| `/deploy` | Deploy to Azure |
| `/db-migrate` | Database migrations |
| `/git-workflow` | Git branch operations |
| `/troubleshoot` | Debug common issues |
| `/debug-agent` | Debug LangGraph agent |
| `/generate-api-docs` | Generate API documentation |

## Agents (17 total)

### QPrisma Specialists
| Agent | Purpose |
|-------|---------|
| `qprisma-specialist` | QPrisma patterns, troubleshooting, review |
| `backend-architect` | FastAPI, services, Neo4j, Azure |
| `frontend-developer` | Next.js 16, React 19, Tailwind |
| `ai-engineer` | LangGraph agents, Azure OpenAI, RAG |
| `video-processor` | FFmpeg, GPT-4o vision, Whisper |

### General Purpose
| Agent | Purpose |
|-------|---------|
| `code-reviewer` | Quick code review checklist |
| `code-quality-reviewer` | Detailed architecture review |
| `test-engineer` | Testing strategies |
| `devops-engineer` | CI/CD, deployment |
| `documentation-expert` | Technical writing |
| `performance-engineer` | Optimization, profiling |
| `python-pro` | Python best practices |
| `api-documenter` | API documentation |
| `architect-review` | Architecture review |
| `context-manager` | Context management |
| `security-check` | Security specialist |
| `ui-ux-designer` | UI/UX patterns |

## Commands vs Skills

| Aspect | Commands (this repo) | Skills (Agent Skills spec) |
|--------|---------------------|---------------------------|
| Format | Single `.md` file | Folder with `SKILL.md` + assets |
| Assets | No bundled files | Scripts, templates, data |
| Location | `.claude/commands/` | `.claude/skills/` |
| Complexity | Simple instructions | Complex workflows |

**Note:** This project uses **commands** (simpler). Skills are folders with bundled assets following the [Agent Skills specification](https://agentskills.io/).

## GitHub Copilot

Copilot uses `.github/copilot-instructions.md` for code suggestions:
- Code style guidelines (Python/TypeScript)
- QPrisma architecture patterns
- Common imports and conventions
- Error handling patterns

## Adding New Commands

1. Create a markdown file: `.claude/commands/{command-name}.md`
2. Structure it with:
   - **Usage** section showing invocation syntax
   - **Instructions** with step-by-step guidance
   - **Code Examples** with QPrisma patterns
   - **Checklist** for verification

See `commands/README.md` for detailed instructions.
