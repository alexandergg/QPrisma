# Testing Best Practices - QPrisma

## Overview

This document outlines testing standards and best practices for QPrisma. All code contributions should include appropriate tests.

## Test Structure

```
backend/
└── tests/
    ├── conftest.py          # Pytest fixtures and configuration
    ├── test_api.py          # API endpoint tests
    ├── test_config.py       # Settings, validators, production guards
    ├── test_community_detection.py          # Community detection pipeline
    ├── test_community_search_integration.py # Community search integration
    ├── test_temporal_chains.py              # Dense temporal chains
    └── test_data/           # Test fixtures and sample data

frontend/
└── __tests__/
    ├── components/          # Component tests
    ├── hooks/               # Custom hooks tests
    └── integration/         # Integration tests
```

### Notable Test Modules

| Test file | Coverage area |
|---|---|
| `test_security_headers.py` | Security headers middleware |
| `test_token_revocation.py` | JWT revocation via Redis JTI denylist |
| `test_websocket_auth.py` | WebSocket JWT authentication |
| `test_a2a_rate_limits.py` | A2A endpoint rate limiting |
| `test_error_sanitization.py` | Error message sanitization |
| `test_cache_routes.py` | Cache endpoint auth and operations |
| `test_pyav_extractor.py` | PyAV frame extraction |
| `test_scene_detect_service.py` | PySceneDetect integration |
| `test_faster_whisper_service.py` | faster-whisper transcription backend |
| `test_video_decoder.py` | Unified VideoDecoder protocol |
| `test_streaming_pipeline.py` | Streaming pipeline architecture |
| `test_audio_parallel_transcription.py` | Parallel audio transcription |
| `test_video_perf_optimizations.py` | Frame dedup, WebP encoding, batch sizing |
| `test_community_detection.py` | Louvain community detection pipeline |
| `test_community_search_integration.py` | Community nodes in hybrid search |
| `test_temporal_chains.py` | NEXT_FRAME / NEXT_SEGMENT / NEXT_SCENE chains and adjacency scoring |
| `test_config.py` | Settings classes, production validators, dev autologin guard, client factories |
| `test_errors.py` | Standardized HTTP error helpers |
| `test_retry.py` | Centralized retry with exponential backoff |
| `test_concurrency.py` | TaskGroup-based structured concurrency |
| `test_processing_metrics.py` | Pipeline observability and stage timing |

## Backend Testing (Python)

### Testing Framework

- **pytest**: Main testing framework
- **pytest-asyncio**: For async tests
- **pytest-mock**: For mocking
- **httpx**: For API testing

### Running Tests

```bash
cd backend

# Run all tests
pytest

# Run specific test file
pytest tests/test_api.py

# Run tests matching pattern
pytest -k "test_upload"

# Run with coverage
pytest --cov=. --cov-report=html

# Run with verbose output
pytest -v
```

### Writing Unit Tests

#### 1. Service Tests

```python
# tests/test_services/test_video_processor.py
import pytest
from services.video_processor import VideoProcessor

@pytest.fixture
def video_processor():
    """Fixture providing a VideoProcessor instance"""
    return VideoProcessor()

def test_extract_frames_returns_list(video_processor):
    """Test that extract_frames returns a list of frames"""
    frames = video_processor.extract_frames("test_video.mp4")
    assert isinstance(frames, list)
    assert len(frames) > 0

def test_extract_frames_with_invalid_path(video_processor):
    """Test that extract_frames handles invalid paths"""
    with pytest.raises(FileNotFoundError):
        video_processor.extract_frames("nonexistent.mp4")

@pytest.mark.asyncio
async def test_async_processing(video_processor):
    """Test async frame processing"""
    result = await video_processor.process_async("test_video.mp4")
    assert result["status"] == "completed"
```

#### 2. API Endpoint Tests

