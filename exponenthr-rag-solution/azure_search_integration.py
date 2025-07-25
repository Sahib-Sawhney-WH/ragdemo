"""
Azure AI Search Integration for ExponentHR RAG System
Handles search index management, document indexing, and search operations.
"""

import asyncio
import json
import logging
from typing import Dict, List, Optional, Any, Tuple
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
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


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
    Azure AI Search integration for the ExponentHR RAG system.
    Handles index management, document indexing, and search operations.
    """
    
    def __init__(self, config: Dict):
        """
        Initialize the Azure Search integration.
        
        Args:
            config: Configuration dictionary containing Azure Search settings
        """
        self.config = config
        self.logger = self._setup_logging()
        
        # Azure Search clients
        self.search_client: Optional[SearchClient] = None
        self.index_client: Optional[SearchIndexClient] = None
        
        # OpenAI client for embeddings
        self.openai_client = None
        self.use_azure_openai = False
        
        # Index configuration
        self.index_name = config.get('search_index_name', 'exponenthr-docs')
        self.embedding_model = config.get('embedding_model', 'text-embedding-ada-002')
        self.embedding_dimension = config.get('embedding_dimension', 1536)
        
        # Search configuration
        self.search_config = {
            'top_k': config.get('search_top_k', 10),
            'semantic_search_enabled': config.get('semantic_search_enabled', True),
            'vector_search_enabled': config.get('vector_search_enabled', True),
            'hybrid_search_enabled': config.get('hybrid_search_enabled', True)
        }
        
        # Document processing
        self.chunk_size = config.get('chunk_size', 1000)
        self.chunk_overlap = config.get('chunk_overlap', 200)
    
    def _setup_logging(self) -> logging.Logger:
        """Setup logging configuration"""
        logger = logging.getLogger('AzureSearchIntegration')
        logger.setLevel(logging.INFO)
        
        if not logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            )
            handler.setFormatter(formatter)
            logger.addHandler(handler)
        
        return logger
    
    def initialize_clients(self) -> None:
        """Initialize Azure Search and OpenAI clients"""
        try:
            # Get credentials
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
            
            # Initialize OpenAI client for embeddings (supports both OpenAI and Azure OpenAI)
            self._initialize_openai_client()
            
            self.logger.info("Azure Search and OpenAI clients initialized")
            
        except Exception as e:
            self.logger.error(f"Failed to initialize clients: {str(e)}")
            raise
    
    def _initialize_openai_client(self) -> None:
        """Initialize OpenAI client (supports both OpenAI and Azure OpenAI)"""
        try:
            # Check if Azure OpenAI configuration is provided
            azure_openai_endpoint = self.config.get('azure_openai_endpoint')
            azure_openai_key = self.config.get('azure_openai_api_key')
            use_azure_openai = self.config.get('use_azure_openai', False)
            
            if azure_openai_endpoint and azure_openai_key and use_azure_openai:
                # Use Azure OpenAI
                from openai import AzureOpenAI
                
                self.openai_client = AzureOpenAI(
                    api_key=azure_openai_key,
                    api_version=self.config.get('azure_openai_api_version', '2024-10-21'),
                    azure_endpoint=azure_openai_endpoint
                )
                
                # Update embedding model for Azure OpenAI
                self.embedding_model = self.config.get('azure_openai_deployment_name', 'text-embedding-3-large')
                self.embedding_dimension = self.config.get('embedding_dimension', 3072)  # text-embedding-3-large dimension
                self.use_azure_openai = True
                
                self.logger.info(f"Initialized Azure OpenAI client with deployment: {self.embedding_model}")
                
            else:
                # Use regular OpenAI
                openai_api_key = self.config.get('openai_api_key')
                if not openai_api_key:
                    raise ValueError("OpenAI API key not configured")
                
                # For regular OpenAI, we'll use a simpler approach
                from openai import OpenAI
                self.openai_client = OpenAI(api_key=openai_api_key)
                self.use_azure_openai = False
                
                self.logger.info("Initialized OpenAI client")
                
        except Exception as e:
            self.logger.error(f"Failed to initialize OpenAI client: {str(e)}")
            raise
    
    def create_search_index(self) -> None:
        """Create the search index with proper schema and configuration"""
        try:
            self.logger.info(f"Creating search index: {self.index_name}")
            
            # Define index fields
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
                SearchField(
                    name="embedding_vector",
                    type=SearchFieldDataType.Collection(SearchFieldDataType.Single),
                    searchable=True,
                    vector_search_dimensions=self.embedding_dimension,
                    vector_search_profile_name="default-vector-profile"
                ),
                ComplexField(name="metadata", fields=[
                    SimpleField(name="extraction_timestamp", type=SearchFieldDataType.String),
                    SimpleField(name="links", type=SearchFieldDataType.Collection(SearchFieldDataType.String)),
                    SimpleField(name="images", type=SearchFieldDataType.Collection(SearchFieldDataType.String))
                ])
            ]
            
            # Configure vector search
            vector_search = VectorSearch(
                profiles=[
                    VectorSearchProfile(
                        name="default-vector-profile",
                        algorithm_configuration_name="default-hnsw-config"
                    )
                ],
                algorithms=[
                    HnswAlgorithmConfiguration(
                        name="default-hnsw-config",
                        kind=VectorSearchAlgorithmKind.HNSW,
                        parameters={
                            "m": 4,
                            "efConstruction": 400,
                            "efSearch": 500,
                            "metric": "cosine"
                        }
                    )
                ]
            )
            
            # Configure semantic search
            semantic_config = SemanticConfiguration(
                name="default-semantic-config",
                prioritized_fields=SemanticPrioritizedFields(
                    title_field=SemanticField(field_name="title"),
                    content_fields=[SemanticField(field_name="content")],
                    keywords_fields=[SemanticField(field_name="section_hierarchy")]
                )
            )
            
            semantic_search = SemanticSearch(
                configurations=[semantic_config]
            )
            
            # Configure suggester
            suggester = SearchSuggester(
                name="default-suggester",
                source_fields=["title", "content"]
            )
            
            # Create the index
            index = SearchIndex(
                name=self.index_name,
                fields=fields,
                vector_search=vector_search,
                semantic_search=semantic_search,
                suggesters=[suggester]
            )
            
            # Create or update the index
            result = self.index_client.create_or_update_index(index)
            
            self.logger.info(f"Search index '{self.index_name}' created successfully")
            
        except Exception as e:
            self.logger.error(f"Failed to create search index: {str(e)}")
            raise
    
    def delete_search_index(self) -> None:
        """Delete the search index"""
        try:
            self.index_client.delete_index(self.index_name)
            self.logger.info(f"Search index '{self.index_name}' deleted")
        except Exception as e:
            self.logger.error(f"Failed to delete search index: {str(e)}")
            raise
    
    async def generate_embedding(self, text: str) -> List[float]:
        """
        Generate embedding vector for text using OpenAI.
        
        Args:
            text: Text to generate embedding for
            
        Returns:
            List of float values representing the embedding
        """
        try:
            # Clean and truncate text if necessary
            cleaned_text = self._clean_text_for_embedding(text)
            
            if self.use_azure_openai:
                # Use Azure OpenAI client
                response = self.openai_client.embeddings.create(
                    model=self.embedding_model,
                    input=cleaned_text
                )
                embedding = response.data[0].embedding
            else:
                # Use regular OpenAI client
                response = self.openai_client.embeddings.create(
                    model=self.embedding_model,
                    input=cleaned_text
                )
                embedding = response.data[0].embedding
            
            return embedding
            
        except Exception as e:
            self.logger.error(f"Failed to generate embedding: {str(e)}")
            # Return zero vector as fallback
            return [0.0] * self.embedding_dimension
    
    def _clean_text_for_embedding(self, text: str) -> str:
        """Clean text for embedding generation"""
        try:
            # Remove excessive whitespace
            cleaned = re.sub(r'\s+', ' ', text)
            
            # Remove special characters that might interfere
            cleaned = re.sub(r'[^\w\s\-\.\,\!\?\:\;]', ' ', cleaned)
            
            # Truncate to reasonable length (OpenAI has token limits)
            max_chars = 8000  # Conservative limit
            if len(cleaned) > max_chars:
                cleaned = cleaned[:max_chars]
            
            return cleaned.strip()
            
        except:
            return text[:1000]  # Fallback to first 1000 chars
    
    def chunk_document(self, content: str, metadata: Dict) -> List[Dict]:
        """
        Split document into chunks for indexing.
        
        Args:
            content: Document content
            metadata: Document metadata
            
        Returns:
            List of document chunks
        """
        try:
            chunks = []
            
            # Simple sentence-based chunking
            sentences = re.split(r'[.!?]+', content)
            
            current_chunk = ""
            current_length = 0
            chunk_index = 0
            
            for sentence in sentences:
                sentence = sentence.strip()
                if not sentence:
                    continue
                
                sentence_length = len(sentence)
                
                # Check if adding this sentence would exceed chunk size
                if current_length + sentence_length > self.chunk_size and current_chunk:
                    # Create chunk
                    chunk = {
                        'content': current_chunk.strip(),
                        'chunk_index': chunk_index,
                        'metadata': metadata.copy()
                    }
                    chunks.append(chunk)
                    
                    # Start new chunk with overlap
                    overlap_text = current_chunk[-self.chunk_overlap:] if len(current_chunk) > self.chunk_overlap else current_chunk
                    current_chunk = overlap_text + " " + sentence
                    current_length = len(current_chunk)
                    chunk_index += 1
                else:
                    # Add sentence to current chunk
                    if current_chunk:
                        current_chunk += " " + sentence
                    else:
                        current_chunk = sentence
                    current_length += sentence_length
            
            # Add final chunk if it has content
            if current_chunk.strip():
                chunk = {
                    'content': current_chunk.strip(),
                    'chunk_index': chunk_index,
                    'metadata': metadata.copy()
                }
                chunks.append(chunk)
            
            return chunks
            
        except Exception as e:
            self.logger.error(f"Error chunking document: {str(e)}")
            # Return single chunk as fallback
            return [{
                'content': content[:self.chunk_size],
                'chunk_index': 0,
                'metadata': metadata
            }]
    
    async def index_document(self, document_data: Dict) -> bool:
        """
        Index a single document in Azure Search.
        
        Args:
            document_data: Document data to index
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Extract document information
            url = document_data.get('url', '')
            title = document_data.get('title', '')
            content = document_data.get('content', '')
            metadata = document_data.get('metadata', {})
            
            # Create document ID
            doc_id = hashlib.sha256(url.encode('utf-8')).hexdigest()
            
            # Generate embedding for content
            embedding = await self.generate_embedding(content)
            
            # Create search document
            search_doc = SearchDocument(
                id=doc_id,
                url=url,
                title=title,
                content=content,
                content_type=metadata.get('content_type', 'documentation'),
                section_hierarchy=metadata.get('section_hierarchy', []),
                view_type=metadata.get('source_view', 'unknown'),
                word_count=metadata.get('word_count', 0),
                last_modified=metadata.get('last_modified', datetime.now().isoformat()),
                content_hash=metadata.get('content_hash', ''),
                embedding_vector=embedding,
                metadata={
                    'extraction_timestamp': metadata.get('extraction_timestamp', ''),
                    'links': metadata.get('links', []),
                    'images': metadata.get('images', [])
                }
            )
            
            # Convert to dictionary for indexing
            doc_dict = asdict(search_doc)
            
            # Upload document to index
            result = self.search_client.upload_documents([doc_dict])
            
            # Check if upload was successful
            if result and len(result) > 0 and result[0].succeeded:
                self.logger.debug(f"Successfully indexed document: {title}")
                return True
            else:
                self.logger.error(f"Failed to index document: {title}")
                return False
            
        except Exception as e:
            self.logger.error(f"Error indexing document: {str(e)}")
            return False
    
    async def index_documents_batch(self, documents: List[Dict]) -> IndexingResult:
        """
        Index multiple documents in batch.
        
        Args:
            documents: List of document data to index
            
        Returns:
            IndexingResult with operation details
        """
        start_time = datetime.now()
        
        processed_documents = 0
        indexed_documents = 0
        updated_documents = 0
        errors = []
        
        try:
            self.logger.info(f"Starting batch indexing of {len(documents)} documents")
            
            # Process documents in batches
            batch_size = self.config.get('indexing_batch_size', 10)
            
            for i in range(0, len(documents), batch_size):
                batch = documents[i:i + batch_size]
                batch_docs = []
                
                for doc_data in batch:
                    try:
                        processed_documents += 1
                        
                        # Extract document information
                        url = doc_data.get('url', '')
                        title = doc_data.get('title', '')
                        content = doc_data.get('content', '')
                        metadata = doc_data.get('metadata', {})
                        
                        # Create document ID
                        doc_id = hashlib.sha256(url.encode('utf-8')).hexdigest()
                        
                        # Generate embedding for content
                        embedding = await self.generate_embedding(content)
                        
                        # Create search document
                        search_doc = SearchDocument(
                            id=doc_id,
                            url=url,
                            title=title,
                            content=content,
                            content_type=metadata.get('content_type', 'documentation'),
                            section_hierarchy=metadata.get('section_hierarchy', []),
                            view_type=metadata.get('source_view', 'unknown'),
                            word_count=metadata.get('word_count', 0),
                            last_modified=metadata.get('last_modified', datetime.now().isoformat()),
                            content_hash=metadata.get('content_hash', ''),
                            embedding_vector=embedding,
                            metadata={
                                'extraction_timestamp': metadata.get('extraction_timestamp', ''),
                                'links': metadata.get('links', []),
                                'images': metadata.get('images', [])
                            }
                        )
                        
                        batch_docs.append(asdict(search_doc))
                        
                    except Exception as e:
                        error_msg = f"Error processing document {doc_data.get('url', 'unknown')}: {str(e)}"
                        errors.append(error_msg)
                        self.logger.error(error_msg)
                
                # Upload batch to index
                if batch_docs:
                    try:
                        results = self.search_client.upload_documents(batch_docs)
                        
                        for result in results:
                            if result.succeeded:
                                indexed_documents += 1
                            else:
                                errors.append(f"Failed to index document {result.key}: {result.error_message}")
                        
                    except Exception as e:
                        error_msg = f"Error uploading batch: {str(e)}"
                        errors.append(error_msg)
                        self.logger.error(error_msg)
                
                # Add delay between batches
                await asyncio.sleep(0.5)
            
            execution_time = (datetime.now() - start_time).total_seconds()
            
            result = IndexingResult(
                operation="batch_indexing",
                success=len(errors) == 0,
                processed_documents=processed_documents,
                indexed_documents=indexed_documents,
                updated_documents=updated_documents,
                errors=errors,
                execution_time=execution_time
            )
            
            self.logger.info(f"Batch indexing completed: {indexed_documents}/{processed_documents} documents indexed")
            
            return result
            
        except Exception as e:
            execution_time = (datetime.now() - start_time).total_seconds()
            error_msg = f"Batch indexing failed: {str(e)}"
            errors.append(error_msg)
            self.logger.error(error_msg)
            
            return IndexingResult(
                operation="batch_indexing",
                success=False,
                processed_documents=processed_documents,
                indexed_documents=indexed_documents,
                updated_documents=updated_documents,
                errors=errors,
                execution_time=execution_time
            )
    
    async def search_documents(self, query: str, filters: Dict = None, 
                             search_type: str = 'hybrid') -> List[SearchResult]:
        """
        Search documents in the index.
        
        Args:
            query: Search query
            filters: Optional filters to apply
            search_type: Type of search ('text', 'vector', 'hybrid', 'semantic')
            
        Returns:
            List of search results
        """
        try:
            search_results = []
            
            # Prepare search parameters
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
            
            # Configure search type
            if search_type == 'semantic' and self.search_config['semantic_search_enabled']:
                search_params['query_type'] = 'semantic'
                search_params['semantic_configuration_name'] = 'default-semantic-config'
            
            elif search_type == 'vector' and self.search_config['vector_search_enabled']:
                # Generate query embedding
                query_embedding = await self.generate_embedding(query)
                vector_query = VectorizedQuery(
                    vector=query_embedding,
                    k_nearest_neighbors=self.search_config['top_k'],
                    fields="embedding_vector"
                )
                search_params['vector_queries'] = [vector_query]
                search_params['search_text'] = None  # Pure vector search
            
            elif search_type == 'hybrid' and self.search_config['hybrid_search_enabled']:
                # Combine text and vector search
                query_embedding = await self.generate_embedding(query)
                vector_query = VectorizedQuery(
                    vector=query_embedding,
                    k_nearest_neighbors=self.search_config['top_k'],
                    fields="embedding_vector"
                )
                search_params['vector_queries'] = [vector_query]
            
            # Execute search
            results = self.search_client.search(**search_params)
            
            # Process results
            for result in results:
                # Extract highlights
                highlights = []
                if hasattr(result, '@search.highlights'):
                    for field, highlight_list in result['@search.highlights'].items():
                        highlights.extend(highlight_list)
                
                # Create content snippet
                content = result.get('content', '')
                snippet = self._create_content_snippet(content, query)
                
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
    
    def _create_content_snippet(self, content: str, query: str, max_length: int = 300) -> str:
        """Create a content snippet highlighting query terms"""
        try:
            # Find query terms in content
            query_terms = query.lower().split()
            content_lower = content.lower()
            
            # Find the best position to start the snippet
            best_position = 0
            max_matches = 0
            
            for i in range(0, len(content) - max_length, 50):
                snippet = content[i:i + max_length].lower()
                matches = sum(1 for term in query_terms if term in snippet)
                if matches > max_matches:
                    max_matches = matches
                    best_position = i
            
            # Extract snippet
            snippet = content[best_position:best_position + max_length]
            
            # Clean up snippet boundaries
            if best_position > 0:
                # Find word boundary
                space_pos = snippet.find(' ')
                if space_pos > 0:
                    snippet = snippet[space_pos + 1:]
            
            if len(snippet) == max_length:
                # Find last complete word
                last_space = snippet.rfind(' ')
                if last_space > max_length * 0.8:
                    snippet = snippet[:last_space] + "..."
            
            return snippet.strip()
            
        except:
            return content[:max_length] + "..." if len(content) > max_length else content
    
    async def suggest_queries(self, partial_query: str, top: int = 5) -> List[str]:
        """
        Get query suggestions based on partial input.
        
        Args:
            partial_query: Partial query string
            top: Number of suggestions to return
            
        Returns:
            List of suggested queries
        """
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
            # Get index statistics
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