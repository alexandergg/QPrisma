# QPrisma Video Ingestion Architecture

This document explains how QPrisma ingests raw video, transforms it into multimodal knowledge, and publishes processing progress back to the user experience.

## Scope

This view focuses on:

- upload and durable handoff
- asynchronous orchestration
- visual and audio processing branches
- embedding generation and graph indexing
- completion, status tracking, and user notification

It does not attempt to re-document every backend class. For implementation detail, see `docs/BACKEND_ARCHITECTURE.md` and the Databricks bundle under `databricks\video-pipeline`.

## Related artifacts

- Published diagram asset: [assets/architecture/video-ingestion-pipeline.svg](assets/architecture/video-ingestion-pipeline.svg)
- Portfolio index: `docs/ARCHITECTURE_PORTFOLIO.md`
- Technical deep dive: `docs/ARCHITECTURE.md`
- Runtime orchestration: `databricks\video-pipeline`
- Databricks bundle package: `databricks\video-pipeline\src\qprisma_video_pipeline`
- Dispatch abstraction: `backend\services\video_processing_dispatch_service.py`
- Dispatch bridge: `backend\functions\video_dispatch_bridge`
- Upload routes: `backend/api/routes/media_routes.py`, `backend/api/routes/chunked_upload_routes.py`

![QPrisma video ingestion pipeline diagram](assets/architecture/video-ingestion-pipeline.svg)

## Architecture style

The ingestion path is best understood as a specialization of the Azure **queue-based load leveling** pattern:

- the web/API tier receives and validates uploads
- the queue decouples user-facing traffic from long-running processing
- Databricks Jobs perform CPU, I/O, and AI-heavy analysis asynchronously

QPrisma extends that baseline with parallel multimodal enrichment, graph indexing, and AI-driven summarization.

## End-to-end flow

| Stage | Primary component | What happens |
|---|---|---|
| Upload | FastAPI + Blob Storage | Raw media is uploaded directly into Azure Blob Storage |
| Metadata registration | FastAPI + PostgreSQL | Media metadata and initial processing state are recorded |
| Async dispatch | API + Service Bus | The control plane publishes the durable Databricks dispatch message |
| Download and extraction | Databricks + Blob/ADLS | The data plane reads the durable media asset and extracts/probes content |
| Visual analysis | Databricks inference stages | Frames are analyzed for OCR, entities, layout, actions, and quality |
| Audio analysis | Databricks audio/ASR stages | Audio is chunked, transcribed, and summarized |
| Semantic indexing | Embedding service + Neo4j | Embeddings and structured nodes are written to the knowledge graph |
| Enrichment | Summarization + graph builders | Scenes, chapters, entities, communities, and relationships are added |
| Completion | PostgreSQL status projection | Final state and progress are persisted for authenticated HTTP polling through `/media/{media_id}/status` |

## 1. Upload and durable handoff

QPrisma supports two upload modes:

- `POST /upload` for direct uploads
- `POST /upload/chunked/init` followed by chunk transfer and `POST /upload/chunked/commit` for larger uploads

The architectural goal is the same in both cases: move the raw asset to durable object storage first and keep the API tier short-lived.

### Why this matters

- The API tier stays responsive under large-file workloads.
- Azure Blob Storage becomes the system of record for the raw asset.
- PostgreSQL tracks processing state independently from the object payload.

### Solution Architect takeaway

This separation is important when documenting enterprise ingestion systems: raw binary durability and relational processing state should not be conflated.

## 2. Queue-based orchestration

Once the upload is durably registered, the API tier delegates to `VideoProcessingDispatchService`. The active backend is Service Bus/Databricks: the API publishes the media handoff as a durable Service Bus message and the Azure Function bridge starts the Databricks Job.

The control plane never exposes Databricks credentials to the browser. It still owns authentication, authorization, Blob upload contracts, idempotency and frontend-compatible state. The selected data plane owns the long-running enrichment path, which keeps HTTP request latency bounded and allows heavy processing to scale independently from frontend/API replicas.

### Key patterns

- queue-based load leveling through Azure Service Bus
- background execution in Databricks Jobs
- Function bridge ownership of Databricks Jobs API calls and outbox polling
- explicit job progress updates during the pipeline
- Databricks outbox projection for durable status/result handoff

### Why this matters

This is one of the clearest examples of the repo applying Azure architecture guidance correctly: user interaction and long-running compute are decoupled by design.

### Databricks dispatch path

When `PROCESSING_BACKEND` is set to `servicebus` or `databricks`, the upload route publishes a dispatch message to the `video-processing` Service Bus queue. The Azure Function bridge consumes the message with managed identity, validates the `source_media` contract, calls Databricks Jobs API `run-now`, and stores the `databricks_run_id` under `media.pipeline_config.dispatch`.

Databricks writes operational records to `${catalog}.${schema}.video_pipeline_events` and frontend-compatible status/result records to `${catalog}.${schema}.video_pipeline_outbox`. A timer-triggered Function polls the outbox through Databricks SQL, applies each event to PostgreSQL, and marks rows consumed only after projection succeeds. If `DATABRICKS_SQL_WAREHOUSE_ID` is not configured, outbox polling is skipped and API status will not receive Databricks result projection.

