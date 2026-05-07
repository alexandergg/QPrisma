# QPrisma Agent Playbook

Root rules for AI-assisted work in QPrisma. Use this with `.github/copilot-instructions.md`,
path-specific `.github/instructions/*.instructions.md`, `.github/agents/*.agent.md`, and
`.github/skills/*/SKILL.md`.

## Start

- Repo: `https://github.com/alexandergg/qprisma`.
- Use repo-relative paths in explanations, issues, PRs, and review comments.
- Read scoped instructions before editing: `.github/instructions/backend.instructions.md`,
  `.github/instructions/frontend.instructions.md`, `.github/instructions/infra.instructions.md`,
  or `.github/instructions/docs.instructions.md`.
- High-confidence changes only: inspect current code/docs, verify the implicated path, and run the
  smallest meaningful proof before handoff.
- Reuse existing services, helpers, hooks, agents, and workflow patterns. Search before adding new
  abstractions.
- Do not expose secrets, tokens, tenant identifiers, private endpoints, or raw Foundry payloads in
  logs, docs, PR comments, or screenshots.
- If behavior depends on an external SDK or Azure service, verify current docs/source/contracts before
  assuming defaults, error shapes, API names, or preview behavior.

## Repo map

- Backend API: `backend/api/` with FastAPI app wiring in `main.py`, DI in `dependencies.py`, and
  route modules in `routes/`.
- Backend services: `backend/services/` owns business logic, database access, graph search,
  media storage, Foundry clients, memory, and processing orchestration.
- Agent runtime: `backend/agent/` owns LangGraph state, graph wiring, nodes, tools, prompts,
  hosted-agent entrypoints, and observability helpers.
- Evaluation: `backend/evaluation_foundry/`, `.github/workflows/evaluate-agent.yml`, and
  `.github/workflows/benchmark-video-mme.yml`.
- Frontend: `frontend/app/` for Next.js App Router pages, `frontend/components/`, `frontend/hooks/`,
  `frontend/contexts/`, `frontend/lib/`, and `frontend/types/`.
- Video pipeline: `databricks/video-pipeline/`.
- Infrastructure: `infra/main.bicep`, `infra/modules/`, `infra/parameters/`, `azure.yaml`,
  Dockerfiles, and `docker-compose.yml`.
- Automation and AI workflow assets: `.github/workflows/`, `.github/actions/`, `.github/agents/`,
  `.github/skills/`, `.github/instructions/`, `.github/hooks/`.
- Documentation: `README.md`, `API_DOCUMENTATION.md`, `TESTING.md`, `docs/`, and `CHANGELOG.md`.

## Architecture boundaries

- Backend routes stay thin: validate request, require auth where appropriate, call services, and map
  known errors to `HTTPException`.
- Business logic belongs in `backend/services/`; new service access goes through lazy accessors in
  `backend/api/dependencies.py`.
- Configuration comes from `backend/core/config.py` (`settings`), not direct `os.getenv()` calls in
  runtime code.
- Agent tools return structured error payloads; they do not raise runtime exceptions into the model
  loop. Keep tool outputs compact and store large payloads as artifacts.
- Preserve the layered memory model: thread checkpointer, `ToolArtifactService`, Foundry Memory
  Store, ranked context, and selective artifact rehydration.
- Neo4j and SQL calls must be parameterized. Prefer batch operations (`UNWIND`, bulk inserts) over
  one-by-one loops.
- Frontend code uses explicit TypeScript types, App Router conventions, SWR/loading/error states, and
  accessible interactive controls.
- Infrastructure changes preserve OIDC, managed identity, Key Vault, health probes, autoscaling,
  rollback behavior, and what-if/validation before deployment.
- Documentation changes describe shipped behavior only. Cross-reference existing docs instead of
  duplicating large sections.

## Validation gates

Prove the touched surface first; broaden only when a shared contract changes or a focused check fails.

- Backend source: `cd backend && ruff check .`, targeted `pytest`, then broader pytest if shared
  services/contracts changed.
