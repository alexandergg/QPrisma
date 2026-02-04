# Create Tests

Generate tests following QPrisma testing patterns.

## Usage
```
/create-test <target> [--type unit|integration|e2e] [--coverage]
```

## Instructions

### Backend Tests (pytest)

Location: `backend/tests/test_{module}.py`

#### 1. Unit Test Template

```python
"""
Tests for {module_name}
{'=' * (len(module_name) + 10)}

Unit tests for {description}.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from {module_path} import {ClassOrFunction}


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def mock_db():
    """Mock database service."""
    db = MagicMock()
    db.get_media = AsyncMock(return_value={
        "media_id": "test-123",
        "title": "Test Video",
        "duration": 120.0,
    })
    db.save = AsyncMock(return_value=True)
    return db


@pytest.fixture
def mock_kg():
    """Mock knowledge graph service."""
    kg = MagicMock()
    kg.execute_query = AsyncMock(return_value=[])
    kg.create_node = AsyncMock(return_value={"id": "node-123"})
    return kg


@pytest.fixture
def sample_data():
    """Sample test data."""
    return {
        "media_id": "test-media-123",
        "timestamp": 45.5,
        "content": "Test content",
    }


# =============================================================================
# Test Cases
# =============================================================================

class Test{ClassName}:
    """Test suite for {ClassName}."""

    # -------------------------------------------------------------------------
    # Initialization Tests
    # -------------------------------------------------------------------------

    def test_init_default(self):
        """Test default initialization."""
        instance = {ClassName}()
        assert instance is not None

    def test_init_with_config(self):
        """Test initialization with custom config."""
        instance = {ClassName}(config={"key": "value"})
        assert instance.config["key"] == "value"

    # -------------------------------------------------------------------------
    # Success Cases
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_process_success(self, mock_db, sample_data):
        """Test successful processing."""
        with patch("{module_path}.get_database_service", return_value=mock_db):
            instance = {ClassName}()
            result = await instance.process(sample_data)

            assert result["success"] is True
            assert "data" in result
            mock_db.save.assert_called_once()

    @pytest.mark.asyncio
    async def test_process_with_options(self, mock_db, sample_data):
        """Test processing with additional options."""
        with patch("{module_path}.get_database_service", return_value=mock_db):
            instance = {ClassName}()
            result = await instance.process(sample_data, limit=5, include_metadata=True)

            assert len(result.get("items", [])) <= 5
            assert "metadata" in result

    # -------------------------------------------------------------------------
    # Error Cases
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_process_invalid_input(self):
        """Test processing with invalid input raises ValueError."""
        instance = {ClassName}()

        with pytest.raises(ValueError, match="Invalid input"):
            await instance.process(None)

    @pytest.mark.asyncio
    async def test_process_not_found(self, mock_db):
        """Test processing when resource not found."""
        mock_db.get_media = AsyncMock(return_value=None)

        with patch("{module_path}.get_database_service", return_value=mock_db):
            instance = {ClassName}()
            result = await instance.process({"media_id": "nonexistent"})

            assert result.get("error") is not None
            assert "not found" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_process_service_error(self, mock_db):
        """Test handling of service errors."""
        mock_db.save = AsyncMock(side_effect=Exception("Database error"))

        with patch("{module_path}.get_database_service", return_value=mock_db):
            instance = {ClassName}()

            with pytest.raises(RuntimeError, match="Processing failed"):
                await instance.process({"media_id": "test-123"})

    # -------------------------------------------------------------------------
    # Edge Cases
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_process_empty_results(self, mock_db, mock_kg):
        """Test processing when no results found."""
        mock_kg.execute_query = AsyncMock(return_value=[])

        with patch("{module_path}.get_database_service", return_value=mock_db):
            with patch("{module_path}.get_knowledge_graph_service", return_value=mock_kg):
                instance = {ClassName}()
                result = await instance.process({"media_id": "test-123"})

                assert result["results"] == []
                assert result["count"] == 0

    @pytest.mark.asyncio
    async def test_process_large_input(self, mock_db):
        """Test processing with large input data."""
        large_data = {"items": list(range(10000))}

        with patch("{module_path}.get_database_service", return_value=mock_db):
            instance = {ClassName}()
            result = await instance.process(large_data)

            # Should handle gracefully, possibly with pagination
            assert result is not None


# =============================================================================
# Integration Tests
# =============================================================================

@pytest.mark.integration
class Test{ClassName}Integration:
    """Integration tests requiring real services."""

    @pytest.fixture(autouse=True)
    def skip_if_no_services(self):
        """Skip if required services not available."""
        import os
        if not os.getenv("RUN_INTEGRATION_TESTS"):
            pytest.skip("Integration tests disabled")

    @pytest.mark.asyncio
    async def test_real_database_interaction(self):
        """Test with real database."""
        from services.database_service import get_database_service

        db = get_database_service()
        # Test real interaction
        pass

    @pytest.mark.asyncio
    async def test_real_knowledge_graph_query(self):
        """Test with real Neo4j."""
        from services.knowledge_graph import get_knowledge_graph_service

        kg = get_knowledge_graph_service()
        # Test real query
        pass
```

#### 2. API Route Test Template

