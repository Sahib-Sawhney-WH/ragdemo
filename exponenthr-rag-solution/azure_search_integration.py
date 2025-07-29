"""
MINIMAL Azure AI Search Integration for ExponentHR RAG System
Simplified version that bypasses OpenAI client initialization issues.
"""

import asyncio
import json
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime
from dataclasses import dataclass, asdict
import hashlib
import re

from azure.search.documents import SearchClient
from azure.search.documents.indexes import SearchIndexClient
from azure.search.documents.indexes.models import (
    SearchIndex, SearchField, SearchFieldDataType, SimpleField, SearchableField,
    ComplexField, VectorSearch, VectorSearchProfile, HnswAlgorithmConfiguration,
    VectorSearchAlgorithmKind, SemanticConfiguration, SemanticSearch,
    SemanticPrioritizedFields, SemanticField, SearchSuggester
)
from azure.search.documents.models import VectorizedQuery
from azure.identity import DefaultAzureCredential
from azure.core.credentials import AzureKeyCredential


@dataclass
class SearchDocument:
    """Structure for search index documents"""
    id: str
    url: str
    title: str
    content: str
    content_type: str
    section_hierarchy: List[str]
    view_type: str
    word_count: int
    last_modified: str
    content_hash: str
    embedding_vector: Optional[List[float]]
    metadata: Dict[str, Any]


@dataclass
class SearchResult:
    """Structure for search results"""
    document_id: str
    url: str
    title: str
    content_snippet: str
    score: float
    highlights: List[str]
    metadata: Dict[str, Any]


@dataclass
class IndexingResult:
    """Result structure for indexing operations"""
    operation: str
    success: bool
    processed_documents: int
    indexed_documents: int
    updated_documents: int
    errors: List[str]
    execution_time: float


