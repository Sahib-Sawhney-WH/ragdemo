# Complete rebuild script
$RESOURCE_GROUP = "exponenthr-rag-rg"
$CONTAINER_NAME = "exponenthr-rag-container"
$REGISTRY_NAME = "demoragregistry"
$IMAGE_NAME = "$REGISTRY_NAME.azurecr.io/exponenthr-rag:latest"

Write-Host "=== Complete Docker Rebuild ===" -ForegroundColor Green

# Clean Docker cache
Write-Host "Cleaning Docker cache..." -ForegroundColor Yellow
docker system prune -f
docker builder prune -f

# Login to ACR
Write-Host "Logging into ACR..." -ForegroundColor Yellow
az acr login --name $REGISTRY_NAME

# Build without cache
Write-Host "Building image (no cache)..." -ForegroundColor Yellow
docker build --no-cache --progress=plain -t $IMAGE_NAME .

# Push image
Write-Host "Pushing image..." -ForegroundColor Yellow
docker push $IMAGE_NAME

# Delete existing container
Write-Host "Deleting existing container..." -ForegroundColor Yellow
az container delete --name $CONTAINER_NAME --resource-group $RESOURCE_GROUP --yes

Start-Sleep -Seconds 15

# Get credentials
$ACR_USERNAME = az acr credential show --name $REGISTRY_NAME --query username --output tsv
$ACR_PASSWORD = az acr credential show --name $REGISTRY_NAME --query passwords[0].value --output tsv

# Create new container
Write-Host "Creating new container..." -ForegroundColor Yellow
az container create `
  --name $CONTAINER_NAME `
  --resource-group $RESOURCE_GROUP `
  --image $IMAGE_NAME `
  --os-type Linux `
  --cpu 2 `
  --memory 4 `
  --registry-login-server "$REGISTRY_NAME.azurecr.io" `
  --registry-username $ACR_USERNAME `
  --registry-password $ACR_PASSWORD `
  --dns-name-label $CONTAINER_NAME `
  --ports 5000 `
  --restart-policy Always `
  --environment-variables `
    AZURE_STORAGE_ACCOUNT_URL=https://raghrstorageaccount.blob.core.windows.net/ `
    AZURE_STORAGE_KEY=fGW/K/4bx2gzVwdxibgLE0uQ/r9ScaVc8lSFskdGOWZ/sjewuFxv1q... `
    AZURE_SEARCH_ENDPOINT=https://raghrsearchservice.search.windows.net  `
    AZURE_SEARCH_KEY=7opHUx4bgrkgzwXia4yeFM5bZN6nFMLwycwwVMif6HAzSeCLkBGQ `
    AZURE_OPENAI_ENDPOINT=https://aimodeluse.openai.azure.com/ `
    AZURE_OPENAI_API_KEY=EDYLWtqXKE9Ll0BqETBV7DBuKGkgToi7SfGKoxgJenhUZgNirPOvJQQJ99BGACYeBjFXJ3w3AAABACOGIfFO `
    AZURE_OPENAI_DEPLOYMENT_NAME=text-embedding-3-large `
    AZURE_OPENAI_API_VERSION=2023-05-15 `
    USE_AZURE_OPENAI=true `
    SEARCH_INDEX_NAME=exponenthr-docs `
    CONTENT_CONTAINER=scraped-content

Start-Sleep -Seconds 30

# Test
Write-Host "Testing endpoints..." -ForegroundColor Green
$FQDN = az container show --name $CONTAINER_NAME --resource-group $RESOURCE_GROUP --query "ipAddress.fqdn" --output tsv
Write-Host "Container FQDN: $FQDN" -ForegroundColor Cyan

az container logs --name $CONTAINER_NAME --resource-group $RESOURCE_GROUP --tail 20

curl "http://$FQDN`:5000/api/health"