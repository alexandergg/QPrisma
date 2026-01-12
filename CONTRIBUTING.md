# Contributing to QPrisma

Thank you for your interest in contributing to QPrisma! This document provides guidelines and instructions for contributing.

## Code of Conduct

Please be respectful and considerate in all interactions. We're building a welcoming community.

## Getting Started

1. **Fork the repository** on GitHub
2. **Clone your fork** locally
3. **Set up your development environment** following the [README](./README.md)

## Development Workflow

### Branch Naming

Use descriptive branch names:
- `feature/add-video-search` - New features
- `fix/audio-transcription-error` - Bug fixes
- `docs/update-api-docs` - Documentation updates
- `refactor/optimize-embeddings` - Code refactoring

### Commit Messages

Follow conventional commits:

```
type(scope): short description

[optional body]

[optional footer]
```

Types:
- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation
- `style`: Formatting (no code change)
- `refactor`: Code restructuring
- `test`: Adding tests
- `chore`: Maintenance tasks

Examples:
```
feat(video): add scene detection support
fix(auth): resolve JWT token expiration issue
docs(readme): update installation instructions
```

## Code Standards

### Python (Backend)

- Python 3.11+
- Format with `black`
- Lint with `ruff`
- Type hints required for public functions

```bash
cd backend
black .
ruff check --fix .
```

### TypeScript (Frontend)

- TypeScript strict mode
- ESLint + Prettier
- Functional components with hooks

```bash
cd frontend
npm run lint
npm run typecheck
```

### Testing

- Write tests for new features
- Maintain or improve code coverage
- Run tests before submitting PR

```bash
# Backend
cd backend && pytest tests/

# Frontend
cd frontend && npm test
```

## Pull Request Process

1. **Update documentation** if your changes affect it
2. **Add tests** for new functionality
3. **Run linters and tests** locally
4. **Create a Pull Request** with a clear description
5. **Link related issues** using keywords (Fixes #123)

### PR Title Format

```
type(scope): description
```

Example: `feat(api): add batch processing endpoint`

### PR Description Template

```markdown
## Description
Brief description of changes

## Type of Change
- [ ] Bug fix
- [ ] New feature
- [ ] Breaking change
- [ ] Documentation update

## Testing
Describe tests performed

## Checklist
- [ ] Code follows project style
- [ ] Tests pass locally
- [ ] Documentation updated
- [ ] No new warnings
```

## Reporting Issues

### Bug Reports

Include:
- Clear title and description
- Steps to reproduce
- Expected vs actual behavior
- Environment details (OS, Python/Node version)
- Error messages or logs

### Feature Requests

Include:
- Clear use case description
- Why this would benefit the project
- Possible implementation approach

## Questions?

- Open a GitHub Discussion for general questions
- Check existing issues before creating new ones

Thank you for contributing! 🎉
