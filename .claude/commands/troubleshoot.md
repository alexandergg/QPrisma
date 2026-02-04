# Troubleshoot

Diagnose and fix common issues in QPrisma development.

## Usage
```
/troubleshoot <issue_type> [--verbose]
```

## Quick Diagnostics

### Health Check All Services
```bash
# Check all services at once
curl http://localhost:8000/health && \
docker-compose ps && \
redis-cli ping && \
cypher-shell -u neo4j -p qprisma123 "RETURN 1"
```

## Common Issues

### 1. Service Connection Errors

#### "Could not connect to Redis"
```bash
# Check Redis is running
docker ps | grep redis

# Check it's Redis Stack (not standard Redis)
docker logs qprisma-redis-1 | grep "RediSearch"

# Verify URL format
echo $REDIS_URL  # Should be: redis://localhost:6379/0

# Test connection
redis-cli ping
redis-cli MODULE LIST  # Should show RediSearch, ReJSON

# Fix: Use Redis Stack image
# docker-compose.yml should have:
# image: redis/redis-stack:latest
```

#### "Neo4j connection refused"
```bash
# Check Neo4j is running
docker ps | grep neo4j

# Wait for startup (can take 30s+)
docker logs qprisma-neo4j-1 | grep "Started"

# Test connection
cypher-shell -u neo4j -p qprisma123 "RETURN 1"

# Check bolt port is exposed
curl -I http://localhost:7474  # Browser
nc -zv localhost 7687          # Bolt

# Fix: Wait for startup or restart
docker-compose restart neo4j
```

#### "PostgreSQL connection failed"
```bash
# Check PostgreSQL is running
docker ps | grep postgres

# Test connection
psql -h localhost -U qprisma -d qprisma -c "SELECT 1"

# Check DATABASE_URL format
echo $DATABASE_URL
# Should be: postgresql://qprisma:qprisma123@localhost:5432/qprisma

# Fix: Verify credentials match docker-compose.yml
```

### 2. Azure OpenAI Errors

#### "Azure OpenAI deployment not found"
```bash
# Check environment variables
echo $AZURE_OPENAI_ENDPOINT
echo $AZURE_OPENAI_DEPLOYMENT_GPT

# Verify deployment exists in Azure Portal
# Portal > Azure OpenAI > Deployments

# Test API directly
curl "$AZURE_OPENAI_ENDPOINT/openai/deployments/$AZURE_OPENAI_DEPLOYMENT_GPT/chat/completions?api-version=2024-08-01-preview" \
  -H "api-key: $AZURE_OPENAI_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "Hello"}]}'

# Common fixes:
# 1. Check deployment name matches exactly (case-sensitive)
# 2. Verify API version is supported
# 3. Check resource region has the model
```

#### "Rate limit exceeded"
```python
# Add retry logic with exponential backoff
from tenacity import retry, wait_exponential, stop_after_attempt

@retry(
    wait=wait_exponential(multiplier=1, min=2, max=60),
    stop=stop_after_attempt(5),
)
async def call_openai(prompt: str):
    return await client.chat.completions.create(...)

# Or use batch API for high volume
# Set use_batch_api=True in processing config
```

#### "Context length exceeded"
```python
# Check token count before calling
from agent.video_agent import estimate_messages_tokens

tokens = estimate_messages_tokens(messages)
if tokens > 100000:
    # Truncate older messages
    messages = truncate_context(messages, max_tokens=80000)
```

### 3. Video Processing Errors

#### "FFmpeg not found"
```bash
# Check FFmpeg installation
ffmpeg -version

# Install if missing
# Windows: winget install Gyan.FFmpeg
# macOS: brew install ffmpeg
# Linux: sudo apt install ffmpeg

# Verify it's in PATH
which ffmpeg  # Should show path
```

#### "Processing stuck at X%"
```bash
# Check Celery worker logs
docker-compose logs -f celery-worker

# Check if worker is running
docker-compose ps celery-worker

# Restart worker
docker-compose restart celery-worker

# Check for task errors
celery -A tasks.celery_app inspect active
celery -A tasks.celery_app inspect reserved
```