## 3. Databricks orchestration model

The Databricks bundle is the pipeline orchestrator. At a high level it performs the following responsibilities:

1. initialize runtime configuration, storage paths, and Delta contracts
2. record stage transitions in operational Delta tables
3. stage/read the video from Blob Storage or Unity Catalog volumes
4. extract frames, audio, quality signals, and media metadata
5. run visual and audio inference stages
6. build scene/chapter summaries and normalized Gold results
7. emit graph upsert rows and frontend-compatible outbox records
8. project final status/result through the bridge into PostgreSQL

The orchestration is intentionally centralized in Databricks so the data plane can own end-to-end processing continuity for a single media asset.

## 4. Visual processing branch

The visual branch turns raw frames into structured scene understanding.

### Extraction strategy

The Databricks extraction layer produces frame samples and quality metadata. QPrisma supports multiple extraction modes so processing can be adapted to the workload:

- uniform sampling
- keyframes-only extraction
- scene-aware extraction
- adaptive extraction
- deeper analysis-oriented extraction

### Cost-aware analysis strategy

Frame analysis is designed around Databricks-managed batch processing where possible. This is an explicit cost and throughput optimization:

- lower cost than synchronous per-frame calls
- better handling of large frame sets
- clearer separation between extraction and model execution

### Output shape

The visual branch produces machine-usable outputs such as:

- OCR text
- entities
- scene descriptions
- actions and relationships
- quality indicators and timestamps

## 5. Audio processing branch

Audio processing is intentionally parallel to visual analysis rather than waiting behind it.

The Databricks pipeline extracts audio from the staged file, runs transcription, and then performs transcript-level analysis when the transcript has enough substance to be meaningful.

### Runtime behavior

- transcription runs inside the Databricks data plane
- chunking keeps long audio workloads bounded and resumable
- transcript analysis is separated from raw transcription

### Architectural value

From a Solution Architect perspective, this is a strong example of workload partitioning:

- speech recognition and transcript reasoning are related but different concerns
- they can scale and fail independently from the visual branch
- the pipeline can still produce partial value when one modality is degraded

## 6. Convergence into semantic indexing

After the visual and audio branches finish, the system shifts from media processing to knowledge construction.

### Embeddings

QPrisma generates embeddings through Azure OpenAI and uses a dual-granularity strategy:

- full embeddings for precise semantic ranking
- coarse Matryoshka-style vectors for faster filtering

### Graph indexing

Neo4j stores the semantic representation of the processed asset. The indexed model is hierarchical:

- Video
- Chapter
- Scene
- Frame
- Entity
- AudioSegment
- Topic
- Community

This is not just a storage choice. It is the foundation of the downstream hosted agent retrieval experience.

## 7. Knowledge enrichment after indexing

The ingestion pipeline does more than attach embeddings to content. It also enriches the semantic structure for later retrieval.

Examples include:

- scene detection
- chapter grouping
- hierarchical summaries
- entity extraction and normalization
- semantic relationships
- temporal chains
- community detection
- cross-video entity resolution

This is why QPrisma should be presented as a **knowledge construction pipeline**, not merely as video preprocessing.

## 8. Status, progress, and completion

Databricks continuously emits status/outbox records as the pipeline advances. This design matters because media processing can be long-running and users need a durable, queryable processing state.

The completion path combines:

- PostgreSQL for final processing status
- HTTP status polling through `/media/{media_id}/status` as the durable cross-replica progress channel

## Reliability considerations

Key resilience choices visible in the implementation and architecture:

- raw asset durability in Blob Storage before asynchronous processing
- queue-based decoupling between user-facing and Databricks workloads
- explicit retries and fallback handling in some pipeline stages
- progress visibility instead of black-box batch processing
- partial degradation options across visual and audio sub-flows

## Performance and cost considerations

| Concern | Architectural response |
|---|---|
| Large upload payloads | Blob-first upload strategy and chunked upload support |
| Long-running work | Service Bus + Databricks Jobs separation |
| AI analysis cost | Batch/lakehouse processing outside the API request path |
| Pipeline latency | Parallel visual/audio execution where practical |
| Retrieval readiness | Embeddings + graph indexing during ingestion, not at query time |

## Risks and trade-offs

| Trade-off | Benefit | Cost |
|---|---|---|
| Queue-based processing | Better scale isolation and user responsiveness | More distributed system complexity |
| Heavy enrichment during ingestion | Better retrieval quality later | Longer processing time per asset |
| Multiple storage engines | Purpose-fit persistence | More operational surface area |
| Parallel multimodal processing | Lower end-to-end latency | More coordination and failure modes |

## How to present this as a Solution Architect

When presenting the ingestion architecture professionally, emphasize:

1. **architecture style**: queue-based load leveling with Databricks multimodal enrichment
2. **durability**: Blob Storage is the raw-media system of record
3. **decoupling**: API and Databricks processing scale independently
4. **cost discipline**: Batch-first AI processing decisions are intentional
5. **knowledge readiness**: ingestion is designed to feed GraphRAG and hosted-agent retrieval

That framing moves the discussion from "video upload" to "enterprise knowledge extraction pipeline."
