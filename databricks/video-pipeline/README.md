# QPrisma Databricks video pipeline

This folder contains the initial Databricks Asset Bundle for the QPrisma video-processing pilot.

The Azure resources are provisioned by Bicep under `infra\`. This bundle owns the inside-Databricks workflow shape: jobs, task graph, parameters, permissions and future Lakeflow pipeline resources.

## Current scope

- Defines a `qprisma-video-processing` workflow with `dev` and `prod` targets.
- Runs a lakehouse pilot DAG with observable stages for manifest registration, source-media probe, FFmpeg audio extraction/chunking, FFmpeg frame extraction, `faster-whisper` ASR, temporal window/scene candidate detection, table-driven multimodal inference request generation, Azure OpenAI Batch payload staging, Azure OpenAI Batch inference/result ingestion, Gold result normalization, Neo4j graph upsert planning, Neo4j projection and outbox/status publication.
- Establishes stable parameters for the Service Bus driven pipeline: `media_id`, `blob_name`, `dispatch_id`, `source_media`, `pipeline_config`, catalog, schema and queue name.
- Writes stage events to the Delta table `${catalog}.${schema}.video_pipeline_events`.
- Writes frontend-compatible running/completion/failure records to `${catalog}.${schema}.video_pipeline_outbox`; this is the durable handoff point for projecting Databricks progress back into QPrisma PostgreSQL/Neo4j/Redis.
- Creates the first operational Delta contracts for the production ETL: `${catalog}.${schema}.video_media_manifest`, `video_source_files`, `video_processing_runs`, `video_job_stage_runs`, `video_audio_assets`, `video_audio_chunks`, `video_asr_runs`, `video_transcript_segments`, `video_frame_assets`, `video_temporal_windows`, `video_scene_candidates`, `video_ai_requests`, `video_ai_batches`, `video_ai_results`, `video_processing_results`, `video_graph_upserts` and `video_record_quarantine`.
- Creates a managed Unity Catalog artifact volume `${catalog}.${schema}.video_artifacts` for derived audio, frame and inference artifacts.

The current DAG shape is intentionally production-like. `extract_audio_assets`, `extract_frame_assets`, `run_faster_whisper_asr`, `detect_scenes_and_windows`, `build_multimodal_inference_requests`, `stage_ai_batch_payloads`, `run_ai_batch_inference`, `build_gold_processing_result`, `build_graph_upserts` and `project_neo4j_graph` are now functional ETL stages. The next missing production slice is broader observability/runbooks:

```text
register_manifest
  -> validate_and_probe_media
      -> extract_audio_assets
          -> run_faster_whisper_asr
      -> extract_frame_assets
      -> detect_scenes_and_windows  # waits for frames + ASR
          -> build_multimodal_inference_requests
          -> stage_ai_batch_payloads
              -> run_ai_batch_inference
                   -> build_gold_processing_result
                       -> build_graph_upserts
                           -> project_neo4j_graph
                               -> publish_outbox
