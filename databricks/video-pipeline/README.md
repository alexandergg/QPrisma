# QPrisma Databricks video pipeline

This folder contains the initial Databricks Asset Bundle for the QPrisma video-processing pilot.

The Azure resources are provisioned by Bicep under `infra\`. This bundle owns the inside-Databricks workflow shape: jobs, task graph, parameters, permissions and future Lakeflow pipeline resources.

## Current scope

- Defines a `qprisma-video-processing` workflow with `dev` and `prod` targets.
- Runs a lakehouse pilot DAG with observable stages for manifest registration, source-media probe, FFmpeg audio extraction/chunking, FFmpeg frame extraction, Florence-2 frame analysis, `faster-whisper` ASR, temporal window/scene candidate detection, Databricks Gemma 3 scene reasoning, Gold result normalization, Neo4j graph upsert planning, Neo4j projection and outbox/status publication.
- Creates a dedicated all-purpose warm cluster `qprisma-video-processing-${bundle.target}-warm` with Databricks Runtime ML CPU, `ffmpeg`/`ffprobe`, Florence revision pinning and Neo4j secret references so workflow runs do not wait for a new job cluster to start each time.
- Writes FFmpeg-derived audio and frame files to local cluster storage first, then copies them into Unity Catalog Volumes; this avoids FUSE limitations for encoders that need seek/trailer operations when closing output files.
- Establishes stable parameters for the Service Bus driven pipeline: `media_id`, `blob_name`, `dispatch_id`, `source_media`, `pipeline_config`, catalog, schema and queue name.
- Writes stage events to the Delta table `${catalog}.${schema}.video_pipeline_events`.
- Writes frontend-compatible running/completion/failure records to `${catalog}.${schema}.video_pipeline_outbox`; this is the durable handoff point for projecting Databricks progress back into QPrisma PostgreSQL/Neo4j for authenticated status polling.
- Creates the first operational Delta contracts for the production ETL: `${catalog}.${schema}.video_media_manifest`, `video_source_files`, `video_processing_runs`, `video_job_stage_runs`, `video_audio_assets`, `video_audio_chunks`, `video_asr_runs`, `video_transcript_segments`, `video_frame_assets`, `video_frame_analysis`, `video_temporal_windows`, `video_scene_candidates`, `video_scene_visual_analysis`, `video_model_inference_runs`, `video_ai_requests`, `video_ai_batches`, `video_ai_results`, `video_processing_results`, `video_graph_upserts` and `video_record_quarantine`.
- Creates a managed Unity Catalog artifact volume `${catalog}.${schema}.video_artifacts` for derived audio, frame and inference artifacts.

## Code organization

The workflow still uses `notebooks/video_pipeline_ops.py` as the Databricks task entrypoint so the Asset Bundle task graph and `stage` parameter contract remain stable. The notebook is intentionally thin: it resolves the sibling `src` folder in the deployed bundle, imports `qprisma_video_pipeline.runner`, and delegates execution to normal Python modules.

Pipeline implementation lives under `src/qprisma_video_pipeline/`:

| Module | Responsibility |
|--------|----------------|
| `contracts.py` | Delta table names, Spark schemas, stage order, progress and security allowlists. |
| `runtime.py` / `runner.py` | Widget registration, runtime namespace binding, qualified table names and notebook entrypoint orchestration. |
| `tables.py` / `observability.py` | Delta DDL, schema evolution, events, outbox, processing runs, stage runs and quarantine writes. |
| `source_media.py` / `stage_utils.py` | Source-media URI validation, Databricks binary file probing and shared observable stage helpers. |
| `storage_paths.py`, `ffmpeg.py`, `quality.py`, `audio.py`, `frames.py` | Artifact paths, FFmpeg/FFprobe execution, Bronze quality gates, audio extraction/chunking/ASR, and frame extraction. |
| `inference/florence.py` | Florence-2 frame analysis on the Databricks job cluster. |
| `inference/azure_openai_batch.py` | Azure OpenAI batch staging/submission/polling helpers retained for the existing contract. |
| `scenes.py` | Transcript/frame loading, deterministic scene/window detection and Databricks Foundation Model scene reasoning. |
| `gold.py` | Frontend-compatible Gold `processing_result` construction. |
| `graph.py` | Graph upsert intent generation and Neo4j projection. |
| `stages.py` | Explicit stage dispatcher preserving the current `stage` names used by `databricks.yml`. |

For local safety checks, compile the package and run the pure-Python tests without requiring a Databricks runtime:

```powershell
python -m compileall -q databricks\video-pipeline\src databricks\video-pipeline\notebooks\video_pipeline_ops.py
$env:PYTHONPATH = "databricks\video-pipeline\src"; backend\.venv\Scripts\python.exe -m pytest databricks\video-pipeline\tests -q
```

The local test suite stubs the small subset of `pyspark.sql.types` needed to import the package, so it validates configuration parsing, source-media URI safety, runtime table naming, quality gates, Gold result helpers and deterministic scene/window logic without a Spark cluster. Full media probing, Delta writes, FFmpeg execution, model inference and Jobs API behavior still require a Databricks workspace.

The current DAG shape is intentionally production-like and does not require backend changes to pass a new inference mode. `extract_audio_assets`, `extract_frame_assets`, `run_florence_frame_analysis`, `run_faster_whisper_asr`, `detect_scenes_and_windows`, `run_databricks_scene_reasoning`, `build_gold_processing_result`, `build_graph_upserts` and `project_neo4j_graph` are now functional ETL stages. Operational visibility is table-driven through Delta so runs can be monitored, replayed and compared before rollout:

```text
register_manifest
  -> validate_and_probe_media
      -> extract_audio_assets
          -> run_faster_whisper_asr
      -> extract_frame_assets
          -> run_florence_frame_analysis  # CPU ML warm cluster for smoke validation, Florence-2 large-ft
      -> detect_scenes_and_windows  # waits for frames + ASR
          -> run_databricks_scene_reasoning  # waits for scenes + Florence, calls Gemma 3
              -> build_gold_processing_result
                  -> build_graph_upserts
                      -> project_neo4j_graph
                          -> publish_outbox
