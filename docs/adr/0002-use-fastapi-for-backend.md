# 2. Use FastAPI for Backend

Date: 2024-02-04

## Status

Accepted

## Context

We need a backend framework for QPrisma that supports:
- High-performance asynchronous I/O (for handling video uploads and AI service calls).
- Strong typing for reliable data validation.
- Automatic documentation generation.
- Easy integration with Python's AI/ML ecosystem.

## Decision

We will use **FastAPI**.

## Consequences

### Positive
- **Performance**: Built on Starlette and Pydantic, offering Node.js/Go-like performance.
- **Async Native**: `async/await` support is first-class, essential for our I/O-bound AI workflows.
- **Type Safety**: Pydantic models ensure data integrity between frontend and backend.
- **Documentation**: Automatic Swagger/OpenAPI generation reduces documentation burden.

### Negative
- Smaller ecosystem than Django (e.g., no built-in admin panel or ORM).
- Requires choosing and integrating separate components for database (SQLAlchemy/SQLModel) and tasks (Celery).
