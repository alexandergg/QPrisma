---
name: qprisma-release-changelog
description: Maintain QPrisma changelog, release notes, version-bump workflow expectations, and release-readiness documentation.
---

# QPrisma Release and Changelog Skill

Use this skill when preparing release notes, updating `CHANGELOG.md`, reviewing release workflow
changes, or checking version-bump behavior.

## Required reads

1. `AGENTS.md`
2. `CHANGELOG.md`
3. `.github/workflows/release.yml`
4. `.github/workflows/version-bump.yml`
5. Relevant changed files since the previous release or tagged version

## Guardrails

- Do not change version numbers, tags, releases, or publish state without explicit operator approval.
- Do not rewrite historical changelog sections except to fix clear factual errors.
- Do not include internal-only implementation notes unless they affect users, operators, security,
  compatibility, deployment, or support.
- Redact private endpoints, tenant IDs, user IDs, tokens, and raw service payloads.

## Changelog rules

- Keep the Keep a Changelog structure.
- Use `## [Unreleased]` for pending work and version sections for releases.
- Prefer categories: `Added`, `Changed`, `Deprecated`, `Removed`, `Fixed`, `Security`.
- Use a breaking-change subsection only when the change requires user/operator action.
- Entries should be user-facing or operator-facing, impact-ordered, deduplicated, and linked to
  issues/PRs when available.
- Do not include internal implementation trivia unless it changes behavior, security, deployment,
  compatibility, evaluation, or support expectations.
- Release notes must use the complete matching changelog section.

## Release hygiene

1. Verify version locations that are touched by the release workflow before proposing a release.
2. Check that release workflow extraction still matches `CHANGELOG.md` headings.
3. Confirm generated release notes do not include secrets, raw Foundry payloads, private endpoints,
   or tenant/user identifiers.
4. For breaking changes, list migration steps and rollback considerations.
5. For evaluation or hosted-agent releases, note required deployed agent version and Foundry project
   prerequisites.

## Output format

```markdown
### Changelog status
- Complete / needs update:
- Missing user-facing entries:
- Duplicates or internal-only entries:

### Release readiness
- Version/release workflow impact:
- Required validation:
- Migration or operator notes:
```
