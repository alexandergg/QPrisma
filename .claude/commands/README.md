# Claude Code Skills for QPrisma

This directory contains custom skills (slash commands) for Claude Code to accelerate QPrisma development.

## Quick Reference

| Skill | Description | Example |
|-------|-------------|---------|
| `/create-route` | Create FastAPI route | `/create-route media --prefix /api/v1/media` |
| `/create-service` | Create backend service | `/create-service export --azure --singleton` |
| `/create-tool` | Create LangGraph agent tool | `/create-tool search_entities --category search` |
| `/create-component` | Create React component | `/create-component VideoPlayer --type feature` |
| `/create-test` | Generate tests | `/create-test media_routes --type integration` |
| `/run-tests` | Execute tests | `/run-tests --type unit --coverage` |
| `/code-review` | Review code quality | `/code-review backend/services/ --focus security` |
| `/debug-agent` | Debug LangGraph agent | `/debug-agent --session abc123 --trace` |
| `/process-video` | Process video pipeline | `/process-video video.mp4 --preset balanced` |
| `/analyze-video` | Query video with agent | `/analyze-video abc123 "Who speaks first?"` |
| `/search-knowledge-graph` | Query Neo4j graph | `/search-knowledge-graph "find speakers" --media abc123` |
| `/neo4j-query` | Cypher query helper | `/neo4j-query find all entities in video` |
| `/generate-api-docs` | Generate API docs | `/generate-api-docs --format openapi` |
| `/setup-dev` | Setup dev environment | `/setup-dev --full` |
| `/deploy` | Deploy to Azure | `/deploy --env production --service all` |
| `/db-migrate` | Database migrations | `/db-migrate --db postgres --action upgrade` |
| `/optimize-performance` | Performance profiling | `/optimize-performance --target backend --profile` |
| `/git-workflow` | Git operations | `/git-workflow feature --branch add-upload` |
| `/security-check` | Security audit | `/security-check --scope all` |
| `/troubleshoot` | Debug common issues | `/troubleshoot connection-errors` |
| `/run-eval` | Run evaluation benchmarks | `/run-eval --expanded` |

## Skills by Category

### Code Generation

| Skill | Use Case |
|-------|----------|
| `/create-route` | New FastAPI endpoint with QPrisma patterns |
| `/create-service` | Backend service with lazy init, Azure integration |
| `/create-tool` | LangGraph agent tool with proper error handling |
| `/create-component` | React component with TypeScript, Tailwind |
| `/create-test` | Unit/integration/E2E tests |

### Code Quality

| Skill | Use Case |
|-------|----------|
| `/code-review` | Comprehensive code review (patterns, security, performance) |
| `/run-tests` | Execute pytest, Jest, Playwright tests |
| `/security-check` | Security audit and vulnerability scanning |
| `/optimize-performance` | Profiling and bottleneck identification |

### Video Processing

| Skill | Use Case |
|-------|----------|
| `/process-video` | FFmpeg processing with presets |
| `/analyze-video` | Chat with video agent |
| `/search-knowledge-graph` | Semantic search in Neo4j |
| `/neo4j-query` | Direct Cypher queries |

### Development Operations

| Skill | Use Case |
|-------|----------|
| `/setup-dev` | Development environment setup |
| `/deploy` | Azure deployment automation |
| `/db-migrate` | PostgreSQL/Neo4j migrations |
| `/git-workflow` | Branch management, PR workflow |
| `/troubleshoot` | Debug common issues |

### Evaluation

| Skill | Use Case |
|-------|----------|
| `/run-eval` | Run benchmarks (custom, Video-MME, MLVU, ablation) |

### Agent Development

| Skill | Use Case |
|-------|----------|
| `/debug-agent` | Troubleshoot LangGraph agent |
| `/create-tool` | Add new agent capabilities |

### Documentation

| Skill | Use Case |
|-------|----------|
| `/generate-api-docs` | OpenAPI, markdown, SDK generation |

## Skill Details

### `/create-route`
Creates a new FastAPI route module following QPrisma patterns:
- Pydantic request/response models
- Dependency injection with `Depends()`
- Proper authentication
- Service layer delegation

```
/create-route media --prefix /api/v1/media
```

### `/create-service`
Creates a backend service with:
- Lazy initialization pattern
- Singleton instance management
- Azure SDK integration (optional)
- Retry logic with tenacity
- Health check methods

```
/create-service export --azure --singleton
```

### `/create-tool`
Creates a LangGraph agent tool with:
- Proper `@tool` decorator
- Comprehensive docstring
- Dict return type (never raises)
- Truncation for context limits

```
/create-tool search_entities --category search
```

### `/code-review`
Performs comprehensive code review:
- Architecture layer compliance
- QPrisma pattern adherence
- Security vulnerability scan (OWASP)
- Performance anti-patterns
- Test coverage analysis

```
/code-review backend/services/video_processor.py --focus security
```

### `/analyze-video`
Interact with the video agent to analyze content:
- Natural language queries
- Timestamp navigation
- Entity extraction
- Transcript search

```
/analyze-video abc123 "What products are demonstrated?"
```

### `/troubleshoot`
Diagnose and fix common issues:
- Service connection errors
- Azure OpenAI issues
- Processing failures
- Agent problems

```
/troubleshoot redis-connection
```

## Creating New Skills

To add a new skill:

1. Create a markdown file: `.claude/commands/{skill-name}.md`
2. Follow this structure:

```markdown
# Skill Name

Brief description of what the skill does.

## Usage
\`\`\`
/skill-name <required_arg> [--optional_flag]
\`\`\`

## Instructions

Step-by-step guidance for Claude to follow.

## Code Examples

\`\`\`python
# Example implementations
\`\`\`

## Checklist
- [ ] Step 1 verified
- [ ] Step 2 completed
```

3. Include:
   - Clear usage syntax
   - Step-by-step instructions
   - Code templates with QPrisma patterns
   - Verification checklist

## QPrisma Context

All skills are tailored for the QPrisma stack:

| Layer | Technology | Key Patterns |
|-------|------------|--------------|
| Backend | FastAPI, Python 3.11+ | Async/await, Depends(), Pydantic |
| Agent | LangGraph, Azure OpenAI | ReAct pattern, tool calling |
| Frontend | Next.js 16, React 19 | SWR, Tailwind CSS 4 |
| Database | PostgreSQL, Neo4j | Alembic migrations, Cypher |
| Cache | Redis Stack | Checkpointing, queues |
| Storage | Azure Blob | Chunked upload |
| AI | GPT-4o, Whisper | Vision analysis, transcription |

## Related Files

- `../settings.json` - Claude Code project settings
- `../../CLAUDE.md` - Main project documentation
- `../agents/` - Custom subagent definitions
- `../../.github/copilot-instructions.md` - GitHub Copilot config

## Best Practices

1. **Use skills proactively** - They encode QPrisma patterns
2. **Chain skills** - e.g., `/create-service` then `/create-test`
3. **Review with skills** - `/code-review` after major changes
4. **Debug systematically** - `/troubleshoot` before manual debugging

## Contributing

To improve skills:
1. Test the skill in real scenarios
2. Add missing patterns or edge cases
3. Update examples with real code
4. Keep checklists actionable
