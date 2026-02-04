# Optimize Performance

Identify and fix performance bottlenecks in QPrisma.

## Usage
```
/optimize-performance [--target backend|frontend|database|all] [--profile]
```

## Performance Profiling

### Backend Profiling

#### Python cProfile
```python
import cProfile
import pstats
from io import StringIO

def profile_function(func):
    """Decorator to profile a function."""
    def wrapper(*args, **kwargs):
        profiler = cProfile.Profile()
        profiler.enable()
        result = func(*args, **kwargs)
        profiler.disable()

        # Print stats
        stream = StringIO()
        stats = pstats.Stats(profiler, stream=stream)
        stats.sort_stats('cumulative')
        stats.print_stats(20)
        print(stream.getvalue())

        return result
    return wrapper

# Usage
@profile_function
async def process_video(media_id: str):
    ...
```

#### Line-by-line Profiling
```bash
pip install line_profiler

# Add @profile decorator to function
kernprof -l -v backend/services/video_processor.py
```

#### Memory Profiling
```bash
pip install memory_profiler

# Profile memory
python -m memory_profiler backend/services/video_processor.py

# Or with decorator
from memory_profiler import profile

@profile
async def process_video(media_id: str):
    ...
```

### API Endpoint Timing
```python
import time
from functools import wraps
from fastapi import Request

# Middleware for timing
@app.middleware("http")
async def timing_middleware(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    duration = time.perf_counter() - start

    response.headers["X-Response-Time"] = f"{duration:.3f}s"

    if duration > 1.0:  # Log slow requests
        logger.warning(f"Slow request: {request.url.path} took {duration:.3f}s")

    return response
```

## Common Bottlenecks

### 1. N+1 Query Problem

**Bad:**
```python
async def get_videos_with_frames(video_ids: list[str]):
    videos = []
    for video_id in video_ids:
        video = await db.get_video(video_id)  # N queries
        frames = await db.get_frames(video_id)  # N more queries
        videos.append({"video": video, "frames": frames})
    return videos
```

**Good:**
```python
async def get_videos_with_frames(video_ids: list[str]):
    # Single query with JOIN
    query = """
    SELECT v.*, array_agg(f.*) as frames
    FROM videos v
    LEFT JOIN frames f ON f.video_id = v.id
    WHERE v.id = ANY($1)
    GROUP BY v.id
    """
    return await db.fetch_all(query, video_ids)
```

### 2. Missing Async I/O

**Bad:**
```python
import requests  # Blocking!

async def call_external_api():
    response = requests.get("https://api.example.com")  # Blocks event loop
    return response.json()
```

**Good:**
```python
import httpx

async def call_external_api():
    async with httpx.AsyncClient() as client:
        response = await client.get("https://api.example.com")
        return response.json()
```

### 3. Large Response Without Pagination

**Bad:**
```python
@router.get("/frames/{media_id}")
async def get_all_frames(media_id: str):
    return await db.get_frames(media_id)  # Could be 1000s of frames
```

**Good:**
```python
@router.get("/frames/{media_id}")
async def get_frames(
    media_id: str,
    limit: int = Query(50, le=100),
    offset: int = Query(0, ge=0),
):
    frames = await db.get_frames(media_id, limit=limit, offset=offset)
    total = await db.count_frames(media_id)
    return {
        "frames": frames,
        "total": total,
        "limit": limit,
        "offset": offset,
    }
```

### 4. Missing Caching

**Add Redis caching:**
```python
from functools import wraps
import json
import redis

redis_client = redis.from_url(os.getenv("REDIS_URL"))

def cache(ttl: int = 300):
    """Cache decorator with TTL in seconds."""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Create cache key from function name and args
            key = f"{func.__name__}:{hash((args, frozenset(kwargs.items())))}"

            # Check cache
            cached = redis_client.get(key)
            if cached:
                return json.loads(cached)

            # Execute and cache
            result = await func(*args, **kwargs)
            redis_client.setex(key, ttl, json.dumps(result))
            return result
        return wrapper
    return decorator

# Usage
@cache(ttl=600)  # Cache for 10 minutes
async def get_video_summary(media_id: str) -> dict:
    ...
```

### 5. Inefficient Embedding Generation

**Bad:**
```python
# One at a time
embeddings = []
for text in texts:
    embedding = await openai.embed(text)  # Slow
    embeddings.append(embedding)
```

**Good:**
```python
# Batch processing
BATCH_SIZE = 100

async def embed_batch(texts: list[str]) -> list[list[float]]:
    embeddings = []
    for i in range(0, len(texts), BATCH_SIZE):
        batch = texts[i:i + BATCH_SIZE]
        batch_embeddings = await openai.embed_batch(batch)
        embeddings.extend(batch_embeddings)
    return embeddings
```

## Database Optimization

### PostgreSQL

#### Add Indexes
```sql
-- For frequent queries
CREATE INDEX idx_frames_media_id ON frames(media_id);
CREATE INDEX idx_frames_timestamp ON frames(media_id, timestamp);
CREATE INDEX idx_processing_jobs_status ON processing_jobs(status);

-- For text search
CREATE INDEX idx_frames_description_gin ON frames USING gin(to_tsvector('english', description));
```

