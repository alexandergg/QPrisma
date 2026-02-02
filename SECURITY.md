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

## Acknowledgments

We appreciate responsible disclosure and will acknowledge security researchers who help improve QPrisma.
