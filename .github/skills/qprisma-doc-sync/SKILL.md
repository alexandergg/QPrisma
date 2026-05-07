---
name: qprisma-doc-sync
description: Keep QPrisma documentation, Copilot instructions, agents, skills, PR templates, and changelog synchronized with implementation and workflow behavior.
---

# QPrisma Documentation Sync Skill

Use this skill when code, APIs, workflows, architecture, evaluation behavior, or maintainer process
changes.

## Required reads

1. `AGENTS.md`
2. `.github/instructions/docs.instructions.md`
3. Changed implementation/workflow files
4. Existing docs that mention the changed behavior
5. `CHANGELOG.md` when the change is user-visible, operator-visible, release-facing, or workflow-facing

## Primary documentation targets

- `README.md`
- `API_DOCUMENTATION.md`
- `TESTING.md`
- `CHANGELOG.md`
- `docs/ARCHITECTURE.md`
- `docs/BACKEND_ARCHITECTURE.md`
- `docs/INFRASTRUCTURE.md`
- `docs/MEMORY_ARCHITECTURE.md`
- `backend/agent/ARCHITECTURE.md`
- `.github/copilot-instructions.md`
- `.github/agents/*.agent.md`
- `.github/skills/*/SKILL.md`
- `.github/PULL_REQUEST_TEMPLATE.md`

## Guardrails

- Prefer edits to existing docs over creating new files.
- Do not document aspirational behavior; document shipped or explicitly planned workflow only.
- Do not duplicate large sections. Cross-reference the source of truth.
- Keep examples runnable and aligned with current repository commands.
- Explicitly note external prerequisites such as Azure, Neo4j, PostgreSQL, Foundry, or deployed hosted
  agent.
- Redact private values in examples and evidence.

## Process

1. Identify impacted docs from changed files and user-visible/operator-visible behavior.
2. Search for stale references across docs, Copilot instructions, agents, skills, and PR templates.
3. Update existing sections with precise paths, commands, environment variables, and constraints.
4. Add changelog entries only when the behavior or workflow matters to users, operators, or maintainers.
5. Verify there are no contradictory statements across docs.

## Validation

- Run `git diff --check` for text formatting issues.
- Inspect Markdown headings, links, commands, and examples touched by the change.
- For docs generated from implementation, run the existing generator/check command if one exists.

## Output format

```markdown
### Updated docs
- `path`: change summary

### Consistency checks
- ...

### Remaining gaps
- ...
```
