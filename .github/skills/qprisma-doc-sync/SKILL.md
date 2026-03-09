---
name: qprisma-doc-sync
description: Keep QPrisma documentation synchronized with implementation and workflow behavior after code or infrastructure changes.
---

# QPrisma Documentation Sync Skill

Use this skill when code, APIs, workflows, or architecture behavior changes.

## Process

1. Identify impacted docs from changed files.
2. Update existing documentation sections with precise command/path updates.
3. Verify no contradictory statements remain across docs.

## Primary documentation targets

- `README.md`
- `API_DOCUMENTATION.md`
- `TESTING.md`
- `docs/ARCHITECTURE.md`
- `docs/BACKEND_ARCHITECTURE.md`
- `docs/INFRASTRUCTURE.md`

## Rules

- Prefer edits to existing docs over creating new files.
- Keep examples runnable and aligned with current repository commands.
- Explicitly note required external prerequisites.
