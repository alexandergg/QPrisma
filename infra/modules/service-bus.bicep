@description('Service Bus namespace name')
param namespaceName string

@description('Video processing queue name')
param queueName string = 'video-processing'

@description('Location for resources')
param location string = resourceGroup().location

@description('Service Bus SKU')
@allowed([
  'Standard'
  'Premium'
])
param skuName string = 'Standard'

@description('Namespace public network access for the dev pilot')
@allowed([
  'Enabled'
  'Disabled'
])
param publicNetworkAccess string = 'Enabled'

@description('Principal IDs that can send video processing messages')
param dataSenderPrincipalIds array = []

@description('Principal IDs that can receive video processing messages')
param dataReceiverPrincipalIds array = []

@description('Resource tags')
param tags object = {}

var serviceBusDataSenderRoleId = '69a216fc-b8fb-44d8-bc22-1f3c2cd27a39'
var serviceBusDataReceiverRoleId = '4f6d3b9b-027b-4f4c-9142-0e5a2a2247e0'

resource serviceBusNamespace 'Microsoft.ServiceBus/namespaces@2024-01-01' = {
  name: namespaceName
  location: location
  tags: tags
  sku: {
    name: skuName
    tier: skuName
  }
  properties: {
    disableLocalAuth: true
    minimumTlsVersion: '1.2'
    publicNetworkAccess: publicNetworkAccess
  }
}

resource videoQueue 'Microsoft.ServiceBus/namespaces/queues@2024-01-01' = {
  parent: serviceBusNamespace
  name: queueName
  properties: {
    defaultMessageTimeToLive: 'P14D'
    duplicateDetectionHistoryTimeWindow: 'PT10M'
    deadLetteringOnMessageExpiration: true
    lockDuration: 'PT5M'
    maxDeliveryCount: 10
    requiresDuplicateDetection: true
  }
}

resource senderAssignments 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for principalId in dataSenderPrincipalIds: {
  name: guid(serviceBusNamespace.id, principalId, serviceBusDataSenderRoleId)
  scope: serviceBusNamespace
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', serviceBusDataSenderRoleId)
    principalId: principalId
    principalType: 'ServicePrincipal'
  }
}]

resource receiverAssignments 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for principalId in dataReceiverPrincipalIds: {
  name: guid(serviceBusNamespace.id, principalId, serviceBusDataReceiverRoleId)
  scope: serviceBusNamespace
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', serviceBusDataReceiverRoleId)
    principalId: principalId
    principalType: 'ServicePrincipal'
  }
}]

output namespaceId string = serviceBusNamespace.id
output namespaceName string = serviceBusNamespace.name
output fullyQualifiedNamespace string = '${serviceBusNamespace.name}.servicebus.windows.net'
output queueName string = videoQueue.name
