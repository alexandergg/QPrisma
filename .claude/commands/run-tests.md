# Run Tests

Execute tests for QPrisma backend and frontend with various options.

## Usage
```
/run-tests [--type unit|integration|e2e|all] [--coverage] [--watch] [--file <path>]
```

## Backend Tests (pytest)

### Run All Tests
```bash
cd backend
pytest tests/ -v
```

### Run by Type
```bash
# Unit tests only
pytest tests/ -v -m "not integration and not e2e"

# Integration tests (require services)
pytest tests/ -v -m integration

# E2E tests
pytest tests/ -v -m e2e
```

### Run Specific File or Pattern
```bash
# Single file
pytest tests/test_media_routes.py -v

# Pattern match
pytest tests/ -k "test_search" -v

# Specific test function
pytest tests/test_media_routes.py::test_upload_video -v
```

### With Coverage
```bash
pytest tests/ --cov=. --cov-report=html --cov-report=term-missing

# Coverage for specific module
pytest tests/ --cov=services --cov-report=term-missing
```

### Async Tests
```bash
# Tests use pytest-asyncio automatically
pytest tests/ -v --asyncio-mode=auto
```

### Watch Mode
```bash
ptw tests/ -- -v  # Requires pytest-watch
```

## Frontend Tests (Jest)

### Run All Tests
```bash
cd frontend
npm test
```

### Run Specific File
```bash
npm test -- components/VideoPlayer.test.tsx
```

### With Coverage
```bash
npm test -- --coverage
```

### Watch Mode
```bash
npm test -- --watch
```

### Update Snapshots
```bash
npm test -- -u
```

## E2E Tests (Playwright)

### Run E2E Tests
```bash
cd frontend
npx playwright test
```

### Headed Mode (see browser)
```bash
npx playwright test --headed
```

### Debug Mode
```bash
npx playwright test --debug
```

### Specific Browser
```bash
npx playwright test --project=chromium
```

## Test Patterns

### Backend Unit Test
```python
"""Tests for media service."""

import pytest
from unittest.mock import AsyncMock, patch

from services.media_service import MediaService


class TestMediaService:
    """Test cases for MediaService."""

    @pytest.fixture
    def mock_storage(self):
        """Create mock storage service."""
        storage = AsyncMock()
        storage.get_media.return_value = {"id": "test", "title": "Test"}
        return storage

    @pytest.fixture
    def service(self, mock_storage):
        """Create service with mocked dependencies."""
        return MediaService(storage=mock_storage)

    @pytest.mark.asyncio
    async def test_get_media_success(self, service, mock_storage):
        """Test successful media retrieval."""
        result = await service.get_media("test-id")

        assert result["id"] == "test"
        mock_storage.get_media.assert_called_once_with("test-id")

    @pytest.mark.asyncio
    async def test_get_media_not_found(self, service, mock_storage):
        """Test media not found raises exception."""
        mock_storage.get_media.return_value = None

        with pytest.raises(MediaNotFoundError):
            await service.get_media("nonexistent")
```

### Backend Integration Test
```python
"""Integration tests for media routes."""

import pytest
from httpx import AsyncClient

from api.main import app


@pytest.mark.integration
class TestMediaRoutesIntegration:
    """Integration tests requiring real services."""

    @pytest.fixture
    async def client(self):
        """Create test client."""
        async with AsyncClient(app=app, base_url="http://test") as client:
            yield client

    @pytest.mark.asyncio
    async def test_upload_and_process(self, client, test_video):
        """Test full upload and processing flow."""
        # Upload
        response = await client.post(
            "/upload",
            files={"file": test_video},
        )
        assert response.status_code == 200
        media_id = response.json()["media_id"]

        # Process
        response = await client.post(f"/processing/ffmpeg/{media_id}")
        assert response.status_code == 202
```

### Frontend Component Test
```typescript
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { VideoPlayer } from './VideoPlayer';

describe('VideoPlayer', () => {
  it('renders video with controls', () => {
    render(<VideoPlayer src="/test.mp4" />);

    expect(screen.getByRole('video')).toBeInTheDocument();
    expect(screen.getByLabelText('Play')).toBeInTheDocument();
  });

  it('plays video on button click', async () => {
    const user = userEvent.setup();
    render(<VideoPlayer src="/test.mp4" />);

    await user.click(screen.getByLabelText('Play'));

    await waitFor(() => {
      expect(screen.getByLabelText('Pause')).toBeInTheDocument();
    });
  });
});
```

## Test Configuration

### pytest.ini
```ini
[pytest]
asyncio_mode = auto
markers =
    integration: marks tests as integration (require services)
    e2e: marks tests as end-to-end
    slow: marks tests as slow
testpaths = tests
python_files = test_*.py
python_functions = test_*
addopts = -v --tb=short
```

### conftest.py Fixtures
```python
import pytest
from unittest.mock import AsyncMock


@pytest.fixture
def mock_azure_openai():
    """Mock Azure OpenAI client."""
    client = AsyncMock()
    client.chat.completions.create.return_value = AsyncMock(
        choices=[AsyncMock(message=AsyncMock(content="Test response"))]
    )
    return client


@pytest.fixture
def test_video(tmp_path):
    """Create test video file."""
    video_path = tmp_path / "test.mp4"
    video_path.write_bytes(b"fake video content")
    return video_path


@pytest.fixture
async def db_session():
    """Create database session for tests."""
    # Setup test database
    yield session
    # Cleanup
```

## CI/CD Test Commands

```yaml
# GitHub Actions example
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - name: Backend Tests
        run: |
          cd backend
          pytest tests/ -v --cov=. --cov-report=xml

      - name: Frontend Tests
        run: |
          cd frontend
          npm test -- --coverage --watchAll=false

      - name: E2E Tests
        run: |
          cd frontend
          npx playwright test
```

## Checklist
- [ ] Unit tests passing
- [ ] Integration tests passing (if applicable)
- [ ] E2E tests passing (if applicable)
- [ ] Coverage threshold met (typically 80%+)
- [ ] No skipped tests without reason
- [ ] New code has corresponding tests
