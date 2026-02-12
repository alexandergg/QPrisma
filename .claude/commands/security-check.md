---
description: Run security audit and vulnerability scanning on QPrisma code
---

# Security Check

Scan QPrisma code for security vulnerabilities, dependency issues, and common anti-patterns.

## Usage
```
/security-check [--scope backend|frontend|deps|all] [--fix]
```

## Instructions

When running a security check, execute these scans and report findings:

### 1. Static Analysis
```bash
# Backend — scan with bandit (exclude tests)
cd backend && bandit -r . --exclude tests/ -ll

# Backend — check with ruff security rules
ruff check . --select=S

# Frontend — npm audit
cd frontend && npm audit --audit-level=high
```

### 2. Dependency Vulnerabilities
```bash
# Backend
cd backend && pip-audit

# Frontend
cd frontend && npm audit
```

### 3. Code Pattern Scan

Search the codebase for these anti-patterns:

| Pattern | Risk | What to find |
|---------|------|-------------|
| `f"SELECT.*{` | SQL injection | String-formatted queries |
| `eval\|exec` | Code injection | Dynamic code execution |
| `os.system\|subprocess.*shell=True` | Command injection | Shell execution with user input |
| `password.*=.*"` or `api.key.*=.*"` | Hardcoded secrets | Credentials in source |
| `verify=False` | SSL bypass | Disabled certificate verification |
| `pickle.loads` | Insecure deserialization | Pickle with untrusted data |
| `dangerouslySetInnerHTML` | XSS | Unescaped HTML rendering |
| `localStorage.setItem.*token` | Token exposure | Tokens in localStorage |

### 4. QPrisma-Specific Checks

- [ ] All routes use `Depends(get_current_user)` for authentication
- [ ] Agent tools never raise exceptions (return error dicts)
- [ ] Config uses `core.config.settings`, not `os.getenv()` directly
- [ ] No secrets in `.env.example` files
- [ ] FFmpeg commands use list args, not `shell=True`
- [ ] Neo4j queries use `$params`, not f-strings

### 5. Report Format

```markdown
## Security Scan Results

**Risk Level**: [Low | Medium | High | Critical]

### Critical (Must Fix)
1. [Finding] — file:line — [Fix]

### High (Should Fix)
1. [Finding] — file:line — [Fix]

### Medium (Consider)
1. [Finding] — file:line — [Fix]

### Dependencies
- Backend: X vulnerabilities (Y critical)
- Frontend: X vulnerabilities (Y critical)
```

## Checklist
- [ ] Static analysis run (bandit, ruff --select=S)
- [ ] Dependency audit passed (pip-audit, npm audit)
- [ ] No hardcoded secrets in code
- [ ] All endpoints require authentication
- [ ] Parameterized queries (SQL + Cypher)
- [ ] No shell=True with user input
