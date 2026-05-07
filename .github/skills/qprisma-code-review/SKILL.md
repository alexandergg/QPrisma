---
name: qprisma-code-review
description: Perform high-signal QPrisma PR/diff review focused on correctness, security, architecture, regression risk, and proof quality.
---

# QPrisma Code Review Skill

Use this skill when asked to review changes before merge, inspect a diff, validate a PR, or assess
whether implementation and tests are sufficient.

## Required reads

1. `AGENTS.md`
2. `.github/copilot-instructions.md`
3. Scoped `.github/instructions/*.instructions.md` for changed files
4. Changed files plus nearby tests/callers
5. `.github/PULL_REQUEST_TEMPLATE.md` when reviewing a PR body

## Review priorities

1. Correctness and regression risk.
2. Security, secret handling, and authorization boundaries.
3. Architecture compliance: services, DI, agent/tool contracts, frontend state, infra safety.
4. Test and evidence adequacy.
5. Documentation/changelog/workflow consistency.

## Guardrails

- Do not report style-only issues unless they create defect or maintenance risk.
- Do not approve speculative fixes without root-cause evidence.
- Do not ask for broad rewrites when a narrow remediation solves the defect.
- Every finding must include exact file/path and concrete remediation.
- Separate blocking issues from optional hardening.

## Process

1. Inspect the changed files and classify touched surfaces: backend, agent, frontend, infra, docs,
   tests, evaluation, or workflow.
2. For each changed surface, read the nearest owner module, caller, and related test.
3. Verify QPrisma guardrails:
   - Backend routes delegate to services and preserve auth.
   - Agent tools return structured errors and keep payloads compact/artifact-backed.
   - Frontend uses explicit types, loading/error UX, and accessible controls.
   - Infra/workflows preserve OIDC, managed identity, health checks, and rollback.
4. Check PR evidence: problem, scope boundary, root cause, regression proof, verification, risks.
5. Rank only impactful findings by severity.

## Proof gates

- Read the owner module and nearest tests for every blocking finding.
- Verify PR evidence covers root cause and regression risk for bug fixes.
- If proof is missing, report it under `Proof gaps` rather than inventing confidence.

## Output format

```markdown
### Critical
- [File:Line] Issue -> Remediation

### High
- [File:Line] Issue -> Remediation

### Medium
- [File:Line] Issue -> Remediation

### Low
- [File:Line] Issue -> Remediation

### Proof gaps
- ...

### Positive observations
- ...
```