class AzureSearchIntegration:
    """
    MINIMAL Azure AI Search integration for the ExponentHR RAG system.
    Simplified version to bypass OpenAI client issues.
    """
    
    def __init__(self, config: Dict):
        """Initialize the Azure Search integration."""
        self.config = config
        self.logger = self._setup_logging()
        
        # Azure Search clients
        self.search_client: Optional[SearchClient] = None
        self.index_client: Optional[SearchIndexClient] = None
        
        # OpenAI client info (but don't initialize yet)
        self.openai_client = None
        self.use_azure_openai = config.get('use_azure_openai', False)
        
        # Index configuration
        self.index_name = config.get('search_index_name', 'exponenthr-docs')
        self.embedding_model = config.get('azure_openai_deployment_name', 'text-embedding-3-large')
        self.embedding_dimension = config.get('embedding_dimension', 3072)
        
        # Search configuration
        self.search_config = {
            'top_k': config.get('search_top_k', 10),
            'semantic_search_enabled': config.get('semantic_search_enabled', True),
            'vector_search_enabled': False,  # Disable for now
            'hybrid_search_enabled': False   # Disable for now
        }
        
        self.logger.info("AzureSearchIntegration initialized in minimal mode")
    
    def _setup_logging(self) -> logging.Logger:
        """Setup logging configuration"""
        logger = logging.getLogger('AzureSearchIntegration')
        logger.setLevel(logging.INFO)
        
        if not logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
            handler.setFormatter(formatter)
            logger.addHandler(handler)
        
        return logger
    
    def initialize_clients(self) -> None:
        """Initialize Azure Search clients (skip OpenAI for now)"""
        try:
            search_endpoint = self.config.get('azure_search_endpoint')
            search_key = self.config.get('azure_search_key')
            
            if not search_endpoint:
                raise ValueError("Azure Search endpoint not configured")
            
            # Initialize credential
            if search_key:
                credential = AzureKeyCredential(search_key)
            else:
                credential = DefaultAzureCredential()
            
            # Initialize Azure Search clients
            self.search_client = SearchClient(
                endpoint=search_endpoint,
                index_name=self.index_name,
                credential=credential
            )
            
            self.index_client = SearchIndexClient(
                endpoint=search_endpoint,
                credential=credential
            )
            
            self.logger.info("Azure Search clients initialized (OpenAI client deferred)")
            
        except Exception as e:
            self.logger.error(f"Failed to initialize clients: {str(e)}")
            raise
    
    def _initialize_openai_client(self) -> None:
        """Initialize Azure OpenAI using direct HTTP calls"""
        try:
            # Your Azure OpenAI configuration
            self.azure_openai_endpoint = self.config.get('azure_openai_endpoint', '').rstrip('/')
            self.azure_openai_key = self.config.get('azure_openai_api_key', '')
            self.azure_openai_deployment = self.config.get('azure_openai_deployment_name', 'text-embedding-3-large')
            self.azure_openai_version = self.config.get('azure_openai_api_version', '2024-10-21')
            
            if not self.azure_openai_endpoint or not self.azure_openai_key:
                raise ValueError("Azure OpenAI endpoint and API key are required")
            
            # Test connection to YOUR Azure OpenAI service
            import requests
            test_url = f"{self.azure_openai_endpoint}/openai/deployments?api-version={self.azure_openai_version}"
            headers = {'api-key': self.azure_openai_key}
            
            response = requests.get(test_url, headers=headers, timeout=10)
            
            if response.status_code == 200:
                self.openai_client = "azure_direct"  # Flag for direct usage
                self.embedding_model = self.azure_openai_deployment
                self.embedding_dimension = self.config.get('embedding_dimension', 3072)
                self.use_azure_openai = True
                self.logger.info(f"✅ Connected to Azure OpenAI: {self.azure_openai_endpoint}")
                self.logger.info(f"✅ Using deployment: {self.embedding_model}")
            else:
                raise Exception(f"Failed to connect to Azure OpenAI: {response.status_code}")
                
        except Exception as e:
            self.logger.error(f"Failed to initialize Azure OpenAI: {str(e)}")
            raise
        
    async def generate_embedding(self, text: str) -> List[float]:
        """Generate embedding using YOUR Azure OpenAI service"""
        try:
            if self.openai_client != "azure_direct":
                return [0.0] * self.embedding_dimension
            
            import requests
            
            # Call YOUR Azure OpenAI embeddings endpoint
            url = f"{self.azure_openai_endpoint}/openai/deployments/{self.azure_openai_deployment}/embeddings?api-version={self.azure_openai_version}"
            
            headers = {
                'api-key': self.azure_openai_key,
                'Content-Type': 'application/json'
            }
            
            cleaned_text = self._clean_text_for_embedding(text)
            
            data = {
                'input': cleaned_text,
                'model': self.azure_openai_deployment
            }
            
            response = requests.post(url, headers=headers, json=data, timeout=30)
            
            if response.status_code == 200:
                result = response.json()
                embedding = result['data'][0]['embedding']
                return embedding
            else:
                self.logger.error(f"Azure OpenAI error: {response.status_code}")
                return [0.0] * self.embedding_dimension
                
        except Exception as e:
            self.logger.error(f"Embedding error: {str(e)}")
            return [0.0] * self.embedding_dimension
    
    def create_search_index(self) -> None:
        """Create the search index with minimal configuration"""
        try:
            self.logger.info(f"Creating search index: {self.index_name}")
            
            # Define basic index fields (without vector search for now)
            fields = [
                SimpleField(name="id", type=SearchFieldDataType.String, key=True),
                SearchableField(name="url", type=SearchFieldDataType.String),
                SearchableField(name="title", type=SearchFieldDataType.String, analyzer_name="en.microsoft"),
                SearchableField(name="content", type=SearchFieldDataType.String, analyzer_name="en.microsoft"),
                SimpleField(name="content_type", type=SearchFieldDataType.String, filterable=True, facetable=True),
                SimpleField(name="section_hierarchy", type=SearchFieldDataType.Collection(SearchFieldDataType.String), filterable=True),
                SimpleField(name="view_type", type=SearchFieldDataType.String, filterable=True, facetable=True),
                SimpleField(name="word_count", type=SearchFieldDataType.Int32, filterable=True, sortable=True),
                SimpleField(name="last_modified", type=SearchFieldDataType.DateTimeOffset, filterable=True, sortable=True),
                SimpleField(name="content_hash", type=SearchFieldDataType.String),
                ComplexField(name="metadata", fields=[
                    SimpleField(name="extraction_timestamp", type=SearchFieldDataType.String),
                    SimpleField(name="links", type=SearchFieldDataType.Collection(SearchFieldDataType.String)),
                    SimpleField(name="images", type=SearchFieldDataType.Collection(SearchFieldDataType.String))
                ])
            ]
            
            # Configure semantic search
            semantic_config = SemanticConfiguration(
                name="default-semantic-config",
                prioritized_fields=SemanticPrioritizedFields(
                    title_field=SemanticField(field_name="title"),
                    content_fields=[SemanticField(field_name="content")],
                    keywords_fields=[SemanticField(field_name="section_hierarchy")]
                )
            )
            
            semantic_search = SemanticSearch(configurations=[semantic_config])
            
            # Configure suggester
            suggester = SearchSuggester(name="default-suggester", source_fields=["title", "content"])
            
            # Create the index
            index = SearchIndex(
                name=self.index_name,
                fields=fields,
                semantic_search=semantic_search,
                suggesters=[suggester]
            )
            
            # Create or update the index
            result = self.index_client.create_or_update_index(index)
            self.logger.info(f"Search index '{self.index_name}' created successfully")
            
        except Exception as e:
            self.logger.error(f"Failed to create search index: {str(e)}")
            raise
    
    async def index_document(self, document_data: Dict) -> bool:
        """Index a single document (without embeddings for now)"""
        try:
            url = document_data.get('url', '')
            title = document_data.get('title', '')
            content = document_data.get('content', '')
            metadata = document_data.get('metadata', {})
            
            doc_id = hashlib.sha256(url.encode('utf-8')).hexdigest()
            
            # Create search document without embedding for now
            search_doc = {
                'id': doc_id,
                'url': url,
                'title': title,
                'content': content,
                'content_type': metadata.get('content_type', 'documentation'),
                'section_hierarchy': metadata.get('section_hierarchy', []),
                'view_type': metadata.get('source_view', 'unknown'),
                'word_count': metadata.get('word_count', 0),
                'last_modified': metadata.get('last_modified', datetime.now().isoformat()),
                'content_hash': metadata.get('content_hash', ''),
                'metadata': {
                    'extraction_timestamp': metadata.get('extraction_timestamp', ''),
                    'links': metadata.get('links', []),
                    'images': metadata.get('images', [])
                }
            }
            
            # Upload document to index
            result = self.search_client.upload_documents([search_doc])
            
            if result and len(result) > 0 and result[0].succeeded:
                self.logger.debug(f"Successfully indexed document: {title}")
                return True
            else:
                self.logger.error(f"Failed to index document: {title}")
                return False
            
        except Exception as e:
            self.logger.error(f"Error indexing document: {str(e)}")
            return False
    
    async def search_documents(self, query: str, filters: Dict = None, search_type: str = 'text') -> List[SearchResult]:
        """Search documents using text search (vector search disabled for now)"""
        try:
            search_results = []
            
            # Use simple text search for now
            search_params = {
                'search_text': query,
                'top': self.search_config['top_k'],
                'include_total_count': True,
                'highlight_fields': ['title', 'content'],
                'select': ['id', 'url', 'title', 'content', 'content_type', 'view_type', 'metadata']
            }
            
            # Add filters if provided
            if filters:
                filter_expressions = []
                for key, value in filters.items():
                    if isinstance(value, list):
                        filter_expr = f"{key}/any(x: x eq '{value[0]}')"
                        for v in value[1:]:
                            filter_expr += f" or {key}/any(x: x eq '{v}')"
                    else:
                        filter_expr = f"{key} eq '{value}'"
                    filter_expressions.append(filter_expr)
                
                if filter_expressions:
                    search_params['filter'] = ' and '.join(filter_expressions)
            
            # Execute search
            results = self.search_client.search(**search_params)
            
            # Process results
            for result in results:
                highlights = []
                if hasattr(result, '@search.highlights'):
                    for field, highlight_list in result['@search.highlights'].items():
                        highlights.extend(highlight_list)
                
                content = result.get('content', '')
                snippet = content[:300] + "..." if len(content) > 300 else content
                
                search_result = SearchResult(
                    document_id=result['id'],
                    url=result['url'],
                    title=result['title'],
                    content_snippet=snippet,
                    score=result.get('@search.score', 0.0),
                    highlights=highlights,
                    metadata=result.get('metadata', {})
                )
                
                search_results.append(search_result)
            
            self.logger.info(f"Search completed: {len(search_results)} results for query '{query}'")
            return search_results
            
        except Exception as e:
            self.logger.error(f"Search failed: {str(e)}")
            return []
    
    async def suggest_queries(self, partial_query: str, top: int = 5) -> List[str]:
        """Get query suggestions"""
        try:
            suggestions = self.search_client.suggest(
                search_text=partial_query,
                suggester_name="default-suggester",
                top=top
            )
            return [suggestion['text'] for suggestion in suggestions]
        except Exception as e:
            self.logger.error(f"Failed to get suggestions: {str(e)}")
            return []
    
    def get_index_statistics(self) -> Dict:
        """Get statistics about the search index"""
        try:
            index_stats = self.index_client.get_index_statistics(self.index_name)
            return {
                'document_count': index_stats.document_count,
                'storage_size_bytes': index_stats.storage_size,
                'index_name': self.index_name,
                'last_updated': datetime.now().isoformat()
            }
        except Exception as e:
            self.logger.error(f"Failed to get index statistics: {str(e)}")
            return {}
    
    async def delete_document(self, document_id: str) -> bool:
        """Delete a document from the index"""
        try:
            result = self.search_client.delete_documents([{"id": document_id}])
            
            if result and len(result) > 0 and result[0].succeeded:
                self.logger.info(f"Document {document_id} deleted from index")
                return True
            else:
                self.logger.error(f"Failed to delete document {document_id}")
                return False
                
        except Exception as e:
            self.logger.error(f"Error deleting document: {str(e)}")
            return False