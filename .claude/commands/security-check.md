# Security Check

Perform security audit and vulnerability scanning for QPrisma.

## Usage
```
/security-check [--scope backend|frontend|deps|all] [--fix]
```

## Quick Security Scan

```bash
# Run all security checks
cd backend && bandit -r . -f json -o security-report.json
cd frontend && npm audit --json > security-report.json
```

## Backend Security

### Static Analysis with Bandit
```bash
cd backend

# Install
pip install bandit

# Full scan
bandit -r . -f json -o bandit-report.json

# Scan with severity filter
bandit -r . -ll  # Only high severity

# Exclude tests
bandit -r . --exclude tests/

# Common issues to fix:
# B101: assert used - use proper validation
# B105: hardcoded password - use env vars
# B108: hardcoded tmp directory - use tempfile
# B301: pickle usage - use json instead
# B608: SQL injection - use parameterized queries
```

### Dependency Vulnerabilities
```bash
# Using pip-audit
pip install pip-audit
pip-audit

# Using safety
pip install safety
safety check

# Fix: Update vulnerable packages
pip install --upgrade <package>
```

### Common Backend Vulnerabilities

#### SQL Injection
```python
# BAD: String formatting
query = f"SELECT * FROM users WHERE id = '{user_id}'"

# GOOD: Parameterized query
query = "SELECT * FROM users WHERE id = $1"
await db.fetch(query, user_id)
```

#### Command Injection
```python
# BAD: Shell=True with user input
subprocess.run(f"ffmpeg -i {filename}", shell=True)

# GOOD: List arguments, no shell
subprocess.run(["ffmpeg", "-i", filename], shell=False)
```

#### Path Traversal
```python
# BAD: Direct path concatenation
file_path = f"/uploads/{user_input}"

# GOOD: Validate and sanitize
from pathlib import Path

base_path = Path("/uploads").resolve()
file_path = (base_path / user_input).resolve()
if not file_path.is_relative_to(base_path):
    raise ValueError("Invalid path")
```

#### Insecure Deserialization
```python
# BAD: Pickle with untrusted data
import pickle
data = pickle.loads(user_data)

# GOOD: Use JSON
import json
data = json.loads(user_data)
```

#### Secrets in Code
```python
# BAD: Hardcoded secrets
API_KEY = "sk-1234567890abcdef"

# GOOD: Environment variables
import os
API_KEY = os.getenv("API_KEY")
if not API_KEY:
    raise ValueError("API_KEY not configured")
```

### Authentication Security

#### JWT Best Practices
```python
from datetime import datetime, timedelta
import jwt

# Strong secret (use env var)
SECRET_KEY = os.getenv("JWT_SECRET_KEY")
if len(SECRET_KEY) < 32:
    raise ValueError("JWT secret too short")

# Token creation with expiration
def create_token(user_id: str) -> str:
    return jwt.encode(
        {
            "sub": user_id,
            "iat": datetime.utcnow(),
            "exp": datetime.utcnow() + timedelta(hours=1),  # Short expiry
            "jti": str(uuid.uuid4()),  # Unique token ID
        },
        SECRET_KEY,
        algorithm="HS256",  # Or RS256 for asymmetric
    )

# Token validation
def verify_token(token: str) -> dict:
    try:
        return jwt.decode(
            token,
            SECRET_KEY,
            algorithms=["HS256"],
            options={
                "require": ["exp", "iat", "sub"],
                "verify_exp": True,
            },
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(401, "Invalid token")
```

#### Password Hashing
```python
from passlib.context import CryptContext

# Use bcrypt
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def hash_password(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)
```

## Frontend Security

### npm Audit
```bash
cd frontend

# Check vulnerabilities
npm audit

# Auto-fix where possible
npm audit fix

# Force fix (may break things)
npm audit fix --force

# Check specific severity
npm audit --audit-level=high
```

### Common Frontend Vulnerabilities

#### XSS Prevention
```typescript
// BAD: dangerouslySetInnerHTML with user content
<div dangerouslySetInnerHTML={{ __html: userInput }} />

// GOOD: Use text content or sanitize
<div>{userInput}</div>

// If HTML needed, sanitize first
import DOMPurify from 'dompurify';
<div dangerouslySetInnerHTML={{ __html: DOMPurify.sanitize(content) }} />
```

#### CSRF Protection
```typescript
// Include CSRF token in requests
const csrfToken = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content');

fetch('/api/endpoint', {
  method: 'POST',
  headers: {
    'X-CSRF-Token': csrfToken,
    'Content-Type': 'application/json',
  },
  credentials: 'include',  // Include cookies
  body: JSON.stringify(data),
});
```

