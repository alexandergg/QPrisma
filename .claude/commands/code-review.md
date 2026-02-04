# Code Review

Perform a comprehensive code review using QPrisma patterns and best practices.

## Usage
```
/code-review <file_or_directory> [--focus security|performance|patterns|all]
```

## Review Process

When reviewing code, follow this systematic approach:

### 1. Architecture & Layering Check

Verify proper layer separation:

| Layer | Should Do | Should NOT Do |
|-------|-----------|---------------|
| Routes | HTTP handling, validation | Business logic, DB access |
| Services | Business logic, orchestration | HTTP concerns, rendering |
| Models | Data structures, validation | Business logic, I/O |
| Agent Tools | LLM orchestration, return dicts | Raise exceptions, direct DB writes |

### 2. QPrisma Pattern Compliance

**Routes must use:**
```python
@router.post("/{media_id}/process")
async def process_media(
    media_id: str,
    config: ProcessingConfig,                                    # Pydantic validation
    current_user: Annotated[User, Depends(get_current_user)],   # Auth
    service: Annotated[MediaService, Depends(get_media_service)], # DI
) -> ProcessingResponse:                                         # Typed response
    result = await service.process(media_id, config)
    return ProcessingResponse.from_result(result)
```

**Services must follow:**
```python
class MediaService:
    def __init__(
        self,
        storage: StorageService,      # Dependency injection
        processor: ProcessorService,  # Not constructed inside
    ):
        self._storage = storage
        self._processor = processor

    async def process(self, media_id: str) -> ProcessingResult:
        # Async for I/O operations
        # Proper error handling with logging
        pass
```

**Agent tools must:**
```python
@tool
async def search_video(
    media_id: Annotated[str, "Video ID to search"],
    query: Annotated[str, "Natural language query"],
) -> dict:  # Always return dict
    """Clear docstring explaining when to use."""
    try:
        results = await graph_service.search(media_id, query)
        return {"results": results[:MAX_RESULTS], "count": len(results)}
    except Exception as e:
        return {"error": str(e), "results": []}  # Never raise
```

### 3. Security Checklist (OWASP)

```bash
# Check for common vulnerabilities
grep -rn "f\"SELECT.*{" backend/          # SQL injection
grep -rn "eval\|exec" backend/            # Code injection
grep -rn "os.system\|subprocess" backend/ # Command injection
grep -rn "password.*=.*\"" backend/       # Hardcoded credentials
grep -rn "verify=False" backend/          # SSL bypass
```

### 4. Error Handling Check

**Good:**
```python
try:
    result = await process()
except ProcessingError as e:
    logger.error(f"Processing failed for {media_id}: {e}")
    raise HTTPException(status_code=500, detail=str(e))
```

**Bad:**
```python
try:
    result = await process()
except Exception:  # Too broad
    pass  # Silent failure
```

### 5. Performance Patterns

Check for:
- N+1 queries (loop with DB call inside)
- Missing async/await for I/O
- Blocking calls in async functions
- Missing caching for expensive operations

### 6. Testing Coverage

Verify tests exist for:
- [ ] Happy path
- [ ] Error cases
- [ ] Edge cases
- [ ] Input validation

## Review Output Format

```markdown
## Code Review: {file_path}

**Overall Assessment**: [Approve | Request Changes | Needs Discussion]
**Risk Level**: [Low | Medium | High]

### Critical Issues (Must Fix)

1. **SQL Injection Risk** - `{file}:{line}`
   ```python
   # Bad
   query = f"SELECT * FROM media WHERE id = '{media_id}'"
   ```
   **Fix:**
   ```python
   query = "SELECT * FROM media WHERE id = $1"
   await db.fetch(query, media_id)
   ```

### High Priority (Should Fix)

2. **Missing Error Handling** - `{file}:{line}`
   ...

### Medium Priority (Consider)

3. **Code Duplication** - `{file}:{line}`
   ...

### Suggestions (Optional)

4. **Type Hints Missing**
   ...

### Positive Observations

- Good use of dependency injection
- Comprehensive error messages
- Well-structured async code
```

## Quick Review Commands

```bash
# Run static analysis
cd backend && ruff check . --select=E,W,F,I,S

# Type checking
pyright backend/

# Security scan
bandit -r backend/ -f json

# Test coverage
pytest --cov=backend --cov-report=html
```

## Checklist
- [ ] Architecture layers respected
- [ ] QPrisma patterns followed
- [ ] Security vulnerabilities checked
- [ ] Error handling appropriate
- [ ] Performance patterns reviewed
- [ ] Tests coverage adequate
- [ ] Type hints present
- [ ] Documentation updated if needed