```

`validate_and_probe_media` now performs Bronze quality gates before any expensive inference: it verifies the source file is readable, runs FFprobe, enforces size/duration/resolution/FPS/codec/audio policy, performs a small decode sample and records the technical metadata plus pass/fail details in `video_source_files` and `video_record_quarantine`. `extract_audio_assets` extracts a 16 kHz mono WAV with FFmpeg into `${catalog}.${schema}.video_artifacts`, splits it into bounded ASR chunks in `video_audio_chunks`, and records chunk offsets for parallel retries; if the validated source has no audio stream, this stage completes as an explicit skip so frame-only video understanding can continue. `extract_frame_assets` extracts representative frames with FFmpeg into the same artifact volume and registers them in `video_frame_assets`. `run_florence_frame_analysis` loads `microsoft/Florence-2-large-ft` on the dedicated CPU ML warm cluster for smoke validation, runs bounded caption/OCR tasks over registered frames by default, and writes per-frame/per-task rows to `video_frame_analysis` plus run metrics to `video_model_inference_runs`. `run_faster_whisper_asr` installs `faster-whisper`, transcribes registered audio chunks, writes an ASR run record and persists timestamped transcript segments; for silent videos it records an explicit ASR skip. `detect_scenes_and_windows` builds deterministic temporal windows and scene candidates from source duration, frame timestamps and transcript gaps, then persists them in `video_temporal_windows` and `video_scene_candidates` for Gold scene construction. `run_databricks_scene_reasoning` calls the Databricks Foundation Model API endpoint `databricks-gemma-3-12b` over selected scenes using transcript + Florence signals + bounded frame images, validates JSON output and writes `video_scene_visual_analysis`. `build_gold_processing_result` normalizes transcript segments, Florence frame understanding, Gemma scene reasoning and scene candidates into `video_processing_results` with a frontend-compatible `processing_result` shape containing `structure`, `audio_data`, `frames_data`, `video_metadata` and `processing_stats`. `build_graph_upserts` creates idempotent `video_graph_upserts` rows for Neo4j, including Gold scenes, chapters, frames, transcript segments and Florence-derived `Entity` nodes linked from frames. `project_neo4j_graph` applies pending graph intents with Cypher `MERGE`, marks rows `applied` or `failed`, and fails the stage if any row cannot be projected. `publish_outbox` emits the Gold result after graph projection so the bridge can update PostgreSQL media rows without relying on a local worker. Databricks remains the source of truth and Neo4j is a serving projection.

`inference.mode` is optional. If the backend sends the existing legacy `pipeline_config` without an `inference` section, the notebook defaults to `local_databricks` and the bundle runs Florence + Gemma 3 directly. While Florence is on CPU, defaults are intentionally bounded for smoke validation: 5 frames, `caption` + `ocr`, and 1 Gemma scene with up to 2 evidence frames. Override these only for targeted validation runs:

```json
{
  "inference": {
    "mode": "local_databricks",
    "frame_analysis": {
      "enabled": true,
      "provider": "databricks_job",
      "model": "microsoft/Florence-2-large-ft",
      "tasks": ["caption", "ocr"],
      "batch_size": 2,
      "max_frames": 5,
      "max_new_tokens": 512,
      "device": "auto",
      "torch_dtype": "auto"
    },
    "scene_visual_reasoning": {
      "enabled": true,
      "provider": "databricks_foundation_model",
      "endpoint": "databricks-gemma-3-12b",
      "max_scenes": 1,
      "max_frames_per_scene": 2,
      "output_schema": "qprisma_scene_visual_v1",
      "request_timeout_seconds": 120,
      "max_retries": 2
    }
  }
}
```

The workflow uses the bundle-managed all-purpose cluster `qprisma-video-processing-${bundle.target}-warm` instead of per-run job clusters, so repeated dev uploads can reuse an already-running runtime. The cluster auto-terminates after `warm_cluster_autotermination_minutes` idle minutes, defaults to `Standard_DS3_v2`, and the job is capped at one concurrent run to avoid saturating the CPU node while Florence is not on GPU. Override the CPU node with the bundle variable `florence_cpu_node_type` if `Standard_DS3_v2` is too small for smoke validation. This CPU path is intended for small validation runs only; keep `frame_analysis.max_frames` and `frame_analysis.tasks` bounded until an NCASv3_T4 quota increase is available. The MVP intentionally allowlists only `microsoft/Florence-2-large-ft` because the model requires `trust_remote_code`; the bundle variable `florence_model_revision` sets `QPRISMA_FLORENCE_MODEL_REVISION` to a vetted commit instead of loading the mutable default branch or accepting arbitrary model revisions from `pipeline_config`.

Gemma 3 uses the Databricks serving endpoint path `/serving-endpoints/databricks-gemma-3-12b/invocations`. The endpoint name is validated as a serving endpoint identifier, and the workspace host is taken only from deployment-owned `DATABRICKS_HOST` or the notebook context. In jobs, use `DATABRICKS_TOKEN` when needed; otherwise the notebook falls back to the Databricks context API token.

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
    "preset": "quality",
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

ASR `preset` defaults to `quality` (`large-v3`) to preserve existing output quality. Use `fast` (`turbo`) for latency-sensitive runs, `balanced` (`distil-large-v3`) for a middle ground, or `custom` with an explicit `model_name`/`model_size`. Stage metrics record the selected preset, model, device, compute type, real-time factor and audio throughput so presets can be compared run-over-run.

Frame extraction supports bounded sampling controls through `pipeline_config.frames` / `pipeline_config.frame_extraction`. The extractor deduplicates near-identical timestamps with `min_spacing_seconds` before invoking FFmpeg and skips duplicate frame hashes by default, reducing downstream visual inference work on short or low-motion videos:

```json
{
  "frames": {
    "method": "uniform",
    "max_frames": 20,
    "min_spacing_seconds": 0.2,
    "dedupe_hashes": true,
    "format": "jpg",
    "quality": 2
  }
}
```

This is intentionally a hybrid baseline rather than a black-box scene detector: FFmpeg/FFprobe and transcript gaps produce replayable candidates, Florence enriches frame-level signals, Gemma 3 enriches scene-level reasoning, and Gold scenes keep evidence references back to frame and transcript segment IDs.

Neo4j projection is configured from deployment-owned Databricks environment variables, not caller-supplied endpoints in `pipeline_config`. The bundle exposes non-secret variables for `NEO4J_URI`, `NEO4J_USER`, `NEO4J_DATABASE`, `NEO4J_ALLOWED_HOST_SUFFIXES`, `NEO4J_PASSWORD_SECRET_SCOPE` and `NEO4J_PASSWORD_SECRET_KEY`; the notebook reads the password lazily with `dbutils.secrets.get()` only when projection is enabled. `pipeline_config.neo4j.enabled` can explicitly require or disable projection for a run, but it cannot override the Neo4j endpoint or credential source. When projection is skipped, `project_neo4j_graph` records a specific `skipped_reason` (`neo4j_disabled_by_config`, `graph_indexing_disabled`, `neo4j_uri_missing`, or `neo4j_password_missing`) and still allows the Gold outbox to publish.

`project_neo4j_graph` reads pending or previously failed rows from `video_graph_upserts`, validates dynamic labels/relationship types before building Cypher, applies idempotent `MERGE` statements, and updates each row to `applied` or `failed`:

```json
{
  "neo4j": {
    "enabled": true
  }
}
```

If `pipeline_config.neo4j.enabled` is `true`, missing `NEO4J_URI` or password secret configuration is treated as a configuration error. If it is omitted, the projector runs only when `NEO4J_URI` and a password source are present and otherwise skips cleanly. When projection is enabled, the stage validates the Neo4j config before checking for pending upserts, so missing password/user/database settings are visible even on replayed runs. Keep `index_graph: false` for runs that should not build graph upsert intents at all.

The Databricks graph projector uses the existing QPrisma Knowledge Graph contract rather than a separate semantic model. It writes `Video.video_id`, `Chapter.id`, `Scene.id`, `Frame.id` and `AudioSegment.id` keys, uses `CONTAINS` for Video/Chapter/Scene/Frame hierarchy, and uses `HAS_TRANSCRIPT` for transcript segments so backend graph queries and indexes continue to work against projected records. Operational rows such as ASR runs and AI requests remain in Delta tables and are not projected as first-class graph nodes.

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

### Stage throughput baseline

Completed stage metrics include derived throughput fields for the current bottlenecks: audio extraction writes `audio_seconds_per_second`, frame extraction writes `frames_per_second`, `run_florence_frame_analysis` writes `inferences_per_second`, `run_faster_whisper_asr` writes `real_time_factor` and `audio_seconds_per_second`, `run_databricks_scene_reasoning` writes `scenes_per_second`, and Neo4j graph stages write `upserts_per_second`. Use these metrics to compare optimization runs before changing cluster size, ASR presets, model providers or Neo4j projection strategy.

```sql
SELECT
  media_id,
  dispatch_id,
  stage,
  try_cast(get_json_object(metrics, '$.elapsed_seconds') AS DOUBLE) AS elapsed_seconds,
  try_cast(get_json_object(metrics, '$.real_time_factor') AS DOUBLE) AS asr_real_time_factor,
  try_cast(get_json_object(metrics, '$.audio_seconds_per_second') AS DOUBLE) AS audio_seconds_per_second,
  try_cast(get_json_object(metrics, '$.frames_per_second') AS DOUBLE) AS frames_per_second,
  try_cast(get_json_object(metrics, '$.inferences_per_second') AS DOUBLE) AS model_inferences_per_second,
  try_cast(get_json_object(metrics, '$.scenes_per_second') AS DOUBLE) AS scenes_per_second,
  try_cast(get_json_object(metrics, '$.upserts_per_second') AS DOUBLE) AS neo4j_upserts_per_second,
  try_cast(get_json_object(metrics, '$.skipped') AS BOOLEAN) AS skipped,
  get_json_object(metrics, '$.skipped_reason') AS skipped_reason,
  completed_at
