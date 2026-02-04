# Process Video

Guide for processing videos through the QPrisma pipeline.

## Usage
```
/process-video <video_path_or_url> [--preset fast|balanced|quality] [--batch]
```

## Processing Pipeline Overview

```
Upload → Extract Frames → Analyze (GPT-4o) → Transcribe → Embed → Index
```

## API Endpoints

### 1. Upload Video

```bash
# Upload local file
curl -X POST "http://localhost:8000/upload" \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@/path/to/video.mp4" \
  -F "title=My Video" \
  -F "preset=balanced"

# Response
{
  "media_id": "abc123",
  "status": "uploaded",
  "message": "Video uploaded successfully"
}
```

### 2. Start Processing

```bash
# Process with FFmpeg pipeline
curl -X POST "http://localhost:8000/processing/ffmpeg/abc123" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "preset": "balanced",
    "enable_audio": true,
    "use_batch_api": true
  }'

# Response
{
  "job_id": "job-456",
  "status": "processing",
  "estimated_frames": 240
}
```

### 3. Check Status

```bash
curl "http://localhost:8000/jobs/job-456" \
  -H "Authorization: Bearer $TOKEN"

# Response
{
  "job_id": "job-456",
  "status": "completed",
  "progress": 100,
  "frames_processed": 240,
  "duration_seconds": 120
}
```

## Processing Presets

| Preset | FPS | Resolution | Use Case |
|--------|-----|------------|----------|
| `fast` | 1 | 720p | Quick preview, cost-sensitive |
| `balanced` | 2 | 1080p | General use (default) |
| `quality` | 5 | Original | High-fidelity analysis |
| `custom` | User-defined | User-defined | Special requirements |

## Custom Configuration

```python
from models.ffmpeg_config import FFmpegProcessingConfig

config = FFmpegProcessingConfig(
    # Frame extraction
    fps=2.0,                    # Frames per second
    max_frames=500,             # Maximum frames to extract
    start_time=0,               # Start position (seconds)
    end_time=None,              # End position (None = full video)

    # Quality settings
    width=1920,                 # Output width (None = original)
    height=1080,                # Output height (None = original)
    quality=85,                 # JPEG quality (1-100)

    # Processing options
    enable_audio=True,          # Extract and transcribe audio
    enable_scene_detection=True,# Detect scene changes
    use_hardware_accel=True,    # Use GPU if available

    # Batch API (50% cost savings)
    use_batch_api=True,         # Use Azure OpenAI Batch API
    batch_size=50,              # Frames per batch
)
```

## Programmatic Processing

```python
from services.ffmpeg_processor import FFmpegVideoProcessor
from services.video_processor import VideoProcessor
from models.ffmpeg_config import FFmpegProcessingConfig, ProcessingPreset

async def process_video(media_id: str, video_path: str):
    # Initialize processors
    ffmpeg = FFmpegVideoProcessor()
    processor = VideoProcessor()

    # Configure processing
    config = FFmpegProcessingConfig.from_preset(ProcessingPreset.BALANCED)

    # Step 1: Extract frames
    frames = await ffmpeg.extract_frames(video_path, config)
    print(f"Extracted {len(frames)} frames")

    # Step 2: Analyze frames with GPT-4o
    if config.use_batch_api:
        # Batch API - 50% cheaper, async
        from services.batch_processor import BatchProcessor
        batch = BatchProcessor()
        job_id = await batch.submit_batch(media_id, frames)
        # Poll for completion...
    else:
        # Standard API - immediate results
        analyses = await processor.analyze_frames(frames)

    # Step 3: Extract and transcribe audio
    if config.enable_audio:
        from services.audio_processor import AudioProcessor
        audio = AudioProcessor()
        transcript = await audio.transcribe(video_path)

    # Step 4: Generate embeddings
    from services.embedding_service import get_embedding_service
    embeddings = get_embedding_service()
    vectors = await embeddings.embed_batch([f["description"] for f in analyses])

    # Step 5: Index in Knowledge Graph
    from services.knowledge_graph import get_knowledge_graph_service
    kg = get_knowledge_graph_service()
    await kg.index_video(media_id, analyses, transcript, vectors)

    return {"status": "completed", "frames": len(frames)}
```

## Batch API Processing

For large videos (100+ frames), use Batch API for 50% cost savings:

```bash
# Submit batch job
curl -X POST "http://localhost:8000/batch/submit" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "media_id": "abc123",
    "frame_ids": ["frame-1", "frame-2", "..."]
  }'

# Check batch status
curl "http://localhost:8000/batch/status/batch-789" \
  -H "Authorization: Bearer $TOKEN"

# Get cost summary
curl "http://localhost:8000/batch/cost-summary" \
  -H "Authorization: Bearer $TOKEN"
```

## WebSocket Progress Updates

```typescript
const ws = new WebSocket(`ws://localhost:8000/ws/processing/${mediaId}`);

ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  console.log(`Progress: ${data.progress}%`);
  console.log(`Status: ${data.status}`);
  console.log(`Current frame: ${data.current_frame}`);
};
```

## Cost Estimation

```bash
# Estimate processing cost
curl "http://localhost:8000/batch/estimate?frame_count=100" \
  -H "Authorization: Bearer $TOKEN"

# Response
{
  "standard_cost": 0.50,
  "batch_cost": 0.25,
  "savings": "50%",
  "recommendation": "Use batch API"
}
```

## Troubleshooting

### Video Won't Upload
- Check file size (default max: 500MB)
- Verify format (MP4, MOV, AVI, WebM supported)
- Check Azure Blob Storage connection

### Processing Stuck
- Check Celery worker logs: `docker-compose logs celery-worker`
- Verify FFmpeg is installed: `ffmpeg -version`
- Check Azure OpenAI quota

### Poor Frame Quality
- Increase FPS in config
- Use `quality` preset
- Disable resolution scaling

### Missing Audio Transcription
- Ensure `enable_audio=True`
- Check Whisper deployment in Azure
- Verify video has audio track

## Checklist
- [ ] Video uploaded to Blob Storage
- [ ] Processing job started
- [ ] Frames extracted successfully
- [ ] GPT-4o analysis completed
- [ ] Audio transcribed (if enabled)
- [ ] Embeddings generated
- [ ] Data indexed in Neo4j
- [ ] Video ready for search
