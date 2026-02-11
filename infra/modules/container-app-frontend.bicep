@description('Container App name')
param name string

@description('Location for resources')
param location string = resourceGroup().location

@description('Container Apps Environment ID')
param environmentId string

@description('Container image name')
param imageName string

@description('Container Registry server')
param registryServer string

@description('Container Registry username')
param registryUsername string

@description('Container Registry password')
@secure()
param registryPassword string

@description('Environment variables')
param envVars array = []

@description('Resource tags')
param tags object = {}

resource frontendContainerApp 'Microsoft.App/containerApps@2024-03-01' = {
  name: name
  location: location
  tags: tags
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    environmentId: environmentId
    configuration: {
      ingress: {
        external: true
        targetPort: 3000
        transport: 'auto'
        allowInsecure: false
      }
      registries: [
        {
          server: registryServer
          username: registryUsername
          passwordSecretRef: 'registry-password'
        }
      ]
      secrets: [
        {
          name: 'registry-password'
          value: registryPassword
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'frontend'
          image: imageName
          resources: {
            cpu: json('0.25')
            memory: '0.5Gi'
          }
          env: envVars
        }
      ]
      scale: {
        minReplicas: 1
        maxReplicas: 2
        rules: [
          {
            name: 'http-scaling'
            http: {
              metadata: {
                concurrentRequests: '20'
              }
            }
          }
        ]
      }
    }
  }
}

output fqdn string = frontendContainerApp.properties.configuration.ingress.fqdn
output id string = frontendContainerApp.id
output name string = frontendContainerApp.name
output principalId string = frontendContainerApp.identity.principalId