FROM ${catalog}.${schema}.video_job_stage_runs
WHERE status = 'completed'
  AND stage IN (
    'extract_audio_assets',
    'extract_frame_assets',
    'run_florence_frame_analysis',
    'run_faster_whisper_asr',
    'run_databricks_scene_reasoning',
    'build_graph_upserts',
    'project_neo4j_graph'
  )
  AND completed_at >= current_timestamp() - INTERVAL 30 DAYS
ORDER BY completed_at DESC;
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

### Legacy AI Batch, tokens and cost inputs

The active Florence + Gemma 3 DAG no longer runs Azure OpenAI Batch stages. The legacy `video_ai_results` and `video_ai_batches` tables may still contain rows from historical runs or ad hoc notebook stages; calculate any legacy Batch cost outside the notebook from the deployed Azure OpenAI price sheet for each `model_name` and do not hard-code prices in the pipeline.

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

Use these checks to compare Databricks output quality across presets and against archived baseline runs from the retired local-processing path. Low transcript coverage can indicate missing audio, ASR chunking issues or an overly strict quality gate. Very low scene density can indicate sparse frame sampling or transcript gaps that are too large for the content.

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

`video_graph_upserts` is the durable queue for Neo4j serving projection. The projector groups compatible node and relationship intents into Cypher `UNWIND` batches by label/type and falls back to row-by-row projection only when a batch group fails, so failed rows still get precise `error` details. If rows fail, fix Neo4j deployment settings or data validation first, then rerun `project_neo4j_graph` or the full job. Rows already marked `applied` are preserved when the same source hash is replayed.