```python
# tests/test_api.py
from fastapi.testclient import TestClient
from api.main import app

client = TestClient(app)

def test_upload_video_success():
    """Test successful video upload"""
    with open("tests/test_data/sample.mp4", "rb") as f:
        response = client.post(
            "/media/upload",
            files={"file": ("sample.mp4", f, "video/mp4")}
        )
    assert response.status_code == 200
    assert "video_id" in response.json()

def test_upload_invalid_file_type():
    """Test upload with invalid file type"""
    with open("tests/test_data/sample.txt", "rb") as f:
        response = client.post(
            "/media/upload",
            files={"file": ("sample.txt", f, "text/plain")}
        )
    assert response.status_code == 422

def test_get_video_not_found():
    """Test retrieving non-existent video"""
    response = client.get("/media/nonexistent-id")
    assert response.status_code == 404
```

#### 3. Mocking External Services

```python
# tests/test_azure_integration.py
import pytest
from unittest.mock import Mock, patch

@patch('services.video_processor.AzureOpenAI')
def test_vision_analysis_with_mock(mock_azure):
    """Test vision analysis with mocked Azure client"""
    # Setup mock
    mock_client = Mock()
    mock_client.chat.completions.create.return_value.choices = [
        Mock(message=Mock(content="Mock analysis result"))
    ]
    mock_azure.return_value = mock_client
    
    # Test
    from services.video_processor import VideoProcessor
    processor = VideoProcessor()
    result = processor.analyze_frame("test_frame.jpg")
    
    assert "Mock analysis result" in result
    mock_client.chat.completions.create.assert_called_once()
```

### Test Coverage Goals

The CI enforces a **70% minimum overall coverage** (`fail_under = 70` in `pyproject.toml`).
Per-area targets:

- **Services**: 80%+ coverage
- **API Routes**: 90%+ coverage
- **Models**: 100% coverage (simple dataclasses)
- **Utils**: 85%+ coverage

### Fixtures and Test Data

```python
# tests/conftest.py
import pytest
from pathlib import Path

@pytest.fixture
def test_video_path():
    """Path to test video file"""
    return Path(__file__).parent / "test_data" / "sample.mp4"

@pytest.fixture
def mock_azure_config():
    """Mock Azure configuration"""
    return {
        "endpoint": "https://test.openai.azure.com",
        "api_key": "test_key",
        "deployment": "test_deployment"
    }

@pytest.fixture(scope="session")
def test_database():
    """Setup test database"""
    # Create test database
    db = setup_test_db()
    yield db
    # Teardown
    cleanup_test_db(db)
```

## Frontend Testing (TypeScript/React)

### Testing Framework

- **Jest**: Test runner
- **React Testing Library**: Component testing
- **MSW (Mock Service Worker)**: API mocking

### Setup

```bash
cd frontend

# Install testing dependencies
npm install --save-dev @testing-library/react @testing-library/jest-dom
npm install --save-dev @testing-library/user-event
npm install --save-dev msw

# Run tests
npm test

# Run with coverage
npm test -- --coverage

# Run in watch mode
npm test -- --watch
```

### Writing Component Tests

#### 1. Simple Component Tests

```typescript
// __tests__/components/VideoCard.test.tsx
import { render, screen } from '@testing-library/react';
import { VideoCard } from '@/components/VideoCard';

describe('VideoCard', () => {
  const mockVideo = {
    id: 'test-id',
    title: 'Test Video',
    duration: 120,
    status: 'completed'
  };

  it('renders video title', () => {
    render(<VideoCard video={mockVideo} />);
    expect(screen.getByText('Test Video')).toBeInTheDocument();
  });

  it('displays formatted duration', () => {
    render(<VideoCard video={mockVideo} />);
    expect(screen.getByText('02:00')).toBeInTheDocument();
  });

  it('shows completed status badge', () => {
    render(<VideoCard video={mockVideo} />);
    const badge = screen.getByTestId('status-badge');
    expect(badge).toHaveTextContent('completed');
  });
});
```

#### 2. User Interaction Tests

