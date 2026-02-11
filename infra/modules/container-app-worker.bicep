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

@description('Redis host for KEDA scaler')
param redisHost string

@description('Environment variables (plain values only: {name, value})')
param envVars array = []

@description('Secrets for the container app ({name, value} pairs)')
param secrets array = []

@description('Environment variables that reference secrets ({name, secretRef} pairs)')
param secretEnvVars array = []

@description('Resource tags')
param tags object = {}

resource workerContainerApp 'Microsoft.App/containerApps@2024-03-01' = {
  name: name
  location: location
  tags: tags
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    environmentId: environmentId
    configuration: {
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
          name: 'worker'
          image: imageName
          resources: {
            cpu: json('1.0')
            memory: '2Gi'
          }
          env: union(envVars, secretEnvVars)
        }
      ]
      terminationGracePeriodSeconds: 600
      scale: {
        minReplicas: 1
        maxReplicas: 3
        rules: [
          {
            name: 'redis-queue-scaler'
            custom: {
              type: 'redis'
              metadata: {
                address: redisHost
                listName: 'celery'
                listLength: '5'
              }
            }
          }
        ]
      }
    }
  }
}

output id string = workerContainerApp.id
output name string = workerContainerApp.name
output principalId string = workerContainerApp.identity.principalId