- Backend formatting: `cd backend && black --check .` when Python formatting changed.
- Frontend source: `cd frontend && npm run lint && npm run typecheck`, plus targeted Jest tests for
  changed components/hooks.
- Infrastructure/workflows: Bicep validation/what-if for Bicep, workflow syntax review, and
  `git diff --check` for all text changes.
- Documentation, agents, skills, and templates: `git diff --check`, verify links/paths/commands, and
  inspect the rendered Markdown for required reads, guardrails, proof, and output sections.
- Azure/evaluation changes: prefer dry-run commands first; cloud evaluation requires configured
  Foundry project, deployed hosted agent, and redacted environment values.

If an expected gate requires unavailable infrastructure, state the missing prerequisite and the
smallest next proof rather than substituting an unrelated check.

## GitHub and PR hygiene

- PR bodies must explain problem, why it matters, what changed, and what did not change.
- Bug fixes need root-cause evidence, the implicated file/path, and a regression test or explicit
  reason why no automated test is practical.
- Include real verification: exact command, environment, observed result, and redacted screenshot/log
  when behavior is UI, workflow, cloud, or integration-facing.
- Do not comment on, label, close, merge, or retitle issues/PRs unless explicitly asked. Report
  maintainer recommendations in chat first.
- Do not add PR-only artifacts to the repo. Attach screenshots/logs to the PR, workflow artifact, or
  an external artifact store.
- Resolve or reply to review conversations you address; leave only items that still need reviewer
  judgment.

## Changelog discipline

- Keep `CHANGELOG.md` on Keep a Changelog categories: `Added`, `Changed`, `Deprecated`, `Removed`,
  `Fixed`, and `Security`; use a breaking-change subsection only when needed.
- Entries should be user-facing or operator-facing, impact-ordered, deduplicated, and linked to
  issues/PRs when available.
- Do not add internal implementation trivia unless it changes behavior, operations, compatibility,
  security, deployment, or support expectations.
- Release notes should come from the complete matching changelog section, not a separate summary.

## Available agents

| Agent | Use when | Default proof |
| --- | --- | --- |
| `ai-engineer` | LangGraph tools, state, prompts, memory, observability, context budgets | Agent tests or focused graph/tool proof |
| `backend-architect` | FastAPI routes, services, database models, Neo4j/PostgreSQL, DI | Focused pytest plus service/route contract review |
| `frontend-developer` | Next.js pages, React components, SWR hooks, upload/chat/graph UI | Lint, typecheck, focused Jest/browser proof |
| `infra-engineer` | Bicep, Docker, Azure resources, workflows, deployment | Bicep/workflow validation or what-if |
| `test-engineer` | Pytest/Jest coverage, fixtures, CI parity, regression tests | Focused tests, then broader gates if contract changed |
| `documentation-expert` | README/API/architecture/testing/changelog sync | Docs path/command verification |
| `code-reviewer` | Read-only correctness, security, architecture, test adequacy | Severity-ranked findings with file refs |
| `security-auditor` | Auth, authorization, injection, secrets, OWASP, dependency risk | Exploit scenario and concrete remediation |
| `performance-optimizer` | Query latency, caching, token budgets, async bottlenecks, N+1 | Measured or code-backed bottleneck evidence |

## Project skills

Use skills when their trigger matches the task:

- `qprisma-architecture-check`: architecture boundary review across backend, frontend, agent, and infra.
- `qprisma-code-review`: high-signal PR/diff review.
- `qprisma-doc-sync`: documentation sync after behavior, API, workflow, or architecture changes.
- `qprisma-evaluation`: Foundry/Video-MME evaluation workflow.
- `qprisma-test-validation`: focused validation and CI parity.
- `qprisma-pr-maintainer`: issue/PR triage, PR body hygiene, review-conversation handling.
- `qprisma-release-changelog`: release prep, changelog maintenance, release note checks.
- `qprisma-security-triage`: security advisory or vulnerability triage.
- `qprisma-small-bugfix-sweep`: bounded high-confidence bugfix passes from a list of refs.
