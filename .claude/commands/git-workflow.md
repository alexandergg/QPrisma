# Git Workflow

Standard git workflows and branch management for QPrisma.

## Usage
```
/git-workflow <action> [--branch <name>] [--type feature|bugfix|hotfix]
```

## Branch Strategy

### Branch Naming
```
feature/JIRA-123-add-video-upload
bugfix/JIRA-456-fix-search-timeout
hotfix/JIRA-789-critical-auth-fix
release/v1.2.0
```

### Branch Hierarchy
```
main (production)
  └── develop (staging)
        └── feature/xxx
        └── bugfix/xxx
```

## Common Workflows

### Start New Feature
```bash
# Update main
git checkout main
git pull origin main

# Create feature branch
git checkout -b feature/JIRA-123-add-chunked-upload

# Work on feature...
git add .
git commit -m "feat: add chunked upload endpoint

- Add /upload/chunk endpoint
- Implement Azure Block Blob staging
- Add progress tracking via Redis

Closes JIRA-123"

# Push and create PR
git push -u origin feature/JIRA-123-add-chunked-upload
gh pr create --title "feat: add chunked upload support" --body "..."
```

### Fix a Bug
```bash
# From develop or main
git checkout develop
git pull origin develop

# Create bugfix branch
git checkout -b bugfix/JIRA-456-fix-search-timeout

# Fix and commit
git add .
git commit -m "fix: increase search timeout to 30s

The vector search was timing out for large videos
due to the default 5s timeout.

Fixes JIRA-456"

# Push and PR
git push -u origin bugfix/JIRA-456-fix-search-timeout
gh pr create
```

### Hotfix for Production
```bash
# Branch from main
git checkout main
git pull origin main
git checkout -b hotfix/JIRA-789-auth-bypass

# Fix critical issue
git add .
git commit -m "fix(security): patch authentication bypass

CRITICAL: Fixes vulnerability allowing unauthenticated
access to protected endpoints.

Fixes JIRA-789"

# Push immediately
git push -u origin hotfix/JIRA-789-auth-bypass

# Create PR with urgent label
gh pr create --title "HOTFIX: auth bypass vulnerability" \
  --label "urgent,security"
```

## Commit Message Format

### Conventional Commits
```
<type>(<scope>): <description>

[optional body]

[optional footer]
```

### Types
| Type | Description | Example |
|------|-------------|---------|
| `feat` | New feature | `feat: add video search endpoint` |
| `fix` | Bug fix | `fix: correct frame timestamp calculation` |
| `docs` | Documentation | `docs: update API reference` |
| `style` | Formatting | `style: fix indentation in routes` |
| `refactor` | Code restructure | `refactor: extract video processing to service` |
| `perf` | Performance | `perf: add caching to search endpoint` |
| `test` | Tests | `test: add unit tests for upload service` |
| `chore` | Maintenance | `chore: update dependencies` |

### Examples
```bash
# Feature with scope
git commit -m "feat(agent): add transcript search tool

Adds new tool for searching spoken content in video transcripts.
Uses full-text search via Neo4j.

- Add search_transcript tool
- Update tool definitions
- Add tests

Closes JIRA-100"

# Bug fix
git commit -m "fix(api): handle missing media gracefully

Returns 404 instead of 500 when media_id not found.

Fixes JIRA-101"

# Breaking change
git commit -m "feat(api)!: change upload response format

BREAKING CHANGE: Upload response now includes 'media_id'
instead of 'id' for consistency with other endpoints.

Migration: Update client code to use response.media_id"
```

## Pull Request Workflow

### Create PR
```bash
# Using GitHub CLI
gh pr create \
  --title "feat: add video summarization" \
  --body "$(cat <<'EOF'
## Summary
Adds automatic video summarization using GPT-4o.

## Changes
- Add `/media/{id}/summarize` endpoint
- Implement chunked summarization for long videos
- Add caching for generated summaries

## Testing
- [x] Unit tests pass
- [x] Integration tests pass
- [x] Manual testing done

## Screenshots
![Summary UI](url)

Closes JIRA-150
EOF
)"
```

### Review PR
```bash
# List PRs
gh pr list

# View PR details
gh pr view 123

# Checkout PR locally
gh pr checkout 123

# Add review comment
gh pr review 123 --comment -b "Looks good, minor suggestion on line 45"

# Approve
gh pr review 123 --approve

# Request changes
gh pr review 123 --request-changes -b "Please add error handling"
```

### Merge PR
```bash
# Squash and merge (preferred for features)
gh pr merge 123 --squash --delete-branch

# Merge commit (for releases)
gh pr merge 123 --merge

# Rebase (clean history)
gh pr merge 123 --rebase
```

## Resolving Conflicts

### Merge Conflicts
```bash
# Update your branch
git checkout feature/my-feature
git fetch origin
git merge origin/main

# If conflicts:
# 1. Open conflicted files
# 2. Resolve conflicts (look for <<<<<<< markers)
# 3. Stage resolved files
git add <resolved-files>

# 4. Complete merge
git commit -m "merge: resolve conflicts with main"

# 5. Push
git push
```

### Rebase Conflicts
```bash
# Rebase onto main
git checkout feature/my-feature
git fetch origin
git rebase origin/main

# If conflicts at each commit:
# 1. Resolve conflicts
git add <resolved-files>

# 2. Continue rebase
git rebase --continue

# 3. Or abort if needed
git rebase --abort

# 4. Force push (rebase rewrites history)
git push --force-with-lease
```

## Useful Commands

### View History
```bash
# Pretty log
git log --oneline --graph --decorate -20

# Changes in a file
git log -p -- path/to/file

# Who changed what
git blame path/to/file
```

### Undo Changes
```bash
# Undo last commit (keep changes)
git reset --soft HEAD~1

# Undo last commit (discard changes)
git reset --hard HEAD~1

# Undo specific file
git checkout -- path/to/file

# Revert a merged commit
git revert -m 1 <merge-commit-hash>
```

### Stash Work
```bash
# Save work in progress
git stash push -m "WIP: video upload"

# List stashes
git stash list

# Apply and keep stash
git stash apply stash@{0}

# Apply and remove stash
git stash pop

# Drop stash
git stash drop stash@{0}
```

### Clean Up
```bash
# Remove untracked files (dry run)
git clean -n

# Remove untracked files
git clean -f

# Remove untracked directories too
git clean -fd

# Prune remote branches
git fetch --prune
```

## Branch Protection Rules

### Recommended Settings (main branch)
- ✅ Require pull request reviews (1 approver)
- ✅ Require status checks to pass
- ✅ Require branches to be up to date
- ✅ Require signed commits
- ❌ Allow force pushes
- ❌ Allow deletions

### Status Checks Required
- `test` - Backend tests pass
- `lint` - Linting passes
- `build` - Frontend builds
- `security` - Security scan passes

## Checklist
- [ ] Branch created from latest main/develop
- [ ] Commits follow conventional format
- [ ] Tests pass locally
- [ ] PR description complete
- [ ] Reviewers assigned
- [ ] CI checks pass
- [ ] Conflicts resolved
- [ ] Approved and merged
