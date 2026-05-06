@description('Azure AI Foundry resource name')
param name string

@description('Location for resources')
param location string = resourceGroup().location

@description('Deploy batch model (gpt-5.1-batch)')
param deployBatchModel bool = true

@description('Storage account resource ID for agents capability host')
param storageAccountId string = ''

@description('Storage account name for agents connection')
param storageAccountName string = ''

@description('Application Insights resource ID for tracing connection')
param appInsightsId string = ''

@description('Application Insights connection string (target for Foundry tracing connection)')
@secure()
param appInsightsConnectionString string = ''

@description('Application Insights instrumentation key (credential for Foundry tracing connection)')
@secure()
param appInsightsInstrumentationKey string = ''

@description('Log Analytics Workspace resource ID for diagnostic settings')
param logAnalyticsWorkspaceId string = ''

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

// GPT-5.5 — GlobalStandard, max 160K TPM
resource gpt55Deployment 'Microsoft.CognitiveServices/accounts/deployments@2025-06-01' = {
  parent: aiFoundry
  name: 'gpt-5.5'
  sku: {
    name: 'GlobalStandard'
    capacity: 160
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: 'gpt-5.5'
      version: '2026-04-24'
    }
    versionUpgradeOption: 'OnceNewDefaultVersionAvailable'
  }
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
    gpt55Deployment
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

// GPT-5.1 Batch — GlobalBatch, max 200M enqueued tokens
resource gpt51BatchDeployment 'Microsoft.CognitiveServices/accounts/deployments@2025-06-01' = if (deployBatchModel) {
  parent: aiFoundry
  name: 'gpt-5.1-batch'
  sku: {
    name: 'GlobalBatch'
    capacity: 200
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: 'gpt-5.1'
      version: '2025-11-13'
    }
    versionUpgradeOption: 'OnceNewDefaultVersionAvailable'
  }
  dependsOn: [
    whisperDeployment
  ]
}

// Reference to existing storage account for agents (when provided)
resource existingAgentStorage 'Microsoft.Storage/storageAccounts@2023-05-01' existing = if (!empty(storageAccountName)) {
  name: storageAccountName
}

// Storage connection for agents (required by capability host)
resource agentStorageConnection 'Microsoft.CognitiveServices/accounts/connections@2025-06-01' = if (!empty(storageAccountId)) {
  parent: aiFoundry
  name: 'agents-storage'
  properties: {
    authType: 'AAD'
    category: 'AzureBlob'
    target: 'https://${storageAccountName}.blob.${az.environment().suffixes.storage}'
    isSharedToAll: true
    metadata: {
      ResourceId: storageAccountId
      AccountName: storageAccountName
      ContainerName: 'agents'
    }
  }
}

// RBAC — Storage Blob Data Contributor for AI Foundry managed identity
var storageBlobDataContributorRole = 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
var cognitiveServicesOpenAiUserRole = '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd'

resource storageRoleAiFoundry 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(storageAccountId)) {
  name: guid(storageAccountId, aiFoundry.id, storageBlobDataContributorRole)
  scope: existingAgentStorage
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageBlobDataContributorRole)
    principalId: aiFoundry.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

// RBAC — Storage Blob Data Contributor for project managed identity
resource storageRoleProject 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(storageAccountId)) {
  name: guid(storageAccountId, aiProject.id, storageBlobDataContributorRole)
  scope: existingAgentStorage
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageBlobDataContributorRole)
    principalId: aiProject.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

// RBAC — Azure OpenAI data-plane access for hosted agent execution identities.
// Hosted containers run under Foundry-managed identities, so app-level grants are not enough.
resource openAiRoleAiFoundry 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(aiFoundry.id, aiFoundry.id, cognitiveServicesOpenAiUserRole)
  scope: aiFoundry
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', cognitiveServicesOpenAiUserRole)
    principalId: aiFoundry.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

resource openAiRoleProject 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(aiFoundry.id, aiProject.id, cognitiveServicesOpenAiUserRole)
  scope: aiFoundry
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', cognitiveServicesOpenAiUserRole)
    principalId: aiProject.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

// AcrPull role assignments are managed via CLI in deploy-hosted-agent.yml
// (Bicep role assignments fail with RoleDefinitionDoesNotExist due to ARM scope resolution)

// Note: The `agents-host` capability host (capabilityHostKind=Agents,
// enablePublicHostingEnvironment=true) is no longer provisioned. The refreshed
// Foundry hosted agent preview manages its own execution sandbox per agent
// version and does not require an account-level capability host. The legacy
// host caused `instance_identity.principal_id` to be returned empty after long
// polling because the platform was provisioning identities against the new
// per-agent sandbox while the capability host blocked materialization.

// =====================================================================
// Application Insights connection (enables Foundry portal tracing)
// =====================================================================

resource appInsightsConnection 'Microsoft.CognitiveServices/accounts/connections@2025-06-01' = if (!empty(appInsightsId) && !empty(appInsightsConnectionString) && !empty(appInsightsInstrumentationKey)) {
  parent: aiFoundry
  name: 'appinsights'
  properties: {
    authType: 'ApiKey'
    category: 'AppInsights'
    target: appInsightsConnectionString
    isSharedToAll: true
    credentials: {
      key: appInsightsInstrumentationKey
    }
    metadata: {
      ResourceId: appInsightsId
    }
  }
}

// =====================================================================
// Diagnostic settings (route AI Foundry platform logs/metrics)
// =====================================================================

resource aiFoundryDiagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = if (!empty(logAnalyticsWorkspaceId)) {
  name: 'ai-foundry-diagnostics'
  scope: aiFoundry
  properties: {
    workspaceId: logAnalyticsWorkspaceId
    metrics: [
      {
        category: 'AllMetrics'
        enabled: true
      }
    ]
    logs: [
      {
        category: 'RequestResponse'
        enabled: true
      }
      {
        category: 'Audit'
        enabled: true
      }
    ]
  }
}

output endpoint string = aiFoundry.properties.endpoint
output id string = aiFoundry.id
output name string = aiFoundry.name
output projectName string = aiProject.name
output projectEndpoint string = 'https://${name}.services.ai.azure.com/api/projects/${aiProject.name}'
output projectPrincipalId string = aiProject.identity.principalId
