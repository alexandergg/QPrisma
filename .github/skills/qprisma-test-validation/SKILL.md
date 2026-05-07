---
name: qprisma-test-validation
description: Choose, run, rerun, or debug QPrisma backend/frontend/infra/evaluation validation with the cheapest safe proof path.
---

# QPrisma Test Validation Skill

Use this skill when validating code changes, reproducing failures, debugging CI, or selecting the
smallest reliable proof before handoff.

## Required reads

1. `AGENTS.md`
2. `TESTING.md`
3. Scoped instructions for changed files
4. Relevant `backend/pyproject.toml`, `frontend/package.json`, workflow, or evaluation config
5. Changed files and nearest tests

## Default rule

Prove the touched surface first. Do not reflexively run the whole suite.

1. Inspect the diff and classify the touched surface.
2. Reproduce narrowly before fixing when possible.
3. Run the smallest targeted test/check.
4. Fix root cause.
5. Rerun the same narrow proof.
6. Broaden only when the touched contract is shared or the focused proof is insufficient.

## Command routing

### Backend

```bash
cd backend
ruff check .
black --check .
pytest tests/ -v --tb=short -x -m "not integration and not e2e and not slow and not requires_azure and not requires_neo4j and not requires_postgres"
```

For focused proof, prefer:

```bash
cd backend
pytest tests/test_<module>.py -v --tb=short
```

### Frontend

```bash
cd frontend
npm run lint
npm run typecheck
npm test -- --ci
```

For focused proof, prefer:

```bash
cd frontend
npm test -- <test-file-or-pattern> --ci
```

### Infrastructure and workflows

- Bicep: validate or what-if the touched deployment scope when Azure context is available.
- GitHub Actions: inspect workflow syntax and job dependencies; run `git diff --check`.
- Docker: build only the touched image unless shared base/deployment behavior changed.

### Documentation, agents, skills, templates

```bash
git diff --check
```

Then manually verify paths, links, command snippets, required reads, guardrails, and output formats.

## Guardrails

- Do not add new tooling; use existing project commands.
- Do not run integration/e2e/cloud tests unless prerequisites are available or the user asks.
- Do not mask failures with broad retries. Capture the first actionable error.
- If tests require unavailable infrastructure, report the missing prerequisite and the smallest next
  proof.
- Prefer deterministic reruns of only failing subsets after triage.

## Output format

```markdown
### Validation run
- Surface:
- Commands:
- Result:

### Failures
- Command:
- Root cause:
- Recommended fix:

### Not run
- Gate:
- Reason:
- Next proof:
```
