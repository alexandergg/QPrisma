using '../main.bicep'

param environment = 'dev'
param dbAdminLogin = 'qprismaadmin'
param dbAdminPassword = readEnvironmentVariable('DB_ADMIN_PASSWORD', '')
param neo4jPassword = readEnvironmentVariable('NEO4J_PASSWORD', '')
param neo4jUri = readEnvironmentVariable('NEO4J_URI', '')
param jwtSecretKey = readEnvironmentVariable('JWT_SECRET_KEY', '')
param benchmarkApiToken = readEnvironmentVariable('BENCHMARK_API_TOKEN', '')
param entraAuthTenantId = readEnvironmentVariable('ENTRA_TENANT_ID', '')
param entraAuthClientId = readEnvironmentVariable('ENTRA_CLIENT_ID', '')
param entraAuthApiScope = readEnvironmentVariable('ENTRA_API_SCOPE', '')
param enableDatabricksPilot = true
param databricksSkuName = 'premium'
param databricksVideoJobId = readEnvironmentVariable('DATABRICKS_VIDEO_JOB_ID', '')
param databricksSqlWarehouseId = readEnvironmentVariable('DATABRICKS_SQL_WAREHOUSE_ID', '')
param databricksOutboxCatalog = readEnvironmentVariable('DATABRICKS_OUTBOX_CATALOG', 'qprisma_dev')
param databricksOutboxSchema = readEnvironmentVariable('DATABRICKS_OUTBOX_SCHEMA', 'video')
param databricksOutboxTable = readEnvironmentVariable('DATABRICKS_OUTBOX_TABLE', 'video_pipeline_outbox')
param databricksOutboxPollBatchSize = int(readEnvironmentVariable('DATABRICKS_OUTBOX_POLL_BATCH_SIZE', '25'))
param databricksOutboxPollSchedule = readEnvironmentVariable('DATABRICKS_OUTBOX_POLL_SCHEDULE', '0 */5 * * * *')
param processingBackend = 'celery'
param videoProcessingQueueName = 'video-processing'
param enableDatabricksDispatchBridge = true
param databricksBridgeAuthType = readEnvironmentVariable('DATABRICKS_BRIDGE_AUTH_TYPE', 'oauth_m2m')
param databricksBridgeClientId = readEnvironmentVariable('DATABRICKS_BRIDGE_CLIENT_ID', '')
param databricksBridgeClientSecret = readEnvironmentVariable('DATABRICKS_BRIDGE_CLIENT_SECRET', '')
param databricksBridgeToken = readEnvironmentVariable('DATABRICKS_BRIDGE_TOKEN', '')
