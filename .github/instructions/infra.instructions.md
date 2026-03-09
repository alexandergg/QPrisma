---
applyTo: "infra/**/*.bicep,infra/**/*.bicepparam,.github/workflows/*.yml,docker-compose.yml"
---

# Infrastructure and CI path-specific instructions

- Preserve OIDC-based Azure authentication patterns in workflows (`azure/login@v2` with federated credentials).
- Keep deployment safety mechanisms intact (health checks, rollback behavior, stale deployment cancellation).
- Use path-filtering patterns to avoid unnecessary builds/deployments when possible.
- Do not introduce plaintext secrets; use GitHub Secrets/Variables and Key Vault integrations.
- Keep workflow/action versions current with existing repository conventions unless compatibility requires otherwise.
- Prefer additive changes; avoid broad infra refactors unless explicitly requested.
