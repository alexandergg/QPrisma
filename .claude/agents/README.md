# Agent Reference Documentation

This folder contains reference documentation for AI-assisted development specialists. These are **not auto-loaded** by Claude Code but serve as context and patterns for different development tasks.

## QPrisma-Specific Agents

| Agent | Purpose |
|-------|---------|
| `qprisma-specialist.md` | QPrisma stack overview, patterns, review checklist |
| `backend-architect.md` | FastAPI, services, Neo4j, Azure integration |
| `frontend-developer.md` | Next.js 16, React 19, SWR, Tailwind |
| `ai-engineer.md` | LangGraph agents, Azure OpenAI, RAG |
| `video-processor.md` | FFmpeg, GPT-4o vision, Whisper, indexing |

## General Purpose Agents

| Agent | Purpose |
|-------|---------|
| `code-reviewer.md` | Quick code review checklist |
| `code-quality-reviewer.md` | Detailed architecture and quality review |
| `test-engineer.md` | Testing strategies and patterns |
| `devops-engineer.md` | CI/CD, deployment, infrastructure |
| `documentation-expert.md` | Technical writing and docs |
| `performance-engineer.md` | Optimization and profiling |

## Usage

These files can be referenced when:
- Planning new features
- Reviewing code
- Understanding QPrisma patterns
- Onboarding new developers

To use as context in Claude Code, you can ask:
> "Review this PR using the patterns in .claude/agents/qprisma-specialist.md"

## File Format

Each agent file follows this structure:
```markdown
---
name: agent-name
description: Brief description
tools: Read, Write, Edit, Bash
model: sonnet
---

Context and instructions...
```

The frontmatter is informational - Claude Code doesn't auto-load these files.