Use the stage metrics first to distinguish expected skips from configuration errors and actual projection failures:

```sql
SELECT
  media_id,
  dispatch_id,
  status,
  message,
  try_cast(get_json_object(metrics, '$.skipped') AS BOOLEAN) AS skipped,
  get_json_object(metrics, '$.skipped_reason') AS skipped_reason,
  try_cast(get_json_object(metrics, '$.neo4j_required') AS BOOLEAN) AS neo4j_required,
  try_cast(get_json_object(metrics, '$.neo4j_uri_configured') AS BOOLEAN) AS neo4j_uri_configured,
  try_cast(get_json_object(metrics, '$.neo4j_password_configured') AS BOOLEAN) AS neo4j_password_configured,
  try_cast(get_json_object(metrics, '$.applied_count') AS BIGINT) AS applied_count,
  try_cast(get_json_object(metrics, '$.failed_count') AS BIGINT) AS failed_count,
  try_cast(get_json_object(metrics, '$.batch_group_count') AS BIGINT) AS batch_group_count,
  try_cast(get_json_object(metrics, '$.fallback_row_count') AS BIGINT) AS fallback_row_count,
  try_cast(get_json_object(metrics, '$.upserts_per_second') AS DOUBLE) AS upserts_per_second,
  error,
  completed_at
FROM ${catalog}.${schema}.video_job_stage_runs
WHERE stage = 'project_neo4j_graph'
ORDER BY coalesce(completed_at, started_at) DESC;
```

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
3. For Florence or Gemma 3 failures, inspect `video_model_inference_runs`, `video_frame_analysis`, `video_scene_visual_analysis` and the failed `video_job_stage_runs.metrics`; keep CPU defaults bounded until GPU quota is available.
4. For outbox projector backlog, validate the Function timer trigger, SQL warehouse ID, Databricks permissions and PostgreSQL connectivity before editing `consumed_at`.
5. For Neo4j projection failures, inspect `video_graph_upserts.error`, validate `NEO4J_URI`, `NEO4J_PASSWORD_SECRET_SCOPE`/`NEO4J_PASSWORD_SECRET_KEY`, host allowlist and database permissions, then rerun `project_neo4j_graph`.
6. For product parity analysis, export the Gold row from `video_processing_results.processing_result_json` and compare it with archived baseline output for transcript coverage, scene/chapter count, frame descriptions, graph upsert completeness, total tokens and wall-clock duration.