```typescript
// __tests__/components/VideoUpload.test.tsx
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { VideoUpload } from '@/components/VideoUpload';

describe('VideoUpload', () => {
  it('handles file selection', async () => {
    const user = userEvent.setup();
    render(<VideoUpload />);
    
    const file = new File(['video'], 'test.mp4', { type: 'video/mp4' });
    const input = screen.getByLabelText('Upload Video');
    
    await user.upload(input, file);
    
    expect(screen.getByText('test.mp4')).toBeInTheDocument();
  });

  it('shows upload progress', async () => {
    render(<VideoUpload />);
    
    const file = new File(['video'], 'test.mp4', { type: 'video/mp4' });
    const input = screen.getByLabelText('Upload Video');
    
    await userEvent.upload(input, file);
    
    await waitFor(() => {
      expect(screen.getByRole('progressbar')).toBeInTheDocument();
    });
  });

  it('displays error for invalid file type', async () => {
    render(<VideoUpload />);
    
    const file = new File(['text'], 'test.txt', { type: 'text/plain' });
    const input = screen.getByLabelText('Upload Video');
    
    await userEvent.upload(input, file);
    
    expect(screen.getByText(/invalid file type/i)).toBeInTheDocument();
  });
});
```

#### 3. Mocking API Calls

```typescript
// __tests__/api/videoApi.test.tsx
import { rest } from 'msw';
import { setupServer } from 'msw/node';
import { render, screen, waitFor } from '@testing-library/react';
import { VideoList } from '@/components/VideoList';

// Setup mock server
const server = setupServer(
  rest.get('/api/media', (req, res, ctx) => {
    return res(ctx.json({
      items: [
        { id: '1', title: 'Video 1', status: 'completed' },
        { id: '2', title: 'Video 2', status: 'processing' }
      ]
    }));
  })
);

beforeAll(() => server.listen());
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

describe('VideoList', () => {
  it('fetches and displays videos', async () => {
    render(<VideoList />);
    
    await waitFor(() => {
      expect(screen.getByText('Video 1')).toBeInTheDocument();
      expect(screen.getByText('Video 2')).toBeInTheDocument();
    });
  });

  it('handles API errors', async () => {
    server.use(
      rest.get('/api/media', (req, res, ctx) => {
        return res(ctx.status(500));
      })
    );
    
    render(<VideoList />);
    
    await waitFor(() => {
      expect(screen.getByText(/error loading videos/i)).toBeInTheDocument();
    });
  });
});
```

### Custom Hooks Testing

```typescript
// __tests__/hooks/useVideoUpload.test.tsx
import { renderHook, act } from '@testing-library/react';
import { useVideoUpload } from '@/hooks/useVideoUpload';

describe('useVideoUpload', () => {
  it('initializes with correct default state', () => {
    const { result } = renderHook(() => useVideoUpload());
    
    expect(result.current.progress).toBe(0);
    expect(result.current.isUploading).toBe(false);
  });

  it('updates progress during upload', async () => {
    const { result } = renderHook(() => useVideoUpload());
    
    const file = new File(['video'], 'test.mp4', { type: 'video/mp4' });
    
    act(() => {
      result.current.upload(file);
    });
    
    expect(result.current.isUploading).toBe(true);
    
    await waitFor(() => {
      expect(result.current.progress).toBeGreaterThan(0);
    });
  });
});
```

## Integration Testing

### Backend Integration Tests

```python
# tests/test_integration/test_full_pipeline.py
import pytest
from services.video_processor import VideoProcessor
from services.knowledge_graph import KnowledgeGraph

@pytest.mark.integration
def test_complete_video_processing_pipeline():
    """Test full video processing from upload to knowledge graph"""
    # Step 1: Upload video
    video_id = upload_video("test_video.mp4")
    
    # Step 2: Process with FFmpeg
    processor = VideoProcessor()
    frames = processor.extract_frames(video_id)
    assert len(frames) > 0
    
    # Step 3: Analyze frames
    analyses = []
    for frame in frames:
        analysis = processor.analyze_frame(frame)
        analyses.append(analysis)
    
    # Step 4: Build knowledge graph
    kg = KnowledgeGraph()
    kg.add_video(video_id, frames, analyses)
    
    # Step 5: Verify graph
    results = kg.search("show all scenes")
    assert len(results) > 0
```

### Frontend Integration Tests