```

`validate_and_probe_media` now performs Bronze quality gates before any expensive inference: it verifies the source file is readable, runs FFprobe, enforces size/duration/resolution/FPS/codec/audio policy, performs a small decode sample and records the technical metadata plus pass/fail details in `video_source_files` and `video_record_quarantine`. `extract_audio_assets` extracts a 16 kHz mono WAV with FFmpeg into `${catalog}.${schema}.video_artifacts`, splits it into bounded ASR chunks in `video_audio_chunks`, and records chunk offsets for parallel retries; if the validated source has no audio stream, this stage completes as an explicit skip so frame-only video understanding can continue. `extract_frame_assets` extracts representative frames with FFmpeg into the same artifact volume and registers them in `video_frame_assets`. `run_faster_whisper_asr` installs `faster-whisper`, transcribes registered audio chunks, writes an ASR run record and persists timestamped transcript segments; for silent videos it records an explicit ASR skip. `detect_scenes_and_windows` builds deterministic temporal windows and scene candidates from source duration, frame timestamps and transcript gaps, then persists them in `video_temporal_windows` and `video_scene_candidates` for Gold scene construction. `build_multimodal_inference_requests` creates idempotent `video_ai_requests` rows for frame understanding and transcript semantics. `stage_ai_batch_payloads` converts pending requests into governed Azure OpenAI Batch JSONL artifacts in `video_artifacts` and registers them in `video_ai_batches`. `run_ai_batch_inference` uploads ready batches to Azure OpenAI Batch, polls until completion within the configured wait window, downloads output/error JSONL files, writes normalized response rows to `video_ai_results` and updates request/batch lifecycle state. `build_gold_processing_result` normalizes transcript segments, frame understanding, scene candidates and transcript semantics into `video_processing_results` with a frontend-compatible `processing_result` shape containing `structure`, `audio_data`, `frames_data`, `video_metadata` and `processing_stats`. `build_graph_upserts` creates idempotent `video_graph_upserts` rows for Neo4j, including Gold scenes and chapters. `project_neo4j_graph` applies pending graph intents with Cypher `MERGE`, marks rows `applied` or `failed`, and fails the stage if any row cannot be projected. `publish_outbox` emits the Gold result after graph projection so the bridge can update PostgreSQL media rows without relying on Celery. Databricks remains the source of truth and Neo4j is a serving projection.

Azure OpenAI Batch is configured through `pipeline_config.azure_openai_batch` or Databricks environment variables. Do not put raw API keys in `pipeline_config`, because the notebook rejects raw secret-like fields before persisting the config in Delta manifests. Use either `api_key_secret_scope`/`api_key_secret_key` or `api_key_env`. The endpoint must be HTTPS and match the trusted Azure OpenAI suffix allowlist from the Databricks environment variable `AZURE_OPENAI_ALLOWED_ENDPOINT_SUFFIXES` (`openai.azure.com,cognitiveservices.azure.com` by default):

```json
{
  "azure_openai_batch": {
    "endpoint": "https://<resource>.openai.azure.com",
    "api_version": "2024-08-01-preview",
    "api_key_secret_scope": "qprisma",
    "api_key_secret_key": "azure-openai-api-key",
    "completion_window": "24h",
    "poll_interval_seconds": 30,
    "max_wait_seconds": 3600
  }
}
```

Bronze quality gates can be tuned with `pipeline_config.quality_gates` or `pipeline_config.quality`. Defaults are intentionally broad for the first Databricks rollout: files must be larger than 1 KiB, shorter than 4 hours, no larger than 20 GiB, at most 8K/120 FPS, and encoded with a common video codec. The notebook enforces bounded ranges for these values so a per-run config cannot disable decode sampling with a non-positive duration or raise limits beyond the deployment safety caps. Audio is optional by default because silent videos can still produce frame understanding:

```json
{
  "quality_gates": {
    "min_size_bytes": 1024,
    "max_size_bytes": 21474836480,
    "min_duration_seconds": 0.1,
    "max_duration_seconds": 14400,
    "max_width": 7680,
    "max_height": 4320,
    "max_fps": 120,
    "allowed_video_codecs": "av1,h264,hevc,mjpeg,mpeg4,vp8,vp9",
    "require_audio": false,
    "sample_decode_seconds": 1.0
  }
}
```

ASR chunking and deterministic scene/window detection are configured through the existing `pipeline_config.asr` / `pipeline_config.faster_whisper` and `pipeline_config.scene_detection` objects:

```json
{
  "asr": {
    "chunk_target_seconds": 300,
    "chunk_overlap_seconds": 5,
    "min_chunk_seconds": 2,
    "max_chunks": 200
  },
  "scene_detection": {
    "target_window_seconds": 60,
    "window_overlap_seconds": 5,
    "transcript_gap_seconds": 2.5,
    "min_scene_seconds": 8,
    "max_scene_seconds": 120
  }
}
```

This is intentionally a hybrid baseline rather than a black-box scene detector: FFmpeg/FFprobe and transcript gaps produce replayable candidates, Azure OpenAI frame/transcript understanding enriches them later, and Gold scenes keep evidence references back to frame and transcript segment IDs.

Neo4j projection is configured from deployment-owned Databricks environment variables, not caller-supplied endpoints in `pipeline_config`. The bundle exposes non-secret variables for `NEO4J_URI`, `NEO4J_USER`, `NEO4J_DATABASE` and an optional `NEO4J_ALLOWED_HOST_SUFFIXES` allowlist; set `NEO4J_PASSWORD` separately as a Databricks secret-backed cluster environment variable. `pipeline_config.neo4j.enabled` can explicitly require or disable projection for a run, but it cannot override the Neo4j endpoint or credential source. When Neo4j is not configured, `project_neo4j_graph` records an explicit skipped stage and still allows the Gold outbox to publish.

`project_neo4j_graph` reads pending or previously failed rows from `video_graph_upserts`, validates dynamic labels/relationship types before building Cypher, applies idempotent `MERGE` statements, and updates each row to `applied` or `failed`:

```json
{
  "neo4j": {
    "enabled": true
  }
}
```

If `pipeline_config.neo4j.enabled` is `true`, missing `NEO4J_URI` or `NEO4J_PASSWORD` is treated as a configuration error. If it is omitted, the projector runs only when `NEO4J_URI` is present and otherwise skips cleanly. Keep `index_graph: false` for runs that should not build graph upsert intents at all.

## Validate and deploy

Run these commands from this directory after installing the Databricks CLI and configuring authentication for the target workspace:

```powershell
databricks bundle validate --target dev
databricks bundle deploy --target dev
databricks bundle run video_processing --target dev
```

The bridge Function invokes this job through Databricks Jobs API `run-now` with `job_parameters`. The `source_media` parameter is a JSON object produced by QPrisma's control plane and must describe media that Databricks compute can read. The notebook accepts these source forms, in priority order:

| Field | Use |
|---|---|
| `volume_path` | Preferred path for the current pilot. The Azure Function bridge stages uploaded Blob media into the managed Unity Catalog volume and passes a logical path such as `/Volumes/dbw_qprisma_dev/video/source_media/<media-id>/<file-name>.mp4`. |
| `uri` | Explicit source URI. Supported values are `/Volumes/...`, `dbfs:/Volumes/...`, `abfss://...`, or `wasbs://...`. |
| `abfss_uri` / `wasbs_uri` | Explicit storage URI when Databricks has a valid UC external location or Hadoop credential for that path. |
| `container_name`, `blob_name`, `storage_account_url` | Fallback contract used by the control plane; the notebook derives `abfss://` for HNS accounts or `wasbs://` for Blob accounts. |

