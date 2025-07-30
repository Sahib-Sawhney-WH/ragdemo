# ExponentHR Dynamic RAG Scraping Solution

A comprehensive, scalable solution for automatically discovering, scraping, and maintaining ExponentHR documentation using Azure AI Search and Blob Storage with intelligent content updates and retrieval-augmented generation capabilities.

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Features](#features)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Configuration](#configuration)
- [Deployment](#deployment)
- [Usage](#usage)
- [API Reference](#api-reference)
- [Monitoring](#monitoring)
- [Troubleshooting](#troubleshooting)
- [Contributing](#contributing)

## Overview

The ExponentHR Dynamic RAG Scraping Solution is an enterprise-grade system designed to automatically discover, scrape, index, and maintain documentation from the ExponentHR help system. The solution provides intelligent search capabilities, automatic content updates, and a comprehensive API for integration with other systems.

### Key Components

1. **Web Scraping Engine** - Automated discovery and extraction of ExponentHR documentation
2. **Content Discovery Service** - Intelligent URL pattern recognition and content mapping
3. **Change Detection System** - Monitors content changes and triggers updates
4. **Azure AI Search Integration** - Advanced search capabilities with vector embeddings
5. **Synchronization Service** - Coordinates updates between all components
6. **REST API Service** - Provides web interface and programmatic access

## Architecture

The solution follows a modular, microservices-inspired architecture with the following layers:

```
┌─────────────────────────────────────────────────────────────┐
│                    REST API Layer                           │
│                 (Flask Application)                         │
├─────────────────────────────────────────────────────────────┤
│                 Orchestration Layer                         │
│              (RAG Orchestrator)                             │
├─────────────────────────────────────────────────────────────┤
│     Service Layer                                           │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐           │
│  │  Scraping   │ │   Change    │ │    Sync     │           │
│  │   Engine    │ │ Detection   │ │  Service    │           │
│  └─────────────┘ └─────────────┘ └─────────────┘           │
├─────────────────────────────────────────────────────────────┤
│                Integration Layer                            │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐           │
│  │   Azure     │ │   Azure     │ │  Content    │           │
│  │   Search    │ │   Blob      │ │ Discovery   │           │
│  │             │ │  Storage    │ │             │           │
│  └─────────────┘ └─────────────┘ └─────────────┘           │
├─────────────────────────────────────────────────────────────┤
│                   Data Layer                                │
│              (ExponentHR Help System)                       │
└─────────────────────────────────────────────────────────────┘
```

### Data Flow

1. **Discovery Phase**: Content Discovery Service analyzes ExponentHR navigation structure
2. **Scraping Phase**: Web Scraping Engine extracts content from discovered URLs
3. **Processing Phase**: Content is processed, chunked, and embedded using OpenAI
4. **Indexing Phase**: Processed content is indexed in Azure AI Search
5. **Monitoring Phase**: Change Detection System monitors for updates
6. **Synchronization Phase**: Updates are automatically synchronized across all components

## Features

### Core Features

- **Automatic Content Discovery**: Intelligent discovery of ExponentHR documentation URLs
- **Dynamic Content Scraping**: Handles JavaScript-driven content loading and fragment-based navigation
- **Change Detection**: Monitors content changes using multiple detection strategies
- **Vector Search**: Advanced semantic search using OpenAI embeddings
- **Hybrid Search**: Combines text-based and vector-based search for optimal results
- **Real-time Synchronization**: Automatic updates when content changes are detected
- **Scalable Architecture**: Designed to handle large volumes of content and concurrent users

### Advanced Features

- **Content Fingerprinting**: Multi-layered change detection using content, structural, and metadata hashes
- **Intelligent Scheduling**: Adaptive monitoring schedules based on content type and change patterns
- **Batch Processing**: Efficient processing of large content volumes
- **Error Recovery**: Robust error handling and automatic retry mechanisms
- **Comprehensive Logging**: Detailed logging and monitoring capabilities
- **API-First Design**: RESTful API for easy integration with other systems

## Prerequisites

### System Requirements

- Python 3.8 or higher
- Node.js 14 or higher (for Playwright)
- Azure subscription with appropriate permissions
- OpenAI API access

### Azure Services Required

- **Azure Storage Account**: For storing scraped content and system state
- **Azure AI Search**: For search indexing and retrieval
- **Azure Key Vault** (optional): For secure credential management

### Permissions Required

- Azure Storage Blob Data Contributor
- Search Service Contributor
- Key Vault Secrets User (if using Key Vault)

## Installation

### 1. Clone the Repository

```bash
git clone <repository-url>
cd exponenthr-rag-solution
```

### 2. Install Python Dependencies

```bash
pip install -r requirements.txt
```

### 3. Install Playwright Browsers

```bash
playwright install chromium
```

### 4. Install Azure CLI (if not already installed)

```bash
# Windows
winget install Microsoft.AzureCLI

# macOS
brew install azure-cli

# Linux
curl -sL https://aka.ms/InstallAzureCLI | sudo bash
```

### 5. Login to Azure

```bash
az login
```

## Configuration

### 1. Create Configuration File

Copy the deployment configuration template:

```bash
cp deployment_config.json my_deployment_config.json
```

### 2. Update Configuration

Edit `my_deployment_config.json` with your specific values:

```json
{
  "azure_subscription_id": "your-azure-subscription-id",
  "azure_resource_group": "exponenthr-rag-rg",
  "azure_storage_account_name": "exponenthrragstorage",
  "azure_search_service_name": "exponenthr-rag-search",
  "azure_region": "East US",
  "openai_api_key": "your-openai-api-key",
  ...
}
```

### 3. Environment Variables

Create a `.env` file for local development:

```bash
AZURE_STORAGE_ACCOUNT_URL=https://yourstorageaccount.blob.core.windows.net
AZURE_SEARCH_ENDPOINT=https://yoursearchservice.search.windows.net
AZURE_SEARCH_INDEX_NAME=exponenthr-docs
OPENAI_API_KEY=your-openai-api-key
CONTENT_CONTAINER=scraped-content
REQUEST_DELAY=1.0
SYNC_BATCH_SIZE=20
```

## Deployment

### Automated Deployment

Use the deployment script for automated setup:

```bash
python deploy.py --config my_deployment_config.json
```

### Manual Deployment Steps

1. **Create Azure Resources**:
   ```bash
   # Create resource group
   az group create --name exponenthr-rag-rg --location "East US"
   
   # Create storage account
   az storage account create --name exponenthrragstorage --resource-group exponenthr-rag-rg --location "East US" --sku Standard_LRS
   
   # Create search service
   az search service create --name exponenthr-rag-search --resource-group exponenthr-rag-rg --location "East US" --sku basic
   ```

2. **Initialize the System**:
   ```bash
   python -c "
   import asyncio
   from rag_orchestrator import RAGOrchestrator
   
   config = {
       'azure_storage_account_url': 'https://yourstorageaccount.blob.core.windows.net',
       'azure_search_endpoint': 'https://yoursearchservice.search.windows.net',
       'openai_api_key': 'your-openai-api-key'
   }
   
   async def main():
       orchestrator = RAGOrchestrator(config)
       await orchestrator.initialize()
       await orchestrator.shutdown()
   
   asyncio.run(main())
   "
   ```

3. **Run Initial Data Load**:
   ```bash
   python -c "
   import asyncio
   from rag_orchestrator import RAGOrchestrator
   
   async def main():
       orchestrator = RAGOrchestrator(config)
       await orchestrator.initialize()
       result = await orchestrator.perform_full_discovery_and_scraping(['personal'])
       print(f'Processed {result.processed_urls} URLs')
       await orchestrator.shutdown()
   
   asyncio.run(main())
   "
   ```

## Usage

### Starting the API Service

1. **Navigate to API Service Directory**:
   ```bash
   cd rag_api_service
   ```

2. **Activate Virtual Environment**:
   ```bash
   source venv/bin/activate  # Linux/macOS
   # or
   venv\Scripts\activate     # Windows
   ```

3. **Start the Service**:
   ```bash
   python src/main.py
   ```

The API service will be available at `http://localhost:5000`

### Basic Usage Examples

#### Search Documents

```bash
curl -X POST http://localhost:5000/api/search \
  -H "Content-Type: application/json" \
  -d '{
    "query": "direct deposit",
    "search_type": "hybrid"
  }'
```

#### Trigger Full Synchronization

```bash
curl -X POST http://localhost:5000/api/sync/full \
  -H "Content-Type: application/json" \
  -d '{
    "view_types": ["personal", "management"]
  }'
```

#### Check System Status

```bash
curl http://localhost:5000/api/system/status
```

### Python SDK Usage

```python
import asyncio
from rag_orchestrator import RAGOrchestrator
from azure_search_integration import AzureSearchIntegration

# Initialize components
config = {
    'azure_storage_account_url': 'https://yourstorageaccount.blob.core.windows.net',
    'azure_search_endpoint': 'https://yoursearchservice.search.windows.net',
    'openai_api_key': 'your-openai-api-key'
}

async def main():
    # Initialize search integration
    search = AzureSearchIntegration(config)
    search.initialize_clients()
    
    # Perform search
    results = await search.search_documents("edit direct deposit", search_type="hybrid")
    
    for result in results:
        print(f"Title: {result.title}")
        print(f"URL: {result.url}")
        print(f"Score: {result.score}")
        print(f"Snippet: {result.content_snippet}")
        print("---")

asyncio.run(main())
```

## API Reference

### Search Endpoints

#### POST /api/search
Search documents in the knowledge base.

**Request Body**:
```json
{
  "query": "search query",
  "filters": {
    "content_type": "procedure",
    "view_type": "personal"
  },
  "search_type": "hybrid"
}
```

**Response**:
```json
{
  "query": "search query",
  "results": [
    {
      "id": "document-id",
      "url": "document-url",
      "title": "Document Title",
      "snippet": "Content snippet...",
      "score": 0.95,
      "highlights": ["highlighted", "terms"],
      "metadata": {}
    }
  ],
  "total_results": 10,
  "search_type": "hybrid"
}
```

#### GET /api/suggest
Get query suggestions.

**Parameters**:
- `q`: Partial query string
- `top`: Number of suggestions (default: 5)

**Response**:
```json
{
  "suggestions": ["suggestion 1", "suggestion 2", ...]
}
```

### Synchronization Endpoints

#### POST /api/sync/full
Trigger a full synchronization.

**Request Body**:
```json
{
  "view_types": ["personal", "management"]
}
```

#### POST /api/sync/incremental
Trigger an incremental synchronization.

#### GET /api/sync/status
Get synchronization status and history.

### System Endpoints

#### GET /api/system/status
Get overall system status and statistics.

#### GET /api/health
Health check endpoint.

## Monitoring

### Logging

The system provides comprehensive logging at multiple levels:

- **INFO**: General operational information
- **WARNING**: Non-critical issues that should be monitored
- **ERROR**: Critical errors that require attention

Logs are written to both console and file outputs.

### Metrics

Key metrics tracked by the system:

- **Search Performance**: Query response times, result relevance scores
- **Synchronization Metrics**: Success rates, processing times, error rates
- **Content Metrics**: Document counts, change detection accuracy
- **System Health**: Service availability, resource utilization

### Health Checks

The system includes built-in health checks accessible via the `/api/health` endpoint:

```json
{
  "status": "healthy",
  "timestamp": "2024-01-15T10:30:00Z",
  "services": {
    "api": true,
    "search": true,
    "orchestrator": true,
    "sync": true
  }
}
```

### Alerts

Configure alerts for:

- Search service failures
- Synchronization errors
- High error rates
- Resource exhaustion
- Content staleness

## Troubleshooting

### Common Issues

#### 1. Authentication Errors

**Problem**: Azure authentication failures

**Solution**:
```bash
# Re-login to Azure CLI
az login

# Check current account
az account show

# Set correct subscription
az account set --subscription "your-subscription-id"
```

#### 2. Search Index Not Found

**Problem**: Azure Search index doesn't exist

**Solution**:
```python
from azure_search_integration import AzureSearchIntegration

config = {...}
search = AzureSearchIntegration(config)
search.initialize_clients()
search.create_search_index()
```

#### 3. Playwright Browser Issues

**Problem**: Browser automation failures

**Solution**:
```bash
# Reinstall browsers
playwright install chromium

# Install system dependencies (Linux)
playwright install-deps
```

#### 4. Memory Issues

**Problem**: High memory usage during processing

**Solution**:
- Reduce batch sizes in configuration
- Increase system memory
- Enable content chunking

#### 5. Rate Limiting

**Problem**: Too many requests to ExponentHR

**Solution**:
- Increase `request_delay` in configuration
- Reduce concurrent operations
- Implement exponential backoff

### Debug Mode

Enable debug mode for detailed logging:

```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

### Performance Optimization

1. **Batch Size Tuning**: Adjust `sync_batch_size` based on system resources
2. **Concurrent Operations**: Tune `max_concurrent_sync_operations`
3. **Caching**: Enable content caching for frequently accessed documents
4. **Index Optimization**: Regular index maintenance and optimization

## Contributing

### Development Setup

1. **Fork the Repository**
2. **Create Development Branch**:
   ```bash
   git checkout -b feature/your-feature-name
   ```
3. **Install Development Dependencies**:
   ```bash
   pip install -r requirements-dev.txt
   ```
4. **Run Tests**:
   ```bash
   python -m pytest tests/
   ```

### Code Standards

- Follow PEP 8 style guidelines
- Include comprehensive docstrings
- Add unit tests for new functionality
- Update documentation for API changes

### Submitting Changes

1. **Run Tests**: Ensure all tests pass
2. **Update Documentation**: Update relevant documentation
3. **Create Pull Request**: Submit PR with detailed description
4. **Code Review**: Address review feedback

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Support

For support and questions:

- **Documentation**: Check this README and inline code documentation
- **Issues**: Create GitHub issues for bugs and feature requests
- **Discussions**: Use GitHub Discussions for general questions

## Changelog

### Version 1.0.0
- Initial release
- Core scraping and search functionality
- Azure AI Search integration
- Change detection system
- REST API service
- Comprehensive documentation

---

**Author**: Manus AI  
**Created**: January 2024  
**Last Updated**: January 2024

