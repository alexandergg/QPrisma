# QPrisma Databricks video pipeline

This folder contains the initial Databricks Asset Bundle for the QPrisma video-processing pilot.

The Azure resources are provisioned by Bicep under `infra\`. This bundle owns the inside-Databricks workflow shape: jobs, task graph, parameters, permissions and future Lakeflow pipeline resources.

## Current scope

- Defines a `qprisma-video-processing` workflow with `dev` and `prod` targets.
- Runs a minimal observable job with three stages: manifest registration, source-media probe and outbox/status publication.
- Establishes stable parameters for the Service Bus driven pipeline: `media_id`, `blob_name`, `dispatch_id`, `source_media`, `pipeline_config`, catalog, schema and queue name.
- Writes stage events to the Delta table `${catalog}.${schema}.video_pipeline_events`.
- Writes frontend-compatible completion/failure records to `${catalog}.${schema}.video_pipeline_outbox`; this is the durable handoff point for projecting Databricks state back into QPrisma PostgreSQL/Neo4j/Redis.

## Validate and deploy

Run these commands from this directory after installing the Databricks CLI and configuring authentication for the target workspace:

```powershell
databricks bundle validate --target dev
databricks bundle deploy --target dev
databricks bundle run video_processing --target dev
```

The bridge Function invokes this job through Databricks Jobs API `run-now` with `job_parameters`. The `source_media` parameter is a JSON object produced by QPrisma's control plane and must describe a managed-identity-readable source blob.

The local shell must be able to resolve `databricks`. If validation fails with `databricks` not found, refresh the shell/PATH or provide the explicit Databricks CLI installation path before deploying the bundle.

## Deploy the dispatch bridge

The Azure Function bridge code lives in `backend\functions\video_dispatch_bridge`. It is deployed by `.github\workflows\deploy-function-bridge.yml`, which packages that folder as the Function App root and deploys it with Azure OIDC using `az functionapp deployment source config-zip`.

The workflow runs on changes to the bridge package and can also be started manually. The default Function App name is `func-qprisma-dbx-bridge-flex-dev`; override it with the `DATABRICKS_BRIDGE_FUNCTION_APP_NAME` environment variable or the manual workflow input when needed. After a successful Flex deployment, the workflow removes the legacy Linux Consumption bridge app `func-qprisma-dbx-bridge-dev` and its `Y1` plan when they are no longer in use.

## Outbox projection back to QPrisma

Databricks writes durable status/result records to `${catalog}.${schema}.video_pipeline_outbox`. The Azure Function bridge includes a timer-triggered outbox projector that:

1. polls the table through the Databricks SQL Statement Execution API;
2. applies each event to QPrisma PostgreSQL through the same `DatabricksStatusEvent` contract used by direct status events;
3. marks the row `consumed_at = current_timestamp()` only after PostgreSQL projection succeeds.

The projector is configured by Bicep through these Function App settings:

| Setting | Purpose |
|---|---|
| `DATABRICKS_SQL_WAREHOUSE_ID` | SQL warehouse used for Statement Execution polling. If empty, polling is skipped. |
| `DATABRICKS_OUTBOX_CATALOG` | Catalog that contains the outbox table. Default: `qprisma_dev`. |
| `DATABRICKS_OUTBOX_SCHEMA` | Schema that contains the outbox table. Default: `video`. |
| `DATABRICKS_OUTBOX_TABLE` | Outbox table name. Default: `video_pipeline_outbox`. |
| `DATABRICKS_OUTBOX_POLL_BATCH_SIZE` | Maximum rows projected per timer invocation. Default: `25`. |
| `OutboxPollSchedule` | Azure Functions NCRONTAB schedule. Default dev value: `0 */5 * * * *`. |

For the pilot, the Databricks job is intentionally minimal: it validates access to the original media, records operational events and publishes completion/failure records. The production pipeline should extend it with frame/audio extraction, model calls, Delta medallion writes, data quality expectations and graph/result publication while keeping the same dispatch and outbox contracts.
