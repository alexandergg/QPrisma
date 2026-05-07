---
name: qprisma-security-triage
description: Triage QPrisma vulnerabilities, security advisories, auth issues, secret exposure, injection reports, and dependency alerts.
---

# QPrisma Security Triage Skill

Use this skill for security advisory review, vulnerability reports, CodeQL/dependency alerts, or
questions about exploitability.

## Required reads

1. `SECURITY.md`
2. `AGENTS.md`
3. `.github/agents/security-auditor.agent.md`
4. Exact implicated code paths
5. Current dependency manifests: `backend/pyproject.toml`, `frontend/package.json`, relevant Docker
   files, or workflow files

## Guardrails

- Do not close, downgrade, or disclose a report without code-backed evidence.
- Do not post advisory comments unless the user explicitly asks.
- Do not confuse optional hardening with required vulnerability remediation.
- Redact secrets, tenant IDs, user IDs, private endpoints, and raw logs.

## Close / downgrade bar

Close or downgrade only when evidence shows one of these:

- duplicate of an existing fixed issue/advisory
- invalid against current shipped behavior
- out of scope under `SECURITY.md`
- fixed before any affected release or deployment
- defense-in-depth only, with no boundary bypass or data exposure

Do not close only because `main` appears fixed if a deployed release or environment remains affected.

## Review method

1. Identify trust boundary: user, tenant, media asset, graph data, storage, hosted agent, CI secret,
   Azure resource, or local developer machine.
2. Verify exploit path with current code and configuration.
3. Check auth and authorization: `Depends(get_current_user)`, token validation, IDOR, and tenant/user
   scoping.
4. Check injection paths: Neo4j parameters, SQL bind params, shell commands, prompt/tool input,
   logging, and file paths.
5. Check secret handling: Key Vault, managed identity, GitHub OIDC, redaction, and generated artifacts.
6. Separate vulnerability status from optional hardening recommendations.

## Output format

```markdown
### Verdict
- exploitable / not exploitable / needs narrowing / needs more evidence

### Evidence
- Boundary:
- Implicated files:
- Attack path:
- Current mitigation:
- Affected deployment/release:

### Recommendation
- Required fix:
- Regression/security proof:
- Optional hardening:
```