#### "Frame extraction failed"
```bash
# Test FFmpeg directly
ffmpeg -i input.mp4 -vf fps=1 -frames:v 10 frame_%04d.jpg

# Check video format is supported
ffprobe input.mp4

# Common issues:
# 1. Video file corrupted - re-upload
# 2. Unsupported codec - convert first
# 3. Disk space - check storage
```

### 4. Agent Issues

#### "Agent not using tools"
```python
# Verify tools are bound
from agent.video_agent_graph import create_video_agent_graph

graph = create_video_agent_graph()
print(graph.get_graph().draw_ascii())  # Should show tool nodes

# Check media_id is passed (tools require it)
# Check video is processed (status: completed)

# Verify tool definitions
from agent.tools import SEARCH_TOOLS
print([t.name for t in SEARCH_TOOLS])
```

#### "Infinite tool loop"
```python
# Check MAX_TOOL_ITERATIONS setting
# Default is 5, increase if complex queries need more

# Check tool is returning useful results
from agent.tools import search_video
result = await search_video(media_id="test", query="test")
print(result)  # Should have results, not error

# Add iteration warning to prompt (already in agent)
```

#### "Session not persisting"
```python
# Check Redis checkpointer
from agent.video_agent_graph import get_video_agent_graph

agent = get_video_agent_graph()
print(type(agent.checkpointer))  # Should be AsyncRedisSaver

# Verify thread_id is consistent
# Same thread_id = same session
```

### 5. Frontend Issues

#### "API calls failing with CORS"
```python
# Check CORS middleware in FastAPI
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],  # Frontend URL
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

#### "SWR not updating"
```typescript
// Force revalidation
const { data, mutate } = useSWR('/api/media/list');
await mutate();  // Refresh data

// Check dedupingInterval
useSWR('/api/media/list', fetcher, {
  dedupingInterval: 0,  // Disable deduplication
});
```

#### "Build failing"
```bash
# Check TypeScript errors
npm run typecheck

# Check ESLint errors
npm run lint

# Clear cache and rebuild
rm -rf .next node_modules
npm install
npm run build
```

### 6. Docker Issues

#### "Container keeps restarting"
```bash
# Check logs
docker-compose logs -f <service_name>

# Check memory limits
docker stats

# Increase memory in docker-compose.yml
services:
  neo4j:
    deploy:
      resources:
        limits:
          memory: 4G
```

#### "Port already in use"
```bash
# Find process using port
lsof -i :8000  # macOS/Linux
netstat -ano | findstr :8000  # Windows

# Kill process
kill -9 <PID>

# Or change port in docker-compose.yml
```

#### "Volume permission denied"
```bash
# Fix permissions
sudo chown -R $USER:$USER ./data

# Or use named volumes instead of bind mounts
volumes:
  neo4j_data:
```

## Diagnostic Commands

### Backend
```bash
# Check API health
curl http://localhost:8000/health

# List routes
curl http://localhost:8000/openapi.json | jq '.paths | keys'

# Test authentication
curl -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "test", "password": "test"}'
```

### Database
```bash
# PostgreSQL
psql -h localhost -U qprisma -d qprisma -c "\dt"  # List tables
psql -h localhost -U qprisma -d qprisma -c "SELECT count(*) FROM media"

# Neo4j
cypher-shell -u neo4j -p qprisma123 "MATCH (n) RETURN labels(n), count(*)"
cypher-shell -u neo4j -p qprisma123 "SHOW INDEXES"

# Redis
redis-cli KEYS "*"
redis-cli INFO memory
```

### Logs
```bash
# All services
docker-compose logs -f

# Specific service
docker-compose logs -f api
docker-compose logs -f celery-worker

# Backend logs (if running outside Docker)
tail -f backend/logs/api.log
```

## Reset Everything

```bash
# Nuclear option - reset all data
docker-compose down -v
docker volume prune -f
docker-compose up -d

# Re-run migrations
cd backend
alembic upgrade head
python -m migrations.neo4j.runner upgrade
```

## Checklist
- [ ] Identified the error message
- [ ] Checked service is running
- [ ] Verified configuration/environment variables
- [ ] Checked logs for details
- [ ] Tested component in isolation
- [ ] Applied fix and verified
