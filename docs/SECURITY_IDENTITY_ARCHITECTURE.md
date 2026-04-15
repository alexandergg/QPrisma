# QPrisma Security and Identity Architecture

This document explains how QPrisma authenticates users, protects service-to-service communication, and enforces trust boundaries across the platform.

## Scope

This view focuses on:

- Microsoft Entra ID sign-in
- API and WebSocket authentication patterns
- service-to-service identity
- Key Vault and secret management
- trust boundaries between clients, services, and data platforms
- security controls and review points

## Related artifacts

- Diagram: `docs/qprisma-identity-trust-boundaries.drawio`
- Platform architecture: `docs/INFRASTRUCTURE.md`
- Deep implementation reference: `docs/BACKEND_ARCHITECTURE.md`
- Portfolio index: `docs/ARCHITECTURE_PORTFOLIO.md`

## Security architecture summary

QPrisma uses different identity patterns for different trust boundaries:

- **human-to-application** access is handled with Microsoft Entra ID
- **service-to-Azure-service** access uses managed identity where possible
- **application secret resolution** is centralized through Azure Key Vault
- **CI/CD deployment access** uses GitHub Actions OIDC federation instead of long-lived cloud credentials

This mix is typical of a mature Azure-native architecture because no single identity mechanism is appropriate for every boundary.

## 1. User authentication model

The frontend integrates with Microsoft Entra ID and acquires bearer tokens for authenticated API access.

On the backend, authentication dependencies validate the token and derive the current user context used to scope data access.

### Why this matters

For a Solution Architect, the important point is not just "login exists." The identity provider is externalized, the backend trusts signed tokens instead of local passwords, and business data access is tied to the authenticated subject.

## 2. API authentication boundary

REST endpoints use bearer-token authentication for user-scoped operations.

Examples include:

- upload and media operations
- chat operations
- user profile/configuration lookups

The backend uses the authenticated user context as part of downstream authorization and data filtering.

## 3. WebSocket authentication model

QPrisma supports more than one WebSocket authentication pattern depending on the endpoint:

| Endpoint shape | Authentication pattern |
|---|---|
| `/ws/jobs/{job_id}` | token provided as query parameter |
| `/ws/user/{user_id}` | token provided as query parameter |
| `/ws/all` | token sent as the first WebSocket message |

### Architectural implication

WebSocket channels often become blind spots in architecture documentation. QPrisma explicitly documents and implements them as authenticated boundaries, not as trusted internal channels.

## 4. Authorization and tenant scoping

Authentication answers who the caller is. Authorization answers what data that caller may access.

In QPrisma, authorization relies on:

- authenticated user identity
- user ownership checks in application services
- user-aware filtering in retrieval paths
- user-aware media context passed into agent flows

### Why this matters for the hosted agent

The hosted agent is not a free-floating model endpoint. It is part of a user-scoped application workflow. Media context, graph retrieval, and answer generation must remain aligned to the authenticated user boundary.

## 5. Service-to-service identity

The Azure platform uses managed identity to reduce dependency on static secrets.

### Current identity pattern

The infrastructure provisions:

- system-assigned managed identities on application workloads
- a user-assigned managed identity reused for Azure Container Registry pulls and Key Vault access patterns

This allows runtime services to authenticate to Azure resources through Azure AD-backed identity instead of embedding long-lived credentials in application configuration.

## 6. Secret management

Azure Key Vault is the central secret store for platform secrets and connection material that should not live in source control.

Examples of protected secrets include:

- Neo4j password
- PostgreSQL connection material
- API keys when managed identity is not applicable
- application configuration secrets used by containerized workloads

### Architectural value

Key Vault centralization improves:

- secret rotation options
- secret inventory visibility
- least-privilege access design
- separation between IaC, CI/CD, and runtime secret consumers

## 7. CI/CD trust boundary

GitHub Actions deploys infrastructure and application changes using OIDC-based Azure login.

This is a strong pattern because:

- GitHub does not need to store a reusable Azure service principal secret
- the trust is federated and workload identity-based
- deployment permissions can be tightly scoped in Azure

From an architecture review perspective, this is an important maturity signal.

## 8. Trust boundaries

The QPrisma trust model can be described in five major zones:

| Zone | Example components | Security concern |
|---|---|---|
| Client zone | Browser, Next.js frontend, authenticated user | Token handling, session integrity, UI exposure |
| Application zone | FastAPI API, worker, hosted agent integration | Auth enforcement, business authorization, prompt integrity |
| Messaging/cache zone | Redis, Pub/Sub, Celery broker | Internal event trust, queue isolation, transient data handling |
| Data zone | Blob, PostgreSQL, Neo4j | Data confidentiality, tenant filtering, backup posture |
| Control plane zone | GitHub Actions, Azure Resource Manager, Key Vault | Deployment trust, secret access, RBAC governance |

These zones should be explicit in architecture diagrams because most real security issues appear at the transitions between zones.

## 9. Security controls visible in the current architecture

| Control area | Current pattern |
|---|---|
| Identity provider | Microsoft Entra ID |
| API auth | Bearer token validation |
| WebSocket auth | Authenticated connection bootstrap |
| Secret storage | Azure Key Vault |
| Azure resource access | Managed identity where possible |
| Deployment auth | GitHub Actions OIDC federation |
| Data access scoping | User-aware backend and retrieval filtering |

## 10. Security review questions

When reviewing QPrisma professionally, these are the most useful architecture questions:

1. Are all user-facing channels authenticated, including WebSockets?
2. Is every downstream data query scoped to the authenticated user and media set?
3. Are managed identities used wherever Azure SDK access allows it?
4. Which secrets still require key-based access and why?
5. Are hosted agent calls guaranteed to preserve tenant context?
6. Can audit and observability traces reconstruct user and conversation activity safely?

## 11. Risks and trade-offs

| Trade-off | Benefit | Cost / review point |
|---|---|---|
| Mixed auth patterns across WebSockets | Supports practical realtime use cases | Requires careful endpoint-specific documentation |
| Multiple identities in the platform | Better least-privilege design | More RBAC and operational complexity |
| Hosted agent integration | Stronger AI capability boundary | More context-integrity and prompt-governance concerns |
| Polyglot data platform | Better workload fit | More data access policies to review |

## How to present this professionally

For a Solution Architect audience, present QPrisma security in this order:

1. **who authenticates users**: Microsoft Entra ID
2. **where trust enters**: frontend to backend API/WebSocket boundary
3. **how services authenticate to Azure**: managed identities and Key Vault
4. **where secrets live**: Key Vault, not source control
5. **where trust transitions happen**: client, app, messaging, data, control plane

That structure turns security from a checklist into an architecture narrative.
