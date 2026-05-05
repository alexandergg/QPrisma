# QPrisma Databricks video pipeline

This folder contains the initial Databricks Asset Bundle for the QPrisma video-processing pilot.

The Azure resources are provisioned by Bicep under `infra\`. This bundle owns the inside-Databricks workflow shape: jobs, task graph, parameters, permissions and future Lakeflow pipeline resources.

## Current scope

- Defines a `qprisma-video-processing` workflow with `dev` and `prod` targets.
- Runs a lakehouse pilot DAG with observable stages for manifest registration, source-media probe, FFmpeg audio extraction/chunking, FFmpeg frame extraction, `faster-whisper` ASR, temporal window/scene candidate detection, table-driven multimodal inference request generation, Azure OpenAI Batch payload staging, Azure OpenAI Batch inference/result ingestion, Gold result normalization, Neo4j graph upsert planning, Neo4j projection and outbox/status publication.
- Installs `ffmpeg` and `ffprobe` on the job cluster through `scripts\install-ffmpeg.sh`; these binaries are required by Bronze quality gates, audio extraction and frame extraction.
- Writes FFmpeg-derived audio and frame files to local cluster storage first, then copies them into Unity Catalog Volumes; this avoids FUSE limitations for encoders that need seek/trailer operations when closing output files.
- Establishes stable parameters for the Service Bus driven pipeline: `media_id`, `blob_name`, `dispatch_id`, `source_media`, `pipeline_config`, catalog, schema and queue name.
- Writes stage events to the Delta table `${catalog}.${schema}.video_pipeline_events`.
- Writes frontend-compatible running/completion/failure records to `${catalog}.${schema}.video_pipeline_outbox`; this is the durable handoff point for projecting Databricks progress back into QPrisma PostgreSQL/Neo4j/Redis.
- Creates the first operational Delta contracts for the production ETL: `${catalog}.${schema}.video_media_manifest`, `video_source_files`, `video_processing_runs`, `video_job_stage_runs`, `video_audio_assets`, `video_audio_chunks`, `video_asr_runs`, `video_transcript_segments`, `video_frame_assets`, `video_temporal_windows`, `video_scene_candidates`, `video_ai_requests`, `video_ai_batches`, `video_ai_results`, `video_processing_results`, `video_graph_upserts` and `video_record_quarantine`.
- Creates a managed Unity Catalog artifact volume `${catalog}.${schema}.video_artifacts` for derived audio, frame and inference artifacts.

The current DAG shape is intentionally production-like. `extract_audio_assets`, `extract_frame_assets`, `run_faster_whisper_asr`, `detect_scenes_and_windows`, `build_multimodal_inference_requests`, `stage_ai_batch_payloads`, `run_ai_batch_inference`, `build_gold_processing_result`, `build_graph_upserts` and `project_neo4j_graph` are now functional ETL stages. Operational visibility is table-driven through Delta so runs can be monitored, replayed and compared before rollout:

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

## Operations and monitoring runbook

Run these queries in a Databricks SQL warehouse that has `SELECT` access to the pipeline catalog and schema. Replace `${catalog}.${schema}` with the deployed target, for example `dbw_qprisma_dev.video`. The tables are Delta contracts written by the workflow; Databricks Job history remains useful for cluster-level failures, but the queries below are the source of truth for product-visible pipeline state.

### Active runs and current stage

Use this query for the primary operations dashboard. It shows every active or recently terminal run, the current stage, whether the frontend outbox has published a terminal event, and the newest stage message:

```sql
WITH latest_stage AS (
  SELECT *
  FROM (
    SELECT
      *,
      row_number() OVER (
        PARTITION BY media_id, dispatch_id
        ORDER BY started_at DESC
      ) AS rn
    FROM ${catalog}.${schema}.video_job_stage_runs
  )
  WHERE rn = 1
),
terminal_outbox AS (
  SELECT
    media_id,
    dispatch_id,
    max(emitted_at) AS terminal_emitted_at,
    max(consumed_at) AS terminal_consumed_at
  FROM ${catalog}.${schema}.video_pipeline_outbox
  WHERE status IN ('completed', 'failed', 'completed_with_warnings')
  GROUP BY media_id, dispatch_id
)
SELECT
  r.media_id,
  r.dispatch_id,
  r.status AS run_status,
  r.progress,
  r.current_stage,
  s.status AS stage_status,
  s.message AS stage_message,
  round((unix_timestamp(coalesce(s.completed_at, current_timestamp())) - unix_timestamp(s.started_at)) / 60, 2) AS stage_minutes,
  r.started_at,
  r.updated_at,
  t.terminal_emitted_at,
  t.terminal_consumed_at