## Parity and rollout validation

Databricks is the active processing path. Use this section for regression validation against archived baseline outputs and for promoting bundle changes safely between environments. Reuse the same uploaded videos and comparable processing presets where possible, but keep separate `dispatch_id` values so Delta, PostgreSQL and Neo4j records stay traceable.

Recommended shadow dataset:

| Case | Purpose |
|---|---|
| Short spoken video | Fast end-to-end smoke test for transcript, frames, Gold result and outbox projection. |
| Silent or music-only video | Verifies audio-less quality gates, explicit ASR skip and frame-only understanding. |
| Long meeting or lecture | Exercises ASR chunk coverage, retries, token volume and scene/window density. |
| Screen recording or slides | Checks OCR-like frame descriptions, chapter quality and graph entities. |
| Low-quality or unusual codec sample | Validates quarantine behavior and source quality diagnostics before inference spend. |

Run the comparison in this order:

1. Select an archived baseline output or a previously accepted Databricks Gold result for each sample.
2. Process the same sample through Databricks with equivalent `preset`, `max_frames`, `custom_prompt`, `index_graph` and model configuration.
3. Confirm Databricks emits terminal `video_pipeline_outbox` rows and the bridge projects them to PostgreSQL without manual edits.
4. Compare `video_processing_results.processing_result_json` against the accepted baseline for required frontend fields: `structure`, `audio_data`, `frames_data`, `video_metadata` and `processing_stats`.
5. Compare quality and completeness using the monitoring queries above: transcript seconds, segment count, frame count, scene candidates, Gold scenes/chapters, graph upsert status and total token usage.
6. Record wall-clock duration from `video_processing_runs.started_at/completed_at` and stage durations from `video_job_stage_runs` so rollout decisions are based on per-stage bottlenecks, not only terminal status.

