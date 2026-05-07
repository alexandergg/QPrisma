## Summary

Describe the problem and fix in 2-5 bullets.

- Problem:
- Why it matters:
- What changed:
- What did not change (scope boundary):

## Change Type

- [ ] Bug fix
- [ ] Feature
- [ ] Refactor required for the fix
- [ ] Documentation
- [ ] Security hardening
- [ ] Infrastructure / CI/CD
- [ ] Evaluation / agent workflow

## Scope

- [ ] Backend API / services
- [ ] LangGraph agent / tools / memory
- [ ] Frontend UI / hooks / types
- [ ] Infrastructure / deployment
- [ ] Evaluation / benchmarks
- [ ] Documentation / Copilot agents / skills
- [ ] Tests only

## Related Issues / PRs

- Closes #
- Related #

## Root Cause

For bug fixes or regressions, explain why this happened. Otherwise write `N/A`.

- Root cause:
- Missing detection / guardrail:
- Implicated file or contract:

## Regression Test Plan

For behavior changes, name the smallest reliable proof that should catch regressions.

- [ ] Unit test
- [ ] Integration / seam test
- [ ] End-to-end or browser test
- [ ] Manual cloud / Azure verification
- [ ] Existing coverage is sufficient
- Target test or command:
- Scenario locked in:
- If no new test was added, why not:

## Verification Evidence

Include real behavior proof when the change is user-visible, workflow-facing, security-sensitive, or cloud/integration-dependent. Redact private data such as tenant IDs, tokens, IP addresses, private endpoints, user IDs, and raw Foundry payloads.

- Environment:
- Exact command or steps:
- Observed result:
- Evidence attached or pasted:
- What was not verified:

## Security and Compatibility

- New permissions/capabilities? (`Yes/No`)
- Secrets/tokens handling changed? (`Yes/No`)
- New/changed network calls? (`Yes/No`)
- Data access scope changed? (`Yes/No`)
- Backward compatible? (`Yes/No`)
- Config/env changes? (`Yes/No`)
- Migration needed? (`Yes/No`)
- If any answer needs explanation, add risk and mitigation:

## Checklist

- [ ] Code follows QPrisma style and architecture boundaries.
- [ ] Backend routes remain thin and preserve auth requirements.
- [ ] Agent tools preserve structured error payloads and compact/artifact-backed context.
- [ ] Frontend changes preserve typed interfaces, loading/error UX, and accessibility.
- [ ] Infra/workflow changes preserve OIDC, managed identity, health checks, and rollback safety.
- [ ] Documentation, API docs, changelog, Copilot agents, or skills were updated when behavior/workflows changed.
- [ ] Relevant focused tests/checks were run and results are included above.
- [ ] Review conversations addressed by this PR were replied to or resolved.
