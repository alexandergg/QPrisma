---
name: qprisma-pr-maintainer
description: Triage QPrisma issues and PRs, verify PR body evidence, review conversation cleanup, labels, duplicate checks, and maintainer-ready recommendations.
---

# QPrisma PR Maintainer Skill

Use this skill for maintainer-facing GitHub workflow. Do not use it for ordinary code edits unless the
task is explicitly issue/PR triage or PR hygiene.

## Required reads

1. `AGENTS.md`
2. `.github/PULL_REQUEST_TEMPLATE.md`
3. `.github/ISSUE_TEMPLATE/`
4. Relevant changed files and scoped `.github/instructions/*.instructions.md`
5. Live issue/PR state via `gh issue view` or `gh pr view` when a GitHub ref is involved

## Guardrails

- Do not comment, label, close, merge, retitle, or request changes unless the user explicitly asks.
- Do not rely on PR text alone for a bug fix. Verify symptom, root cause, implicated path, and proof.
- Do not surface secrets, private endpoints, tenant IDs, user IDs, or raw logs in recommendations.
- Do not recommend broad refactors as PR hygiene unless they are required for correctness.
- Treat bot/reviewer conversations as work items: address them, then resolve only if the fix is present.

## Triage process

1. Gather the issue/PR title, body, author, labels, linked refs, changed files, and current CI status.
2. Search for duplicates or already-fixed behavior in open/closed issues and recent PRs.
3. Classify the work: bug, feature, docs, infra, security, evaluation, support, or low-signal.
4. For bug fixes, verify:
   - observable symptom or failing test/log
   - root cause in current code with file/path
   - fix touches the implicated path
   - regression proof exists or the gap is justified
5. Check the PR body against the QPrisma template: summary, scope boundary, root cause,
   regression plan, verification evidence, security/compatibility, and checklist.
6. Produce a maintainer recommendation in chat before taking any GitHub action.

## Proof gates

- Live issue/PR state checked before any recommendation.
- Duplicate or already-fixed claims backed by a concrete issue, PR, commit, or release reference.
- Bugfix readiness backed by symptom, root cause, changed path, and regression proof.

## Output format

```markdown
### Verdict
- keep / request changes / ready / close as duplicate / needs maintainer decision

### Evidence
- Issue/PR:
- Author/context:
- Symptom and root cause:
- Changed files:
- Verification:

### Required follow-up
- ...

### Maintainer-ready comment
<only include when the user asked for a comment>
```