Acceptance gates before promoting bundle changes:

| Gate | Acceptance requirement |
|---|---|
| Frontend contract | PostgreSQL projection from Databricks renders the same product views without frontend changes. |
| Transcript | Videos with audio produce timestamped transcript segments unless explicitly quarantined; silent videos complete with an ASR skip rather than failing. |
| Scenes and chapters | Gold scenes/chapters are present for valid videos and include evidence references to frames or transcript segments. |
| Graph projection | When `index_graph` is enabled and Neo4j is configured, `video_graph_upserts` rows reach `applied` or expose actionable failure details. |
| Operations | Active runs, failures, outbox backlog, token usage and quality metrics are visible through Delta queries without inspecting notebook logs. |
| Replay | Rerunning the same `media_id` and `dispatch_id` does not duplicate durable records or corrupt already-applied serving projections. |
| Cost and latency | Token totals and stage durations are captured for every sample so QPrisma can choose rollout thresholds per environment. |

Roll out by environment:

1. Validate representative videos in `dev` against the acceptance gates above.
2. Promote the Asset Bundle to `prod` only after Databricks SQL warehouse access, Function bridge settings, UC volume permissions, Florence/Gemma 3 model access and Neo4j deployment variables are verified.
3. Keep `PROCESSING_BACKEND=servicebus` or `databricks`, monitor outbox backlog and failure/quarantine rate, then expand usage.
4. Preserve archived baseline artifacts for regression analysis; do not reintroduce local worker-only artifacts into product surfaces.

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

Large-file staging decision: keep Function-based Files API staging as the dev/pilot path only. It is acceptable for short smoke videos and the current Blob/non-HNS upload account, but it should not be treated as the production large-video transfer path because it couples Service Bus locks, Function timeout/memory and Databricks Files API throughput to the full media payload. For production-sized uploads, prefer one of these handoff patterns before raising concurrency or file-size limits:

1. Store uploads in an HNS-enabled ADLS Gen2 account registered as a Unity Catalog external location, then pass `abfss_uri`/`uri` for Databricks to read directly with workspace-managed identity.
2. Keep the current upload account but move bulk copy into Databricks job-controlled code that reads the cloud URI and writes the UC volume from cluster compute, leaving the Function bridge responsible only for validation, idempotency and `jobs/run-now`.

Until one of those paths is deployed, cap smoke inputs conservatively and keep `volume_path` as the canonical post-staging contract from the bridge to the bundle.

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

For the pilot, the Databricks job validates access to the original media, records operational events, persists manifests/stage runs/audio/frame/transcript/request/batch/result/Gold/graph/quarantine records and publishes frontend-compatible progress/failure/completion records. The DAG now exposes the planned production stages and operational tables so QPrisma can validate orchestration, parallel branches, frontend progress, quality metrics and replay behavior before rollout. A local processing worker is not part of the target architecture for this pipeline.
