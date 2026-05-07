---
name: qprisma-small-bugfix-sweep
description: Fix only small, high-certainty QPrisma bugs from a pasted issue/PR list after code-path proof.
---

# QPrisma Small Bugfix Sweep Skill

Use this skill when the user provides multiple QPrisma issue or PR refs and asks for a bounded bugfix
pass.

## Required reads

1. `AGENTS.md`
2. `.github/skills/qprisma-pr-maintainer/SKILL.md`
3. `.github/skills/qprisma-test-validation/SKILL.md`
4. Live issue/PR state for each pasted ref
5. Current code, adjacent tests, and dependency contracts for each candidate

## Guardrails

- Fix only bugs with clear current-code root cause and a narrow owner path.
- Do not include support, product decisions, broad refactors, release process work, or speculative
  dependency behavior.
- Do not commit, push, create PRs, comment, label, close, or merge unless explicitly asked after the
  local diff is reviewed.
- Skip items where reproduction, root cause, owner boundary, or reliable proof is unclear.

## Loop

For each ref:

1. Read live issue/PR state with `gh`.
2. Read body, comments, linked refs, changed files, current code, adjacent tests, and dependency
   contracts when relevant.
3. Trace the runtime path and identify the owner module.
4. Classify:
   - `fixed-local`: narrow fix applied with proof
   - `ready-to-merge`: existing PR is sound and proof is adequate
   - `needs-fixup`: clear fix needed but should be applied to an existing PR/branch
   - `skipped`: broad, stale, speculative, support/config/product/security/release, or no proof
   - `needs-human`: owner/product/security decision needed
5. Add focused regression proof when practical.
6. Run the smallest meaningful gate.

## Fix rules

- Owner module first; shared seams only when multiple surfaces need the same contract.
- Reuse existing helpers, services, hooks, fixtures, and test patterns.
- No drive-by refactors.
- Tests stay near the failing surface.
- Docs/changelog only when public behavior or workflow changes.

## Output format

```markdown
### Ledger
- fixed-local:
- ready-to-merge:
- needs-fixup:
- skipped:
- needs-human:

### Files left dirty
- ...

### Proof
- Commands:
- Results:
```
