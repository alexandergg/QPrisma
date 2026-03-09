---
name: qprisma-code-review
description: Perform high-signal code review for QPrisma pull requests with focus on correctness, security, architecture, and test adequacy.
---

# QPrisma Code Review Skill

Use this skill when asked to review changes before merge.

## Review priorities

1. Correctness and regression risk.
2. Security and secret handling.
3. Architecture compliance (service layer, DI, agent/tool patterns).
4. Test coverage for changed behavior.

## Process

1. Inspect changed files and related tests.
2. Identify only impactful findings.
3. Provide severity, exact location, and concrete remediation.

## QPrisma guardrails

- Backend routes should delegate logic to services.
- Agent tools should return structured error dictionaries.
- Frontend changes should preserve typed interfaces and loading/error UX states.
- Infra/workflow changes must preserve OIDC auth and rollback safety.
