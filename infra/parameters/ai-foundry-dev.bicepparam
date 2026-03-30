using '../modules/ai-foundry.bicep'

param name = 'aif-qprisma-dev'
param location = 'westeurope'
param deployBatchModel = true

// storageAccountId is resolved and passed by deploy-ai-foundry.yml workflow
// to enable the agents capability host provisioning.
