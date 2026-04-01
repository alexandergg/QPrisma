# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 1.x.x   | :white_check_mark: |
| < 1.0   | :x:                |

## Reporting a Vulnerability

We take security issues seriously. If you discover a security vulnerability, please follow responsible disclosure:

### How to Report

1. **Do NOT** create a public GitHub issue for security vulnerabilities
2. Email security concerns to the repository maintainers
3. Include detailed information about the vulnerability
4. Allow up to 48 hours for an initial response

### What to Include

- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix (if any)

### Response Timeline

- **Initial Response**: Within 48 hours
- **Status Update**: Within 7 days
- **Resolution Target**: Within 30 days for critical issues

## Security Best Practices

When deploying QPrisma:

1. **Environment Variables**: Never commit secrets to the repository
2. **API Keys**: Rotate Azure OpenAI keys regularly
3. **Database**: Use strong passwords for PostgreSQL and Neo4j
4. **Network**: Deploy behind a reverse proxy with TLS
5. **Updates**: Keep dependencies updated

## Code Scanning Alert Triage

QPrisma uses [CodeQL](https://codeql.github.com/) for static analysis of both Python and JavaScript/TypeScript code. Alerts appear in **Security → Code scanning** on GitHub.

### Severity Prioritization

| Priority | Severity | Action |
|----------|----------|--------|
| P0 | **Critical / High** — Injection (SQL, command, path traversal) | Fix immediately |
| P1 | **High** — XSS, SSRF, insecure deserialization | Fix within current sprint |
| P2 | **Medium** — Hardcoded secrets, weak cryptography | Fix within next release |
| P3 | **Low** — Information exposure, missing auth checks | Schedule for backlog |
| P4 | **Note** — Code quality, style, complexity | Fix opportunistically |

### Triage Workflow

1. **Filter by severity** — In the Security tab, use `is:open sort:severity-desc` to surface critical issues first.
2. **Group by rule** — Click a rule ID to see all alerts for that pattern. Fixing the root pattern often closes many alerts at once.
3. **Dismiss false positives** — Select alerts → **Dismiss** with an appropriate reason:
   - *False positive* — scanner misidentified the pattern
   - *Won't fix* — accepted risk or not applicable
   - *Used in tests* — test-only code (should be excluded by config going forward)
4. **Fix by category** — Create one PR per category for cohesive, reviewable changes.

### Bulk Operations with GitHub CLI

```bash
# List all open alerts with their rule, severity, and file
gh api "/repos/{owner}/{repo}/code-scanning/alerts?state=open&per_page=100" \
  --jq '.[] | [.number, .rule.id, .rule.security_severity_level // .rule.severity, .most_recent_instance.location.path] | @tsv'

# Count alerts grouped by rule
gh api "/repos/{owner}/{repo}/code-scanning/alerts?state=open&per_page=100" --paginate \
  --jq '[.[].rule.id] | group_by(.) | map({rule: .[0], count: length}) | sort_by(-.count)[]'

# Dismiss a specific alert as false positive
gh api "/repos/{owner}/{repo}/code-scanning/alerts/{alert_number}" \
  -X PATCH -f state=dismissed -f dismissed_reason=false-positive

# Dismiss a specific alert as won't fix
gh api "/repos/{owner}/{repo}/code-scanning/alerts/{alert_number}" \
  -X PATCH -f state=dismissed -f dismissed_reason="won't fix"
```

> **Tip:** Replace `{owner}/{repo}` with `alexandergg/QPrisma` and `{alert_number}` with the alert number from the list command.

### Preventing New Alerts

- CodeQL runs on every push and PR to `main` — new vulnerabilities are caught before merge.
- Dependabot opens weekly PRs for dependency updates (pip, npm, Actions, Docker).
- Consider enabling **Copilot Autofix** in repo settings (Settings → Code security → Code scanning) for automated fix suggestions.
- Add a branch protection rule requiring the "Analyze" status check to pass before merging.

## Acknowledgments

We appreciate responsible disclosure and will acknowledge security researchers who help improve QPrisma.
