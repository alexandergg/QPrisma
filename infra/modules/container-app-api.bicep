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

@description('Environment variables (plain values only: {name, value})')
param envVars array = []

@description('Secrets for the container app ({name, value} pairs)')
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
    type: 'SystemAssigned'
  }
  properties: {
    environmentId: environmentId
    configuration: {
      ingress: {
        external: true
        targetPort: 8000
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
      secrets: union(
        [{ name: 'registry-password', value: registryPassword }],
        secrets
      )
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
          probes: [
            {
              type: 'Startup'
              httpGet: {
                path: '/'
                port: 8000
                scheme: 'HTTP'
              }
              periodSeconds: 10
              failureThreshold: 10
            }
            {
              type: 'Liveness'
              httpGet: {
                path: '/health'
                port: 8000
                scheme: 'HTTP'
              }
              periodSeconds: 30
              failureThreshold: 3
            }
            {
              type: 'Readiness'
              httpGet: {
                path: '/health'
                port: 8000
                scheme: 'HTTP'
              }
              periodSeconds: 10
              failureThreshold: 3
            }
          ]
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
