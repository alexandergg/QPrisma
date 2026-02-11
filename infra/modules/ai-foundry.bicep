@description('Azure AI Foundry resource name')
param name string

@description('Location for resources')
param location string = resourceGroup().location

@description('Deploy batch model (gpt-4o-batch)')
param deployBatchModel bool = true

@description('Resource tags')
param tags object = {}

// AI Foundry resource (AIServices with project management)
resource aiFoundry 'Microsoft.CognitiveServices/accounts@2025-06-01' = {
  name: name
  location: location
  tags: tags
  identity: {
    type: 'SystemAssigned'
  }
  kind: 'AIServices'
  sku: {
    name: 'S0'
  }
  properties: {
    allowProjectManagement: true
    customSubDomainName: name
    publicNetworkAccess: 'Enabled'
    disableLocalAuth: false
    networkAcls: {
      defaultAction: 'Allow'
    }
  }
}

// Default project
resource aiProject 'Microsoft.CognitiveServices/accounts/projects@2025-06-01' = {
  name: '${name}-project'
  parent: aiFoundry
  location: location
  identity: {
    type: 'SystemAssigned'
  }
  properties: {}
}

// GPT-4o — GlobalStandard, default max 450K TPM
resource gpt4oDeployment 'Microsoft.CognitiveServices/accounts/deployments@2025-06-01' = {
  parent: aiFoundry
  name: 'gpt-4o'
  sku: {
    name: 'GlobalStandard'
    capacity: 450
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: 'gpt-4o'
      version: '2024-11-20'
    }
    versionUpgradeOption: 'OnceNewDefaultVersionAvailable'
  }
}

// GPT-5.2-chat — GlobalStandard, default max 1M TPM
resource gpt52chatDeployment 'Microsoft.CognitiveServices/accounts/deployments@2025-06-01' = {
  parent: aiFoundry
  name: 'gpt-5.2-chat'
  sku: {
    name: 'GlobalStandard'
    capacity: 1000
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: 'gpt-5.2-chat'
      version: '2025-12-11'
    }
    versionUpgradeOption: 'OnceNewDefaultVersionAvailable'
  }
  dependsOn: [
    gpt4oDeployment
  ]
}

// text-embedding-3-large — GlobalStandard, default max 350K TPM
resource embeddingDeployment 'Microsoft.CognitiveServices/accounts/deployments@2025-06-01' = {
  parent: aiFoundry
  name: 'text-embedding-3-large'
  sku: {
    name: 'GlobalStandard'
    capacity: 350
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: 'text-embedding-3-large'
      version: '1'
    }
    versionUpgradeOption: 'OnceNewDefaultVersionAvailable'
  }
  dependsOn: [
    gpt52chatDeployment
  ]
}

// Whisper — Standard, max 3 RPM
resource whisperDeployment 'Microsoft.CognitiveServices/accounts/deployments@2025-06-01' = {
  parent: aiFoundry
  name: 'whisper'
  sku: {
    name: 'Standard'
    capacity: 3
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: 'whisper'
      version: '001'
    }
    versionUpgradeOption: 'OnceNewDefaultVersionAvailable'
  }
  dependsOn: [
    embeddingDeployment
  ]
}

// GPT-4o Batch — GlobalBatch, 200M enqueued tokens
resource gpt4oBatchDeployment 'Microsoft.CognitiveServices/accounts/deployments@2025-06-01' = if (deployBatchModel) {
  parent: aiFoundry
  name: 'gpt-4o-batch'
  sku: {
    name: 'GlobalBatch'
    capacity: 200
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: 'gpt-4o'
      version: '2024-11-20'
    }
    versionUpgradeOption: 'OnceNewDefaultVersionAvailable'
  }
  dependsOn: [
    whisperDeployment
  ]
}

output endpoint string = aiFoundry.properties.endpoint
output id string = aiFoundry.id
output name string = aiFoundry.name
