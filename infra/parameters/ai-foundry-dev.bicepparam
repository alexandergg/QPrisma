using '../modules/ai-foundry.bicep'

param name = 'aif-qprisma-dev'
param location = 'swedencentral'
param deployBatchModel = true

// storageAccountId and storageAccountName are passed from the workflow
// after resolving the existing storage account.