```typescript
// __tests__/integration/uploadAndProcess.test.tsx
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { App } from '@/App';

describe('Upload and Process Flow', () => {
  it('completes full upload and processing workflow', async () => {
    const user = userEvent.setup();
    render(<App />);
    
    // Upload video
    const file = new File(['video'], 'test.mp4', { type: 'video/mp4' });
    const input = screen.getByLabelText('Upload Video');
    await user.upload(input, file);
    
    // Wait for upload to complete
    await waitFor(() => {
      expect(screen.getByText('Upload Complete')).toBeInTheDocument();
    }, { timeout: 5000 });
    
    // Start processing
    const processButton = screen.getByText('Process Video');
    await user.click(processButton);
    
    // Wait for processing
    await waitFor(() => {
      expect(screen.getByText('Processing Complete')).toBeInTheDocument();
    }, { timeout: 10000 });
    
    // Verify results displayed
    expect(screen.getByText(/frames extracted/i)).toBeInTheDocument();
  });
});
```

## Test Naming Conventions

### Backend (Python)

```python
# Format: test_<function_name>_<condition>_<expected_result>

def test_upload_video_with_valid_file_returns_video_id():
    """Test that uploading a valid video returns a video ID"""
    pass

def test_process_video_with_missing_file_raises_error():
    """Test that processing a missing video raises FileNotFoundError"""
    pass

def test_extract_frames_with_zero_fps_returns_empty_list():
    """Test that zero FPS configuration returns empty frame list"""
    pass
```

### Frontend (TypeScript)

```typescript
// Format: 'should <expected behavior> when <condition>'

describe('VideoUpload', () => {
  it('should display file name when file is selected', () => {});
  
  it('should show error message when invalid file type is uploaded', () => {});
  
  it('should update progress bar during upload', () => {});
});
```

## Test Data Management

### Creating Test Videos

```python
# tests/create_test_video.py — uses FFmpeg (no OpenCV dependency)
import os
import subprocess

def create_test_video(output_path: str = "test_video.mp4", duration: int = 5, fps: int = 30):
    """Create a test video with colour patterns and text overlay via FFmpeg."""
    width, height = 1280, 720
    ffmpeg_cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi",
        "-i", f"testsrc2=size={width}x{height}:rate={fps}:duration={duration}",
        "-c:v", "libx264", "-preset", "medium", "-crf", "23",
        "-pix_fmt", "yuv420p",
        output_path,
    ]
    subprocess.run(ffmpeg_cmd, capture_output=True, text=True, check=True)
    return output_path
```

## Continuous Integration

### GitHub Actions Workflow

```yaml
# .github/workflows/tests.yml
name: Tests

on: [push, pull_request]

jobs:
  backend-tests:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      - name: Install dependencies
        run: |
          cd backend
          pip install uv
          uv pip install -e .
      - name: Run tests
        run: |
          cd backend
          pytest --cov=. --cov-report=xml
      - name: Upload coverage
        uses: codecov/codecov-action@v3
        with:
          file: ./backend/coverage.xml

  frontend-tests:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Setup Node
        uses: actions/setup-node@v3
        with:
          node-version: '20'
      - name: Install dependencies
        run: |
          cd frontend
          npm ci
      - name: Run tests
        run: |
          cd frontend
          npm test -- --coverage
      - name: Upload coverage
        uses: codecov/codecov-action@v3
        with:
          file: ./frontend/coverage/lcov.info
```

## Best Practices Summary

### DO:
✅ Write tests for all new features  
✅ Test both success and failure cases  
✅ Use descriptive test names  
✅ Mock external dependencies  
✅ Keep tests fast and isolated  
✅ Aim for 70%+ code coverage (CI threshold)  
✅ Test edge cases and error handling  
✅ Use fixtures for reusable test data  

### DON'T:
❌ Test implementation details  
❌ Write flaky tests  
❌ Depend on test execution order  
❌ Use production data in tests  
❌ Skip error case testing  
❌ Leave tests commented out  
❌ Write overly complex test logic  

## Resources

- [pytest Documentation](https://docs.pytest.org/)
- [React Testing Library Docs](https://testing-library.com/react)
- [FastAPI Testing Guide](https://fastapi.tiangolo.com/tutorial/testing/)
- [Jest Documentation](https://jestjs.io/)
