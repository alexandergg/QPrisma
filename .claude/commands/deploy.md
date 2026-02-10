# Deploy QPrisma

Guide for deploying QPrisma to different environments.

## Usage
```
/deploy [--env development|staging|production] [--service api|frontend|worker|all]
```

## Deployment Options

### Local Development (Docker Compose)

```bash
# Infrastructure only (recommended for local dev)
docker-compose up -d redis postgres neo4j

# With Celery worker
docker-compose --profile worker up -d

# Full stack
docker-compose --profile full up -d

# With debug tools (pgAdmin, Redis Commander)
docker-compose --profile full --profile debug up -d
```

### Azure Container Apps (Recommended for MVP)

#### 1. Prerequisites

```bash
# Install Azure CLI
az login
az account set --subscription <subscription-id>

# Create resource group
az group create --name qprisma-rg --location westeurope
```

#### 2. Create Container Registry

```bash
# Create ACR
az acr create --resource-group qprisma-rg \
  --name qprismaregistry --sku Basic

# Login to ACR
az acr login --name qprismaregistry
```

#### 3. Build and Push Images

```bash
# Backend API
cd backend
docker build -t qprismaregistry.azurecr.io/qprisma-api:latest .
docker push qprismaregistry.azurecr.io/qprisma-api:latest

# Celery Worker
docker build -t qprismaregistry.azurecr.io/qprisma-worker:latest -f Dockerfile.worker .
docker push qprismaregistry.azurecr.io/qprisma-worker:latest

# Frontend
cd ../frontend
docker build -t qprismaregistry.azurecr.io/qprisma-frontend:latest .
docker push qprismaregistry.azurecr.io/qprisma-frontend:latest
```

#### 4. Create Container Apps Environment

```bash
# Create environment
az containerapp env create \
  --name qprisma-env \
  --resource-group qprisma-rg \
  --location westeurope

# Create API app
az containerapp create \
  --name qprisma-api \
  --resource-group qprisma-rg \
  --environment qprisma-env \
  --image qprismaregistry.azurecr.io/qprisma-api:latest \
  --target-port 8000 \
  --ingress external \
  --registry-server qprismaregistry.azurecr.io \
  --env-vars-file ./env-vars.txt \
  --cpu 1 --memory 2Gi \
  --min-replicas 1 --max-replicas 5

# Create frontend app
az containerapp create \
  --name qprisma-frontend \
  --resource-group qprisma-rg \
  --environment qprisma-env \
  --image qprismaregistry.azurecr.io/qprisma-frontend:latest \
  --target-port 3000 \
  --ingress external \
  --registry-server qprismaregistry.azurecr.io \
  --env-vars NEXT_PUBLIC_API_URL=https://qprisma-api.<region>.azurecontainerapps.io \
  --cpu 0.5 --memory 1Gi
```

### Azure Kubernetes Service (Production)

#### 1. Create AKS Cluster

```bash
az aks create \
  --resource-group qprisma-rg \
  --name qprisma-aks \
  --node-count 3 \
  --enable-addons monitoring \
  --generate-ssh-keys

# Get credentials
az aks get-credentials --resource-group qprisma-rg --name qprisma-aks
```

#### 2. Deploy with Kubernetes Manifests

```yaml
# k8s/api-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: qprisma-api
spec:
  replicas: 3
  selector:
    matchLabels:
      app: qprisma-api
  template:
    metadata:
      labels:
        app: qprisma-api
    spec:
      containers:
      - name: api
        image: qprismaregistry.azurecr.io/qprisma-api:latest
        ports:
        - containerPort: 8000
        envFrom:
        - secretRef:
            name: qprisma-secrets
        resources:
          requests:
            memory: "1Gi"
            cpu: "500m"
          limits:
            memory: "2Gi"
            cpu: "1000m"
        livenessProbe:
          httpGet:
            path: /health
            port: 8000
          initialDelaySeconds: 10
          periodSeconds: 30
        readinessProbe:
          httpGet:
            path: /health
            port: 8000
          initialDelaySeconds: 5
          periodSeconds: 10
---
apiVersion: v1
kind: Service
metadata:
  name: qprisma-api
spec:
  selector:
    app: qprisma-api
  ports:
  - port: 80
    targetPort: 8000
  type: ClusterIP
```

```bash
# Apply manifests
kubectl apply -f k8s/

# Check status
kubectl get pods
kubectl get services
```

## Environment Variables

Create secrets for each environment:

```bash
# Create Kubernetes secret
kubectl create secret generic qprisma-secrets \
  --from-literal=AZURE_OPENAI_ENDPOINT=https://... \
  --from-literal=AZURE_OPENAI_API_KEY=... \
  --from-literal=DATABASE_URL=postgresql://... \
  --from-literal=NEO4J_URI=bolt://... \
  --from-literal=REDIS_URL=redis://...
```

## CI/CD Pipeline (GitHub Actions)

```yaml
# .github/workflows/deploy.yml
name: Deploy QPrisma

on:
  push:
    branches: [main]

jobs:
  build-and-deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Login to Azure
        uses: azure/login@v1
        with:
          creds: ${{ secrets.AZURE_CREDENTIALS }}

      - name: Login to ACR
        run: az acr login --name qprismaregistry

      - name: Build and push API
        run: |
          cd backend
          docker build -t qprismaregistry.azurecr.io/qprisma-api:${{ github.sha }} .
          docker push qprismaregistry.azurecr.io/qprisma-api:${{ github.sha }}

      - name: Deploy to Container Apps
        run: |
          az containerapp update \
            --name qprisma-api \
            --resource-group qprisma-rg \
            --image qprismaregistry.azurecr.io/qprisma-api:${{ github.sha }}
```

## Health Checks

```bash
# API health
curl https://qprisma-api.azurecontainerapps.io/health

# Expected response
{
  "status": "healthy",
  "services": {
    "database": "connected",
    "neo4j": "connected",
    "redis": "connected",
    "azure_openai": "configured"
  }
}
```

## Scaling

```bash
# Container Apps
az containerapp update \
  --name qprisma-api \
  --resource-group qprisma-rg \
  --min-replicas 2 \
  --max-replicas 10

# AKS
kubectl scale deployment qprisma-api --replicas=5
```

## Rollback

```bash
# Container Apps - use revision
az containerapp revision list --name qprisma-api --resource-group qprisma-rg
az containerapp revision activate --name <revision-name> --resource-group qprisma-rg

# AKS
kubectl rollout undo deployment/qprisma-api
kubectl rollout status deployment/qprisma-api
```

## Monitoring

```bash
# Container Apps logs
az containerapp logs show --name qprisma-api --resource-group qprisma-rg

# AKS logs
kubectl logs -f deployment/qprisma-api
```

## Checklist

### Pre-Deployment
- [ ] Environment variables configured
- [ ] Azure resources provisioned
- [ ] Database migrations applied
- [ ] Neo4j indexes created
- [ ] SSL certificates configured

### Post-Deployment
- [ ] Health check passing
- [ ] API docs accessible
- [ ] Frontend loading
- [ ] WebSocket connections working
- [ ] Monitoring configured
