using '../modules/ai-foundry.bicep'

param name = 'aif-qprisma-dev'
param location = 'swedencentral'
param deployBatchModel = true
// appInsightsId and logAnalyticsWorkspaceId are passed dynamically
// from the deploy-ai-foundry.yml workflow
