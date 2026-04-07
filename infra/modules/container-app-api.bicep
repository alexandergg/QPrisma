@description('Container App name')
param name string

@description('Location for resources')
param location string = resourceGroup().location

@description('Container Apps Environment ID')
param environmentId string

@description('Container image name')
param imageName string

@description('Ingress target port')
param targetPort int = 8000

@description('Enable health probes (disable for placeholder images that do not expose /health)')
param enableProbes bool = true

@description('Container Registry server')
param registryServer string

@description('User-assigned managed identity resource ID for ACR pulls and Key Vault secret refs')
param runtimeIdentityResourceId string

@description('Environment variables (plain values only: {name, value})')
param envVars array = []

@description('Secrets for the container app ({name, value} or {name, keyVaultUrl, identity})')
param secrets array = []

@description('Environment variables that reference secrets ({name, secretRef} pairs)')
param secretEnvVars array = []

@description('Resource tags')
param tags object = {}

resource apiContainerApp 'Microsoft.App/containerApps@2024-03-01' = {
  name: name
  location: location
  tags: tags
  identity: {
    type: 'SystemAssigned,UserAssigned'
    userAssignedIdentities: {
      '${runtimeIdentityResourceId}': {}
    }
  }
  properties: {
    environmentId: environmentId
    configuration: {
      ingress: {
        external: true
        targetPort: targetPort
        transport: 'auto'
        allowInsecure: false
      }
      registries: [
        {
          server: registryServer
          identity: runtimeIdentityResourceId
        }
      ]
      secrets: secrets
    }
    template: {
      containers: [
        {
          name: 'api'
          image: imageName
          resources: {
            cpu: json('0.5')
            memory: '1Gi'
          }
          env: union(envVars, secretEnvVars)
          probes: enableProbes ? [
            {
              type: 'Startup'
              httpGet: {
                path: '/'
                port: targetPort
                scheme: 'HTTP'
              }
              periodSeconds: 10
              failureThreshold: 10
            }
            {
              type: 'Liveness'
              httpGet: {
                path: '/health'
                port: targetPort
                scheme: 'HTTP'
              }
              periodSeconds: 30
              failureThreshold: 3
            }
            {
              type: 'Readiness'
              httpGet: {
                path: '/health'
                port: targetPort
                scheme: 'HTTP'
              }
              periodSeconds: 10
              failureThreshold: 3
            }
          ] : []
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
                concurrentRequests: '10'
              }
            }
          }
        ]
      }
    }
  }
}

output fqdn string = apiContainerApp.properties.configuration.ingress.fqdn
output id string = apiContainerApp.id
output name string = apiContainerApp.name
output principalId string = apiContainerApp.identity.principalId
