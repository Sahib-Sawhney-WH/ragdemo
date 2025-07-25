# Azure Container Instance Deployment Guide

This guide walks you through deploying the ExponentHR RAG solution to Azure Container Instances (ACI).

## Prerequisites

### 1. Install Required Tools

**Docker Desktop:**
- Download and install from [docker.com](https://www.docker.com/products/docker-desktop)
- Ensure Docker is running

**Azure CLI:**
```bash
# Windows (using winget)
winget install Microsoft.AzureCLI

# macOS (using Homebrew)
brew install azure-cli

# Linux (Ubuntu/Debian)
curl -sL https://aka.ms/InstallAzureCLI | sudo bash
```

### 2. Azure Login
```bash
az login
```

### 3. Set Your Subscription
```bash
az account list --output table
az account set --subscription "your-subscription-id"
```

## Configuration

### 1. Update Configuration File

Edit `aci_deployment_config.json` with your specific values:

```json
{
  "azure_subscription_id": "your-actual-subscription-id",
  "azure_resource_group": "exponenthr-rag-rg",
  "azure_storage_account_name": "youruniquestorageaccount",
  "azure_search_service_name": "youruniquesearchservice",
  "azure_container_registry": "youruniqueregistry",
  "openai_api_key": "your-openai-api-key",
  ...
}
```

**Important Notes:**
- Storage account names must be globally unique (3-24 lowercase letters/numbers)
- Search service names must be globally unique
- Container registry names must be globally unique (5-50 alphanumeric characters)

### 2. Required Azure Permissions

Ensure your account has these roles:
- **Contributor** (for creating resources)
- **AcrPush** (for pushing to container registry)
- **Storage Blob Data Contributor** (for blob storage access)

## Deployment Steps

### Option 1: Automated Deployment (Recommended)

Run the automated deployment script:

```bash
python deploy_aci.py --config aci_deployment_config.json
```

This will:
1. ✅ Validate prerequisites
2. ✅ Create Azure resources (Resource Group, Storage, Search, ACR)
3. ✅ Build and push Docker image
4. ✅ Deploy to Azure Container Instances
5. ✅ Configure networking and provide access URLs

### Option 2: Manual Step-by-Step Deployment

#### Step 1: Create Azure Resources

```bash
# Set variables
RESOURCE_GROUP="exponenthr-rag-rg"
LOCATION="East US"
STORAGE_ACCOUNT="youruniquestorageaccount"
SEARCH_SERVICE="youruniquesearchservice"
REGISTRY_NAME="youruniqueregistry"

# Create resource group
az group create --name $RESOURCE_GROUP --location "$LOCATION"

# Create storage account
az storage account create \
  --name $STORAGE_ACCOUNT \
  --resource-group $RESOURCE_GROUP \
  --location "$LOCATION" \
  --sku Standard_LRS

# Create search service
az search service create \
  --name $SEARCH_SERVICE \
  --resource-group $RESOURCE_GROUP \
  --location "$LOCATION" \
  --sku basic

# Create container registry
az acr create \
  --name $REGISTRY_NAME \
  --resource-group $RESOURCE_GROUP \
  --sku Basic \
  --admin-enabled true
```

#### Step 2: Build and Push Container

```bash
# Login to registry
az acr login --name $REGISTRY_NAME

# Build image
docker build -t $REGISTRY_NAME.azurecr.io/exponenthr-rag:latest .

# Push image
docker push $REGISTRY_NAME.azurecr.io/exponenthr-rag:latest
```

#### Step 3: Deploy to ACI

```bash
# Get registry credentials
ACR_USERNAME=$(az acr credential show --name $REGISTRY_NAME --query username --output tsv)
ACR_PASSWORD=$(az acr credential show --name $REGISTRY_NAME --query passwords[0].value --output tsv)

# Deploy container
az container create \
  --name exponenthr-rag-container \
  --resource-group $RESOURCE_GROUP \
  --image $REGISTRY_NAME.azurecr.io/exponenthr-rag:latest \
  --cpu 2 \
  --memory 4 \
  --registry-login-server $REGISTRY_NAME.azurecr.io \
  --registry-username $ACR_USERNAME \
  --registry-password $ACR_PASSWORD \
  --dns-name-label exponenthr-rag-container \
  --ports 5000 \
  --restart-policy Always \
  --environment-variables \
    AZURE_STORAGE_ACCOUNT_URL=https://$STORAGE_ACCOUNT.blob.core.windows.net \
    AZURE_SEARCH_ENDPOINT=https://$SEARCH_SERVICE.search.windows.net \
    AZURE_SEARCH_INDEX_NAME=exponenthr-docs \
    OPENAI_API_KEY=your-openai-api-key \
    CONTENT_CONTAINER=scraped-content \
    REQUEST_DELAY=1.0 \
    SYNC_BATCH_SIZE=20
```

## Post-Deployment

### 1. Get Container Information

```bash
# Get container details
az container show \
  --name exponenthr-rag-container \
  --resource-group exponenthr-rag-rg \
  --query "{FQDN:ipAddress.fqdn,State:instanceView.state}" \
  --output table
```

### 2. Test the Deployment

```bash
# Get the FQDN
FQDN=$(az container show --name exponenthr-rag-container --resource-group exponenthr-rag-rg --query ipAddress.fqdn --output tsv)

# Test health endpoint
curl http://$FQDN:5000/api/health

# Test system status
curl http://$FQDN:5000/api/system/status
```

### 3. Access URLs

Your deployed application will be available at:
- **Application**: `http://your-container-fqdn:5000`
- **Health Check**: `http://your-container-fqdn:5000/api/health`
- **System Status**: `http://your-container-fqdn:5000/api/system/status`
- **API Documentation**: Available through the status endpoint

## Initial Setup and Data Loading

### 1. Trigger Initial Sync

Once deployed, trigger the initial data load:

```bash
# Trigger full synchronization
curl -X POST http://$FQDN:5000/api/sync/full \
  -H "Content-Type: application/json" \
  -d '{"view_types": ["personal"]}'
```

### 2. Monitor Progress

```bash
# Check sync status
curl http://$FQDN:5000/api/sync/status
```

### 3. Test Search Functionality

```bash
# Test search
curl -X POST http://$FQDN:5000/api/search \
  -H "Content-Type: application/json" \
  -d '{"query": "direct deposit", "search_type": "hybrid"}'
```

## Connecting to Copilot Studio

### 1. Get Azure AI Search Details

```bash
# Get search service endpoint
az search service show \
  --name $SEARCH_SERVICE \
  --resource-group $RESOURCE_GROUP \
  --query hostName \
  --output tsv

# Get search service admin key
az search admin-key show \
  --service-name $SEARCH_SERVICE \
  --resource-group $RESOURCE_GROUP \
  --query primaryKey \
  --output tsv
```

### 2. Configure Copilot Studio

1. **Open Copilot Studio**
2. **Go to Knowledge Sources**
3. **Add New Source → Azure AI Search**
4. **Enter Details:**
   - **Service Endpoint**: `https://yoursearchservice.search.windows.net`
   - **Index Name**: `exponenthr-docs`
   - **API Key**: (from step 1 above)
5. **Test Connection**
6. **Save and Publish**

## Management Commands

### View Container Logs
```bash
az container logs \
  --name exponenthr-rag-container \
  --resource-group exponenthr-rag-rg \
  --tail 50
```

### Restart Container
```bash
az container restart \
  --name exponenthr-rag-container \
  --resource-group exponenthr-rag-rg
```

### Update Container (Redeploy)
```bash
# Build and push new image
docker build -t $REGISTRY_NAME.azurecr.io/exponenthr-rag:latest .
docker push $REGISTRY_NAME.azurecr.io/exponenthr-rag:latest

# Delete and recreate container
az container delete \
  --name exponenthr-rag-container \
  --resource-group exponenthr-rag-rg \
  --yes

# Redeploy with same command as before
```

### Scale Container Resources
```bash
# Delete current container
az container delete \
  --name exponenthr-rag-container \
  --resource-group exponenthr-rag-rg \
  --yes

# Recreate with different resources
az container create \
  --name exponenthr-rag-container \
  --resource-group exponenthr-rag-rg \
  --image $REGISTRY_NAME.azurecr.io/exponenthr-rag:latest \
  --cpu 4 \
  --memory 8 \
  # ... other parameters
```

### Monitor Resource Usage
```bash
# Get container metrics
az monitor metrics list \
  --resource /subscriptions/your-subscription-id/resourceGroups/exponenthr-rag-rg/providers/Microsoft.ContainerInstance/containerGroups/exponenthr-rag-container \
  --metric "CpuUsage,MemoryUsage" \
  --interval PT1M
```

## Troubleshooting

### Common Issues

#### 1. Container Won't Start
```bash
# Check container logs
az container logs --name exponenthr-rag-container --resource-group exponenthr-rag-rg

# Check container events
az container show --name exponenthr-rag-container --resource-group exponenthr-rag-rg --query instanceView.events
```

#### 2. Image Pull Errors
```bash
# Verify registry credentials
az acr credential show --name $REGISTRY_NAME

# Test registry login
az acr login --name $REGISTRY_NAME
```

#### 3. Network Connectivity Issues
```bash
# Check container IP and ports
az container show \
  --name exponenthr-rag-container \
  --resource-group exponenthr-rag-rg \
  --query ipAddress
```

#### 4. Environment Variable Issues
```bash
# Check environment variables
az container show \
  --name exponenthr-rag-container \
  --resource-group exponenthr-rag-rg \
  --query containers[0].environmentVariables
```

### Performance Optimization

#### 1. Resource Allocation
- **CPU**: Start with 2 cores, scale up if needed
- **Memory**: Start with 4GB, monitor usage
- **Storage**: Use Premium storage for better performance

#### 2. Container Optimization
- Use multi-stage Docker builds to reduce image size
- Optimize Python dependencies
- Enable container insights for monitoring

#### 3. Azure AI Search Optimization
- Use appropriate search tier (Basic → Standard → Premium)
- Configure proper indexing policies
- Monitor search unit consumption

## Cost Optimization

### 1. Container Instance Costs
- **CPU**: ~$0.0012 per vCPU per hour
- **Memory**: ~$0.00013 per GB per hour
- **Example**: 2 vCPU + 4GB = ~$0.003 per hour (~$2.16/day)

### 2. Storage Costs
- **Blob Storage**: ~$0.018 per GB per month
- **Search Service**: Basic tier ~$250/month

### 3. Cost Reduction Tips
- Use spot instances for development
- Schedule container stop/start for non-production
- Monitor and optimize resource usage
- Use Azure Cost Management alerts

## Security Considerations

### 1. Network Security
- Consider using Azure Virtual Network integration
- Implement proper firewall rules
- Use private endpoints for storage and search

### 2. Credential Management
- Store secrets in Azure Key Vault
- Use managed identities where possible
- Rotate API keys regularly

### 3. Container Security
- Keep base images updated
- Scan images for vulnerabilities
- Use minimal base images

## Monitoring and Alerts

### 1. Container Insights
```bash
# Enable container insights
az monitor log-analytics workspace create \
  --resource-group exponenthr-rag-rg \
  --workspace-name exponenthr-rag-logs
```

### 2. Application Insights
- Configure Application Insights for the Flask app
- Monitor API performance and errors
- Set up custom dashboards

### 3. Alerts
- Container restart alerts
- High CPU/memory usage alerts
- API error rate alerts
- Search service quota alerts

---

This deployment guide provides everything needed to successfully deploy and manage the ExponentHR RAG solution on Azure Container Instances.