For `dev`, the validated source path is the managed Unity Catalog volume `dbw_qprisma_dev.video.source_media`. The original upload account `stqprismadev` is Blob/non-HNS, so it cannot be registered directly as a Unity Catalog external location. The Function bridge now performs this staging automatically before invoking `jobs/run-now`: it reads the upload Blob with managed identity, writes it to the UC volume through Databricks Files API, persists `pipeline_config.dispatch.source_media.volume_path`, and only then starts the processing job. Do not pass or persist physical `abfss://.../__unitystorage/...` backing URIs because Unity Catalog rejects reads that overlap managed storage internals.

The bridge staging settings are deployed as Function App settings:

| Setting | Purpose |
|---|---|
| `DATABRICKS_STAGING_ENABLED` | Enables Blob-to-UC-volume staging before Databricks processing. Default: `true`. |
| `DATABRICKS_SOURCE_VOLUME_CATALOG` | Catalog containing the managed source media volume. Default: `dbw_qprisma_dev`. |
| `DATABRICKS_SOURCE_VOLUME_SCHEMA` | Schema containing the managed source media volume. Default: `video`. |
| `DATABRICKS_SOURCE_VOLUME_NAME` | Managed volume used for staged uploads. Default: `source_media`. |
| `DATABRICKS_SOURCE_VOLUME_PREFIX` | Optional prefix inside the volume for staged source media. Default: empty. |
| `AZURE_STORAGE_MANAGED_IDENTITY_CLIENT_ID` | Managed identity client ID used by the bridge when reading the original upload Blob. |

The bridge identity also needs `Storage Blob Data Reader` on the upload storage account and Databricks permissions to write files into the target UC volume.

The local shell must be able to resolve `databricks`. If validation fails with `databricks` not found, refresh the shell/PATH or provide the explicit Databricks CLI installation path before deploying the bundle.

## Deploy the dispatch bridge

The Azure Function bridge code lives in `backend\functions\video_dispatch_bridge`. It is deployed by `.github\workflows\deploy-function-bridge.yml`, which packages that folder as the Function App root and deploys it with Azure OIDC using `az functionapp deployment source config-zip`.

The workflow runs on changes to the bridge package and can also be started manually. The default Function App name is `func-qprisma-dbx-bridge-flex-dev`; override it with the `DATABRICKS_BRIDGE_FUNCTION_APP_NAME` environment variable or the manual workflow input when needed. After a successful Flex deployment, the workflow removes the legacy Linux Consumption bridge app `func-qprisma-dbx-bridge-dev` and its `Y1` plan when they are no longer in use.

## Outbox projection back to QPrisma

Databricks writes durable status/result records to `${catalog}.${schema}.video_pipeline_outbox`. The pilot now emits intermediate `running` records for stage progress as well as terminal `completed`/`failed` records. The Azure Function bridge includes a timer-triggered outbox projector that:

1. polls the table through the Databricks SQL Statement Execution API;
2. applies each event to QPrisma PostgreSQL through the same `DatabricksStatusEvent` contract used by direct status events;
3. marks the row `consumed_at = current_timestamp()` only after PostgreSQL projection succeeds.

The projector is configured by Bicep through these Function App settings:

| Setting | Purpose |
|---|---|
| `DATABRICKS_SQL_WAREHOUSE_ID` | SQL warehouse used for Statement Execution polling. If empty, polling is skipped. |
| `DATABRICKS_OUTBOX_CATALOG` | Catalog that contains the outbox table. Default: `dbw_qprisma_dev`. |
| `DATABRICKS_OUTBOX_SCHEMA` | Schema that contains the outbox table. Default: `video`. |
| `DATABRICKS_OUTBOX_TABLE` | Outbox table name. Default: `video_pipeline_outbox`. |
| `DATABRICKS_OUTBOX_POLL_BATCH_SIZE` | Maximum rows projected per timer invocation. Default: `25`. |
| `OutboxPollSchedule` | Azure Functions NCRONTAB schedule. Default dev value: `0 */5 * * * *`. |

For the pilot, the Databricks job validates access to the original media, records operational events, persists manifests/stage runs/audio/frame/transcript/request/batch/result/Gold/graph/quarantine records and publishes frontend-compatible progress/failure/completion records. The DAG already exposes the planned production stages so QPrisma can validate orchestration, parallel branches and frontend progress while compute-heavy stages are added incrementally. The production pipeline should extend these stages with smarter audio chunking, stronger scene/window detection, data quality expectations and a dedicated graph projector while keeping the same dispatch and outbox contracts. Celery is not part of the target architecture for this pipeline.