#### Analyze Slow Queries
```sql
-- Enable query logging
ALTER SYSTEM SET log_min_duration_statement = 100;  -- Log queries > 100ms

-- Analyze query plan
EXPLAIN ANALYZE
SELECT * FROM frames
WHERE media_id = 'abc123'
ORDER BY timestamp;
```

### Neo4j

#### Create Vector Index
```cypher
// Vector index for semantic search
CALL db.index.vector.createNodeIndex(
  'frame_embeddings',
  'Frame',
  'embedding',
  1536,
  'cosine'
);

// Verify index
SHOW INDEXES WHERE name = 'frame_embeddings';
```

#### Optimize Cypher Queries
```cypher
// Bad: No index usage
MATCH (f:Frame)
WHERE f.description CONTAINS 'person'
RETURN f;

// Good: Use full-text index
CALL db.index.fulltext.createNodeIndex('frame_descriptions', ['Frame'], ['description']);

CALL db.index.fulltext.queryNodes('frame_descriptions', 'person')
YIELD node
RETURN node;
```

## Frontend Optimization

### React Performance

#### Use React.memo
```typescript
// Memoize expensive components
const FrameGrid = React.memo(({ frames }: { frames: Frame[] }) => {
  return (
    <div className="grid grid-cols-4 gap-4">
      {frames.map(frame => (
        <FrameCard key={frame.id} frame={frame} />
      ))}
    </div>
  );
});
```

#### Use useMemo/useCallback
```typescript
function VideoPlayer({ frames, onSelect }: Props) {
  // Memoize expensive calculations
  const sortedFrames = useMemo(
    () => frames.sort((a, b) => a.timestamp - b.timestamp),
    [frames]
  );

  // Memoize callbacks passed to children
  const handleSelect = useCallback(
    (id: string) => onSelect(id),
    [onSelect]
  );

  return <FrameGrid frames={sortedFrames} onSelect={handleSelect} />;
}
```

#### Virtualize Long Lists
```typescript
import { useVirtualizer } from '@tanstack/react-virtual';

function VirtualizedFrameList({ frames }: { frames: Frame[] }) {
  const parentRef = useRef<HTMLDivElement>(null);

  const virtualizer = useVirtualizer({
    count: frames.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => 200,
  });

  return (
    <div ref={parentRef} className="h-[600px] overflow-auto">
      <div style={{ height: virtualizer.getTotalSize() }}>
        {virtualizer.getVirtualItems().map(virtualRow => (
          <div
            key={virtualRow.key}
            style={{
              position: 'absolute',
              top: virtualRow.start,
              height: virtualRow.size,
            }}
          >
            <FrameCard frame={frames[virtualRow.index]} />
          </div>
        ))}
      </div>
    </div>
  );
}
```

### SWR Optimization
```typescript
// Configure caching and revalidation
const { data } = useSWR(
  `/api/media/${mediaId}/frames`,
  fetcher,
  {
    revalidateOnFocus: false,
    revalidateOnReconnect: false,
    dedupingInterval: 60000,  // Dedupe requests within 1 min
  }
);
```

## Load Testing

### Locust Script
```python
# locustfile.py
from locust import HttpUser, task, between

class QPrismaUser(HttpUser):
    wait_time = between(1, 3)

    def on_start(self):
        # Login and get token
        response = self.client.post("/auth/login", json={
            "username": "test",
            "password": "test"
        })
        self.token = response.json()["access_token"]
        self.headers = {"Authorization": f"Bearer {self.token}"}

    @task(3)
    def search_video(self):
        self.client.post(
            "/graph/search",
            headers=self.headers,
            json={"query": "person speaking", "media_id": "test-123"}
        )

    @task(1)
    def get_frames(self):
        self.client.get(
            "/media/test-123/frames?limit=50",
            headers=self.headers
        )
```

### Run Load Test
```bash
# Install
pip install locust

# Run
locust -f locustfile.py --host=http://localhost:8000

# Or headless
locust -f locustfile.py --host=http://localhost:8000 \
  --users 100 --spawn-rate 10 --run-time 5m --headless
```

## Monitoring

### Add Prometheus Metrics
```python
from prometheus_client import Counter, Histogram, generate_latest
from fastapi import Response

# Metrics
REQUEST_COUNT = Counter(
    'http_requests_total',
    'Total HTTP requests',
    ['method', 'endpoint', 'status']
)

REQUEST_LATENCY = Histogram(
    'http_request_duration_seconds',
    'HTTP request latency',
    ['method', 'endpoint']
)

@app.middleware("http")
async def metrics_middleware(request: Request, call_next):
    start = time.time()
    response = await call_next(request)
    duration = time.time() - start

    REQUEST_COUNT.labels(
        method=request.method,
        endpoint=request.url.path,
        status=response.status_code
    ).inc()

    REQUEST_LATENCY.labels(
        method=request.method,
        endpoint=request.url.path
    ).observe(duration)

    return response

@app.get("/metrics")
async def metrics():
    return Response(generate_latest(), media_type="text/plain")
```

## Checklist
- [ ] Profiled slow endpoints (>500ms)
- [ ] Identified N+1 queries
- [ ] Added missing database indexes
- [ ] Implemented caching where appropriate
- [ ] Batch processing for bulk operations
- [ ] Frontend components memoized
- [ ] Long lists virtualized
- [ ] Load tested critical paths
- [ ] Monitoring metrics in place
