---
name: qprisma-architecture-check
description: Validate that changes follow QPrisma architecture boundaries across backend services, frontend components, agent flows, infrastructure, documentation, and workflow automation.
---

# QPrisma Architecture Check Skill

Use this skill when reviewing design consistency, cross-layer impact, service boundaries, or structural
changes before implementation or merge.

## Required reads

1. `AGENTS.md`
2. `.github/copilot-instructions.md`
3. Scoped instructions for touched files:
   - `.github/instructions/backend.instructions.md`
   - `.github/instructions/frontend.instructions.md`
   - `.github/instructions/infra.instructions.md`
   - `.github/instructions/docs.instructions.md`
4. Affected code, tests, docs, workflows, and adjacent owner modules

## Guardrails

- Do not approve architecture changes based only on the diff. Read the owner module and at least one
  caller/consumer path.
- Do not suggest broad refactors unless the current change crosses a boundary that cannot be fixed
  narrowly.
- Preserve auth requirements, service-layer ownership, settings-based configuration, and managed
  identity/OIDC patterns.
- Separate required remediation from optional cleanup.

## Validation checklist

### Backend
- Route handlers stay orchestration-only.
- Business logic lives in `backend/services/`.
- Service access goes through dependency/lazy singleton patterns.
- Config uses `core.config.settings`, not direct environment access.
- Neo4j and SQL queries are parameterized and batched where practical.

### Agent
- LangGraph state, graph nodes, and tools preserve current wiring and tool contracts.
- Tool functions return structured error payloads and compact results.
- Artifact-backed context and Foundry Memory Store patterns remain intact.
- Observability uses structured logs/metrics without leaking payloads.

### Frontend
- Next.js App Router conventions remain intact.
- Client components use `'use client'` only when needed.
- API data paths keep typed interfaces, loading/error states, and accessibility.

### Infrastructure and CI/CD
- OIDC, managed identity, Key Vault, health probes, autoscaling, rollback, and path-filtered builds
  remain intact.
- Deployment changes include validation/what-if or an explicit reason if blocked.

### Documentation and workflow assets
- Docs, agents, skills, templates, and changelog describe current behavior.
- New workflow surfaces include proof gates, scope boundaries, and required reads.

## Output format

```markdown
### Architecture verdict
- aligned / needs changes / blocked

### Aligned items
- ...

### Violations
- [File:Line] Boundary crossed -> Required remediation

### Optional improvements
- ...

### Required proof
- ...
```
