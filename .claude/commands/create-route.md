---
description: Create a new FastAPI route module following QPrisma patterns
---

# Create FastAPI Route

Create a new FastAPI route module following QPrisma patterns.

## Usage
```
/create-route <route_name> [--prefix /api/v1/<prefix>] [--tags <tag>]
```

## Instructions

When creating a new route for QPrisma, follow these patterns:

### 1. Create the route file at `backend/api/routes/{name}_routes.py`

```python
"""
{Name} Routes
{'=' * (len(name) + 7)}

API endpoints for {description}.
"""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from api.main import get_database_service
from services.auth_service import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/{prefix}", tags=["{tag}"])


# =============================================================================
# Request/Response Models
# =============================================================================

class {Name}Request(BaseModel):
    """Request model for {name} operations."""
    pass


class {Name}Response(BaseModel):
    """Response model for {name} operations."""
    success: bool
    message: str


# =============================================================================
# Endpoints
# =============================================================================

@router.get("/")
async def list_{name}s(
    current_user: Annotated[dict, Depends(get_current_user)],
    db=Depends(get_database_service),
) -> list[{Name}Response]:
    """List all {name}s for the current user."""
    try:
        # Implementation
        return []
    except Exception as e:
        logger.error(f"Error listing {name}s: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.post("/")
async def create_{name}(
    request: {Name}Request,
    current_user: Annotated[dict, Depends(get_current_user)],
    db=Depends(get_database_service),
) -> {Name}Response:
    """Create a new {name}."""
    try:
        # Implementation
        return {Name}Response(success=True, message="{Name} created")
    except Exception as e:
        logger.error(f"Error creating {name}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.get("/{{id}}")
async def get_{name}(
    id: str,
    current_user: Annotated[dict, Depends(get_current_user)],
    db=Depends(get_database_service),
) -> {Name}Response:
    """Get a specific {name} by ID."""
    try:
        # Implementation
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="{Name} not found",
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting {name}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.delete("/{{id}}")
async def delete_{name}(
    id: str,
    current_user: Annotated[dict, Depends(get_current_user)],
    db=Depends(get_database_service),
) -> {Name}Response:
    """Delete a {name}."""
    try:
        # Implementation
        return {Name}Response(success=True, message="{Name} deleted")
    except Exception as e:
        logger.error(f"Error deleting {name}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )
```

### 2. Register the router in `backend/api/routes/__init__.py`

Add import and export:
```python
from api.routes.{name}_routes import router as {name}_router
```

### 3. Include the router in `backend/api/main.py`

```python
from api.routes import {name}_router

app.include_router({name}_router)
```

### 4. Create tests at `backend/tests/test_{name}_routes.py`

```python
"""Tests for {name} routes."""

import pytest
from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)


class Test{Name}Routes:
    """Test cases for {name} endpoints."""

    def test_list_{name}s(self, auth_headers):
        """Test listing {name}s."""
        response = client.get("/{prefix}/", headers=auth_headers)
        assert response.status_code == 200

    def test_create_{name}(self, auth_headers):
        """Test creating a {name}."""
        response = client.post(
            "/{prefix}/",
            json={{}},
            headers=auth_headers,
        )
        assert response.status_code == 200
```

## Checklist
- [ ] Route file created with proper structure
- [ ] Request/Response Pydantic models defined
- [ ] Authentication dependency added
- [ ] Error handling with proper HTTP status codes
- [ ] Logging added for debugging
- [ ] Router registered in `__init__.py`
- [ ] Router included in `main.py`
- [ ] Tests created