```python
"""Tests for {route_name} routes."""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, patch

from api.main import app


@pytest.fixture
def client():
    """Create test client."""
    return TestClient(app)


@pytest.fixture
def auth_headers():
    """Create authenticated headers."""
    return {"Authorization": "Bearer test-token"}


@pytest.fixture
def mock_auth():
    """Mock authentication."""
    with patch("api.routes.{route_name}_routes.get_current_user") as mock:
        mock.return_value = {"user_id": "test-user", "email": "test@example.com"}
        yield mock


class Test{RouteName}Routes:
    """Test suite for {route_name} API endpoints."""

    def test_list_success(self, client, auth_headers, mock_auth):
        """Test listing resources."""
        response = client.get("/{prefix}/", headers=auth_headers)
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    def test_list_unauthorized(self, client):
        """Test listing without auth returns 401."""
        response = client.get("/{prefix}/")
        assert response.status_code == 401

    def test_create_success(self, client, auth_headers, mock_auth):
        """Test creating resource."""
        response = client.post(
            "/{prefix}/",
            json={"name": "test"},
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert response.json()["success"] is True

    def test_create_invalid_data(self, client, auth_headers, mock_auth):
        """Test creating with invalid data returns 422."""
        response = client.post(
            "/{prefix}/",
            json={},  # Missing required fields
            headers=auth_headers,
        )
        assert response.status_code == 422

    def test_get_not_found(self, client, auth_headers, mock_auth):
        """Test getting non-existent resource returns 404."""
        response = client.get("/{prefix}/nonexistent", headers=auth_headers)
        assert response.status_code == 404

    def test_delete_success(self, client, auth_headers, mock_auth):
        """Test deleting resource."""
        response = client.delete("/{prefix}/test-id", headers=auth_headers)
        assert response.status_code == 200
```

### Frontend Tests (Jest)

Location: `frontend/__tests__/{ComponentName}.test.tsx`

```tsx
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { rest } from 'msw';
import { setupServer } from 'msw/node';

import { {ComponentName} } from '@/components/{ComponentName}';

// =============================================================================
// Mock Server
// =============================================================================

const server = setupServer(
  rest.get('*/api/endpoint', (req, res, ctx) => {
    return res(ctx.json({ data: 'mock data' }));
  }),
  rest.post('*/api/endpoint', (req, res, ctx) => {
    return res(ctx.json({ success: true }));
  }),
);

beforeAll(() => server.listen());
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

// =============================================================================
// Test Suite
// =============================================================================

describe('{ComponentName}', () => {
  // ---------------------------------------------------------------------------
  // Rendering Tests
  // ---------------------------------------------------------------------------

  describe('rendering', () => {
    it('renders without crashing', () => {
      render(<{ComponentName} />);
      expect(screen.getByTestId('{component-name}')).toBeInTheDocument();
    });

    it('renders with custom className', () => {
      render(<{ComponentName} className="custom-class" />);
      expect(screen.getByTestId('{component-name}')).toHaveClass('custom-class');
    });

    it('renders loading state', () => {
      render(<{ComponentName} loading />);
      expect(screen.getByRole('status')).toBeInTheDocument();
    });

    it('renders error state', () => {
      render(<{ComponentName} error="Test error" />);
      expect(screen.getByText(/test error/i)).toBeInTheDocument();
    });
  });

  // ---------------------------------------------------------------------------
  // Interaction Tests
  // ---------------------------------------------------------------------------

  describe('interactions', () => {
    it('handles click events', async () => {
      const handleClick = jest.fn();
      render(<{ComponentName} onClick={handleClick} />);

      await userEvent.click(screen.getByRole('button'));

      expect(handleClick).toHaveBeenCalledTimes(1);
    });

    it('handles form submission', async () => {
      const handleSubmit = jest.fn();
      render(<{ComponentName} onSubmit={handleSubmit} />);

      await userEvent.type(screen.getByRole('textbox'), 'test input');
      await userEvent.click(screen.getByRole('button', { name: /submit/i }));

      expect(handleSubmit).toHaveBeenCalledWith(
        expect.objectContaining({ value: 'test input' })
      );
    });

    it('disables button during loading', () => {
      render(<{ComponentName} loading />);
      expect(screen.getByRole('button')).toBeDisabled();
    });
  });

  // ---------------------------------------------------------------------------
  // Data Fetching Tests
  // ---------------------------------------------------------------------------

  describe('data fetching', () => {
    it('fetches and displays data', async () => {
      render(<{ComponentName} />);

      await waitFor(() => {
        expect(screen.getByText('mock data')).toBeInTheDocument();
      });
    });

    it('handles fetch errors', async () => {
      server.use(
        rest.get('*/api/endpoint', (req, res, ctx) => {
          return res(ctx.status(500));
        }),
      );

      render(<{ComponentName} />);

      await waitFor(() => {
        expect(screen.getByText(/error/i)).toBeInTheDocument();
      });
    });
  });

  // ---------------------------------------------------------------------------
  // Accessibility Tests
  // ---------------------------------------------------------------------------

  describe('accessibility', () => {
    it('has accessible button', () => {
      render(<{ComponentName} />);
      expect(screen.getByRole('button')).toHaveAccessibleName();
    });

    it('supports keyboard navigation', async () => {
      render(<{ComponentName} />);

      await userEvent.tab();
      expect(screen.getByRole('button')).toHaveFocus();
    });
  });
});
```

## Running Tests

```bash
# Backend
cd backend
pytest tests/                          # All tests
pytest tests/test_specific.py          # Specific file
pytest tests/ -k "test_search"         # Pattern match
pytest tests/ -m "not integration"     # Skip integration
pytest tests/ --cov=services           # With coverage

# Frontend
cd frontend
npm test                               # All tests
npm test -- ComponentName              # Specific component
npm test -- --coverage                 # With coverage
npm test -- --watch                    # Watch mode
```

## Checklist
- [ ] Test file created with proper naming
- [ ] Fixtures defined for common setup
- [ ] Success cases covered
- [ ] Error cases covered
- [ ] Edge cases covered
- [ ] Mocks properly configured
- [ ] Integration tests marked with `@pytest.mark.integration`
- [ ] Async tests marked with `@pytest.mark.asyncio`
- [ ] Tests are isolated (no shared state)
