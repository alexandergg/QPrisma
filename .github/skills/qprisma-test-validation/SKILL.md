---
name: qprisma-test-validation
description: Run QPrisma backend/frontend validation workflows after code changes. Use for test execution, focused regression checks, and CI parity verification.
---

# QPrisma Test Validation Skill

Use this skill when the task includes validating code changes.

## Workflow

1. Detect changed areas and run the smallest relevant checks first.
2. Escalate to broader validation if focused checks fail or if shared contracts changed.
3. Report pass/fail with failing command, root cause, and recommended fix.

## Commands

### Backend

```bash
cd backend && pytest tests/ -v --tb=short -x -m "not integration and not e2e and not slow and not requires_azure and not requires_neo4j and not requires_postgres"
```

### Frontend

```bash
cd frontend && npm run lint && npm run typecheck && npm test -- --ci --coverage
```

## Rules

- Do not add new tooling; use existing project commands.
- Prefer deterministic reruns of only failing subsets after triage.
- If tests require unavailable infrastructure, report explicitly and provide next actionable step.