FROM ${catalog}.${schema}.video_processing_runs r
LEFT JOIN latest_stage s
  ON r.media_id = s.media_id
 AND r.dispatch_id = s.dispatch_id
LEFT JOIN terminal_outbox t
  ON r.media_id = t.media_id
 AND r.dispatch_id = t.dispatch_id
WHERE r.updated_at >= current_timestamp() - INTERVAL 48 HOURS
   OR r.status IN ('running', 'queued')
ORDER BY r.updated_at DESC;
```

### Stage duration and retry pressure

Use this to find bottlenecks, stuck stages and stages that are failing repeatedly. `attempt` is currently `1` per stage run key, so repeated failures for the same media should be interpreted through status changes and reruns by `media_id`/`dispatch_id`.

```sql
SELECT
  stage,
  status,
  count(*) AS stage_runs,
  round(avg(unix_timestamp(coalesce(completed_at, current_timestamp())) - unix_timestamp(started_at)), 2) AS avg_seconds,
  percentile_approx(unix_timestamp(coalesce(completed_at, current_timestamp())) - unix_timestamp(started_at), 0.95) AS p95_seconds,
  sum(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed_runs,
  max(started_at) AS newest_started_at
FROM ${catalog}.${schema}.video_job_stage_runs
WHERE started_at >= current_timestamp() - INTERVAL 7 DAYS
GROUP BY stage, status
ORDER BY stage, status;
```

### Outbox backlog and projector health

The Azure Function bridge should consume rows only after PostgreSQL projection succeeds. If `pending_rows` grows, check `DATABRICKS_SQL_WAREHOUSE_ID`, the Function timer trigger, Databricks SQL Statement Execution API permissions and PostgreSQL connectivity before changing data manually.

```sql
SELECT
  status,
  count(*) AS pending_rows,
  min(emitted_at) AS oldest_emitted_at,
  max(emitted_at) AS newest_emitted_at,
  round((unix_timestamp(current_timestamp()) - unix_timestamp(min(emitted_at))) / 60, 2) AS oldest_age_minutes
FROM ${catalog}.${schema}.video_pipeline_outbox
WHERE consumed_at IS NULL
GROUP BY status
ORDER BY oldest_emitted_at;
```

### Quarantine and hard failures

Quarantine records are created before expensive inference when media fails source validation, quality gates or a stage-level contract. Fix the source/configuration issue first, then rerun the Databricks job with the same `media_id` and `dispatch_id`; idempotent `MERGE` operations will update the existing run records.

```sql
SELECT
  q.created_at,
  q.media_id,
  q.dispatch_id,
  q.stage,
  q.reason,
  q.error_type,
  q.details,
  r.status AS run_status,
  r.current_stage,
  r.error AS run_error
FROM ${catalog}.${schema}.video_record_quarantine q
LEFT JOIN ${catalog}.${schema}.video_processing_runs r
  ON q.media_id = r.media_id
 AND q.dispatch_id = r.dispatch_id
WHERE q.created_at >= current_timestamp() - INTERVAL 14 DAYS
ORDER BY q.created_at DESC;
```

### AI Batch, tokens and cost inputs

This pipeline records token usage in `video_ai_results` and lifecycle state in `video_ai_batches`. Cost should be calculated outside the notebook from the deployed Azure OpenAI price sheet for each `model_name`; do not hard-code prices in the pipeline.

```sql
SELECT
  r.media_id,
  r.dispatch_id,
  r.model_name,
  count(*) AS result_rows,
  sum(coalesce(r.tokens_prompt, 0)) AS prompt_tokens,
  sum(coalesce(r.tokens_completion, 0)) AS completion_tokens,
  sum(coalesce(r.tokens_prompt, 0) + coalesce(r.tokens_completion, 0)) AS total_tokens,
  max(b.provider_status) AS provider_status,
  max(b.status) AS batch_status,
  max(b.error) AS batch_error
FROM ${catalog}.${schema}.video_ai_results r
LEFT JOIN ${catalog}.${schema}.video_ai_batches b
  ON r.batch_id = b.batch_id
WHERE r.created_at >= current_timestamp() - INTERVAL 30 DAYS
GROUP BY r.media_id, r.dispatch_id, r.model_name
ORDER BY total_tokens DESC;
```

### Media quality, ASR coverage and scene density

Use these checks to compare Databricks output quality across presets and against the Celery baseline. Low transcript coverage can indicate missing audio, ASR chunking issues or an overly strict quality gate. Very low scene density can indicate sparse frame sampling or transcript gaps that are too large for the content.

```sql
WITH audio_chunks AS (
  SELECT media_id, dispatch_id, count(*) AS audio_chunks
  FROM ${catalog}.${schema}.video_audio_chunks
  GROUP BY media_id, dispatch_id
),
transcript AS (
  SELECT
    media_id,
    dispatch_id,
    count(*) AS transcript_segments,
    round(sum(coalesce(end_ms - start_ms, 0)) / 1000, 2) AS transcript_seconds
  FROM ${catalog}.${schema}.video_transcript_segments
  GROUP BY media_id, dispatch_id
),
frames AS (
  SELECT media_id, dispatch_id, count(*) AS frames
  FROM ${catalog}.${schema}.video_frame_assets
  GROUP BY media_id, dispatch_id
),
windows AS (
  SELECT media_id, dispatch_id, count(*) AS temporal_windows
  FROM ${catalog}.${schema}.video_temporal_windows
  GROUP BY media_id, dispatch_id
),
scenes AS (
  SELECT media_id, dispatch_id, count(*) AS scene_candidates
  FROM ${catalog}.${schema}.video_scene_candidates
  GROUP BY media_id, dispatch_id
)
SELECT
  s.media_id,
  s.dispatch_id,
  s.quality_status,
  s.duration_seconds,
  s.video_codec,
  s.audio_codec,
  s.width,
  s.height,
  s.fps,
  coalesce(c.audio_chunks, 0) AS audio_chunks,
  coalesce(t.transcript_segments, 0) AS transcript_segments,
  coalesce(t.transcript_seconds, 0) AS transcript_seconds,
  coalesce(f.frames, 0) AS frames,
  coalesce(w.temporal_windows, 0) AS temporal_windows,
  coalesce(sc.scene_candidates, 0) AS scene_candidates,
  s.validated_at
FROM ${catalog}.${schema}.video_source_files s
LEFT JOIN audio_chunks c
  ON s.media_id = c.media_id
 AND s.dispatch_id = c.dispatch_id
LEFT JOIN transcript t
  ON s.media_id = t.media_id
 AND s.dispatch_id = t.dispatch_id
LEFT JOIN frames f
  ON s.media_id = f.media_id
 AND s.dispatch_id = f.dispatch_id
LEFT JOIN windows w
  ON s.media_id = w.media_id
 AND s.dispatch_id = w.dispatch_id
LEFT JOIN scenes sc
  ON s.media_id = sc.media_id
 AND s.dispatch_id = sc.dispatch_id
WHERE s.validated_at >= current_timestamp() - INTERVAL 30 DAYS
ORDER BY s.validated_at DESC;
```

### Graph projection repair

`video_graph_upserts` is the durable queue for Neo4j serving projection. If rows fail, fix Neo4j deployment settings or data validation first, then rerun `project_neo4j_graph` or the full job. Rows already marked `applied` are preserved when the same source hash is replayed.

```sql
SELECT
  media_id,
  dispatch_id,
  operation_type,
  label_or_type,
  source_table,
  status,
  count(*) AS rows,
  min(created_at) AS oldest_created_at,
  max(updated_at) AS newest_updated_at,
  max(error) AS latest_error
FROM ${catalog}.${schema}.video_graph_upserts
WHERE status <> 'applied'
GROUP BY media_id, dispatch_id, operation_type, label_or_type, source_table, status
ORDER BY oldest_created_at;
```

### Replay and reprocess checklist

1. For source or quality failures, inspect `video_record_quarantine` and `video_source_files.quality_details`, fix the upload/source metadata or `pipeline_config.quality_gates`, then rerun the same Databricks job parameters.
2. For ASR or frame extraction failures, confirm FFmpeg can read the staged UC volume path, check `video_audio_chunks` or `video_frame_assets` counts, then rerun the failed task or full job.
3. For Azure OpenAI Batch failures, inspect `video_ai_batches.provider_status`, `provider_error_file_id` and `error`; fix endpoint/secret/quota/model deployment, then rerun from `stage_ai_batch_payloads` or the full job.
4. For outbox projector backlog, validate the Function timer trigger, SQL warehouse ID, Databricks permissions and PostgreSQL connectivity before editing `consumed_at`.
5. For Neo4j projection failures, inspect `video_graph_upserts.error`, validate `NEO4J_URI`, `NEO4J_PASSWORD`, host allowlist and database permissions, then rerun `project_neo4j_graph`.
6. For product parity analysis, export the Gold row from `video_processing_results.processing_result_json` and compare it with the legacy Celery result for transcript coverage, scene/chapter count, frame descriptions, graph upsert completeness, total tokens and wall-clock duration.

## Parity and rollout validation

Databricks should remain a shadow or opt-in backend until it passes product parity against the current Celery path. Use the same uploaded videos and comparable processing presets, but keep separate `dispatch_id` values so Delta, PostgreSQL and Neo4j records stay traceable.

Recommended shadow dataset:

| Case | Purpose |
|---|---|
| Short spoken video | Fast end-to-end smoke test for transcript, frames, Gold result and outbox projection. |
| Silent or music-only video | Verifies audio-less quality gates, explicit ASR skip and frame-only understanding. |
| Long meeting or lecture | Exercises ASR chunk coverage, retries, token volume and scene/window density. |
| Screen recording or slides | Checks OCR-like frame descriptions, chapter quality and graph entities. |
| Low-quality or unusual codec sample | Validates quarantine behavior and source quality diagnostics before inference spend. |

Run the comparison in this order:

1. Process each sample with the legacy Celery backend and preserve the product-visible PostgreSQL media row plus any Neo4j graph records as the baseline.
2. Process the same sample through Databricks with equivalent `preset`, `max_frames`, `custom_prompt`, `index_graph` and model configuration.
3. Confirm Databricks emits terminal `video_pipeline_outbox` rows and the bridge projects them to PostgreSQL without manual edits.
4. Compare `video_processing_results.processing_result_json` against the legacy result for required frontend fields: `structure`, `audio_data`, `frames_data`, `video_metadata` and `processing_stats`.
5. Compare quality and completeness using the monitoring queries above: transcript seconds, segment count, frame count, scene candidates, Gold scenes/chapters, graph upsert status and total token usage.
6. Record wall-clock duration from `video_processing_runs.started_at/completed_at` and stage durations from `video_job_stage_runs` so rollout decisions are based on per-stage bottlenecks, not only terminal status.

Acceptance gates before making Databricks the default backend:

| Gate | Acceptance requirement |
|---|---|
| Frontend contract | PostgreSQL projection from Databricks renders the same product views without frontend changes. |
| Transcript | Videos with audio produce timestamped transcript segments unless explicitly quarantined; silent videos complete with an ASR skip rather than failing. |
| Scenes and chapters | Gold scenes/chapters are present for valid videos and include evidence references to frames or transcript segments. |
| Graph projection | When `index_graph` is enabled and Neo4j is configured, `video_graph_upserts` rows reach `applied` or expose actionable failure details. |
| Operations | Active runs, failures, outbox backlog, token usage and quality metrics are visible through Delta queries without inspecting notebook logs. |
| Replay | Rerunning the same `media_id` and `dispatch_id` does not duplicate durable records or corrupt already-applied serving projections. |
| Cost and latency | Token totals and stage durations are captured for every sample so QPrisma can choose rollout thresholds per environment. |

Roll out by environment and feature flag:

1. Keep Celery as the baseline while Databricks runs shadow jobs for representative videos.
2. Enable Databricks for internal/dev users once the acceptance gates pass in `dev`.
3. Promote the Asset Bundle to `prod` only after Databricks SQL warehouse access, Function bridge settings, UC volume permissions, Azure OpenAI Batch secrets and Neo4j deployment variables are verified.
4. Switch `PROCESSING_BACKEND=databricks` for a controlled cohort, monitor outbox backlog and failure/quarantine rate, then expand.
5. Retire Celery video-processing code only after the Databricks backend is the default, rollback criteria are agreed and no product surface depends on worker-only artifacts.

## Validate and deploy

Run these commands from this directory after installing the Databricks CLI and configuring authentication for the target workspace:

```powershell
databricks bundle validate --target dev
databricks bundle deploy --target dev
databricks bundle run video_processing --target dev
```

If the local Databricks `DEFAULT` profile points at an old workspace, prefer an explicit Azure CLI authenticated host for the current workspace:

```powershell
$workspaceUrl = az databricks workspace show `
  --resource-group rg-qprisma-dev `
  --name dbw-qprisma-dev `
  --query workspaceUrl `
  -o tsv
$env:DATABRICKS_HOST = "https://$workspaceUrl"
$env:DATABRICKS_AUTH_TYPE = "azure-cli"
databricks bundle validate --target dev
databricks bundle deploy --target dev
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

For the pilot, the Databricks job validates access to the original media, records operational events, persists manifests/stage runs/audio/frame/transcript/request/batch/result/Gold/graph/quarantine records and publishes frontend-compatible progress/failure/completion records. The DAG now exposes the planned production stages and operational tables so QPrisma can validate orchestration, parallel branches, frontend progress, quality metrics and replay behavior before rollout. Celery is not part of the target architecture for this pipeline.