#### Secure Storage
```typescript
// BAD: Store sensitive data in localStorage
localStorage.setItem('token', accessToken);

// GOOD: Use httpOnly cookies (set by server)
// Or memory-only storage
let accessToken: string | null = null;

function setToken(token: string) {
  accessToken = token;
}

function getToken(): string | null {
  return accessToken;
}
```

### Content Security Policy
```typescript
// next.config.js
const securityHeaders = [
  {
    key: 'Content-Security-Policy',
    value: `
      default-src 'self';
      script-src 'self' 'unsafe-eval' 'unsafe-inline';
      style-src 'self' 'unsafe-inline';
      img-src 'self' blob: data: https:;
      font-src 'self';
      connect-src 'self' ${process.env.NEXT_PUBLIC_API_URL};
      frame-ancestors 'none';
    `.replace(/\n/g, ''),
  },
  {
    key: 'X-Frame-Options',
    value: 'DENY',
  },
  {
    key: 'X-Content-Type-Options',
    value: 'nosniff',
  },
  {
    key: 'Referrer-Policy',
    value: 'strict-origin-when-cross-origin',
  },
];
```

## Infrastructure Security

### Environment Variables
```bash
# Check for exposed secrets
grep -rn "password\|secret\|api.key\|token" --include="*.py" --include="*.ts" .

# Ensure .env is in .gitignore
cat .gitignore | grep ".env"

# Check for committed secrets
git log -p --all -S "password" --source --all
```

### Docker Security
```dockerfile
# Use non-root user
FROM python:3.11-slim

# Create non-root user
RUN useradd -m -u 1000 appuser
USER appuser

# Don't run as root
# USER root  # BAD

# Scan for vulnerabilities
# docker scan qprisma-api:latest
```

### Network Security
```yaml
# docker-compose.yml - limit exposed ports
services:
  api:
    ports:
      - "8000:8000"  # Only expose what's needed

  postgres:
    # Don't expose in production
    # ports:
    #   - "5432:5432"
    expose:
      - "5432"  # Internal only

  redis:
    expose:
      - "6379"  # Internal only
```

## Security Checklist

### Code Security
- [ ] No hardcoded secrets
- [ ] Input validation on all endpoints
- [ ] Parameterized database queries
- [ ] Output encoding/escaping
- [ ] Authentication on sensitive endpoints
- [ ] Authorization checks (role-based)
- [ ] Rate limiting implemented
- [ ] Logging without sensitive data

### Dependency Security
- [ ] `npm audit` shows no high/critical issues
- [ ] `pip-audit` shows no vulnerabilities
- [ ] Dependencies regularly updated
- [ ] Lock files committed

### Infrastructure Security
- [ ] HTTPS enforced
- [ ] Security headers configured
- [ ] CORS properly restricted
- [ ] Secrets in environment variables
- [ ] Non-root container users
- [ ] Network segmentation

### Authentication & Session
- [ ] Strong password hashing (bcrypt)
- [ ] JWT with short expiration
- [ ] Secure cookie flags
- [ ] Session invalidation on logout
- [ ] Account lockout after failed attempts

## Automated Security Scanning

### GitHub Actions
```yaml
name: Security Scan

on:
  push:
    branches: [main, develop]
  schedule:
    - cron: '0 0 * * 0'  # Weekly

jobs:
  security:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Python security scan
        run: |
          pip install bandit safety
          bandit -r backend/ -f json -o bandit.json
          safety check --json > safety.json

      - name: Node security scan
        run: |
          cd frontend
          npm audit --json > npm-audit.json

      - name: Upload results
        uses: github/codeql-action/upload-sarif@v2
        with:
          sarif_file: bandit.json
```

## Incident Response

### If Secrets Are Exposed
```bash
# 1. Rotate immediately
# - Regenerate API keys
# - Change passwords
# - Revoke tokens

# 2. Remove from git history
git filter-branch --force --index-filter \
  "git rm --cached --ignore-unmatch path/to/secret" \
  --prune-empty --tag-name-filter cat -- --all

# 3. Force push (coordinate with team)
git push origin --force --all

# 4. Notify affected parties
# 5. Audit access logs
# 6. Document incident
```

## Checklist
- [ ] Static analysis run (bandit, eslint-plugin-security)
- [ ] Dependency audit passed
- [ ] No secrets in code
- [ ] Authentication secure
- [ ] Input validation complete
- [ ] HTTPS configured
- [ ] Security headers set
- [ ] Rate limiting enabled
