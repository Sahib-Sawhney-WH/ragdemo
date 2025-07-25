"""
Synchronization Service for ExponentHR RAG System
Coordinates content updates between scraping, change detection, and search indexing.
"""

import asyncio
import json
import logging
from typing import Dict, List, Optional, Tuple, Set
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict
import time

from exponenthr_scraper import ExponentHRScraper, ScrapingResult
from content_discovery import ContentDiscoveryService
from change_detection import ChangeDetectionSystem, ChangeEvent, ContentFingerprint
from azure_search_integration import AzureSearchIntegration, IndexingResult
from azure.storage.blob import BlobServiceClient
from azure.identity import DefaultAzureCredential


@dataclass
class SyncOperation:
    """Structure for synchronization operations"""
    operation_id: str
    operation_type: str  # 'full_sync', 'incremental_sync', 'change_sync'
    status: str  # 'pending', 'running', 'completed', 'failed'
    started_at: Optional[str]
    completed_at: Optional[str]
    urls_processed: int
    urls_updated: int
    urls_failed: int
    errors: List[str]
    metadata: Dict


@dataclass
class SyncResult:
    """Result structure for synchronization operations"""
    operation_id: str
    success: bool
    total_processed: int
    newly_indexed: int
    updated_indexed: int
    removed_indexed: int
    errors: List[str]
    execution_time: float
    sync_statistics: Dict


class SynchronizationService:
    """
    Service for synchronizing content between scraping, change detection, and search indexing.
    Manages the complete update workflow and ensures data consistency.
    """
    
    def __init__(self, config: Dict):
        """
        Initialize the synchronization service.
        
        Args:
            config: Configuration dictionary
        """
        self.config = config
        self.logger = self._setup_logging()
        
        # Initialize component services
        self.scraper = ExponentHRScraper(config)
        self.discovery_service = ContentDiscoveryService(config)
        self.change_detector = ChangeDetectionSystem(config)
        self.search_integration = AzureSearchIntegration(config)
        
        # Azure clients
        self.blob_client = None
        
        # Synchronization state
        self.active_operations: Dict[str, SyncOperation] = {}
        self.sync_history: List[SyncResult] = []
        self.last_full_sync: Optional[datetime] = None
        self.last_incremental_sync: Optional[datetime] = None
        
        # Configuration
        self.sync_config = {
            'max_concurrent_operations': config.get('max_concurrent_sync_operations', 3),
            'batch_size': config.get('sync_batch_size', 20),
            'retry_attempts': config.get('sync_retry_attempts', 3),
            'retry_delay': config.get('sync_retry_delay', 5),
            'full_sync_interval_hours': config.get('full_sync_interval_hours', 168),  # Weekly
            'incremental_sync_interval_hours': config.get('incremental_sync_interval_hours', 6)
        }
        
        # Metrics and monitoring
        self.sync_metrics = {
            'total_syncs': 0,
            'successful_syncs': 0,
            'failed_syncs': 0,
            'average_sync_time': 0.0,
            'last_error': None
        }
    
    def _setup_logging(self) -> logging.Logger:
        """Setup logging configuration"""
        logger = logging.getLogger('SynchronizationService')
        logger.setLevel(logging.INFO)
        
        if not logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            )
            handler.setFormatter(formatter)
            logger.addHandler(handler)
        
        return logger
    
    async def initialize(self) -> None:
        """Initialize all component services"""
        try:
            self.logger.info("Initializing Synchronization Service...")
            
            # Initialize Azure clients
            await self._initialize_azure_clients()
            
            # Initialize component services
            await self.scraper.initialize_browser()
            self.change_detector.initialize_azure_clients()
            self.search_integration.initialize_clients()
            
            # Load previous state
            await self._load_sync_state()
            
            self.logger.info("Synchronization Service initialized successfully")
            
        except Exception as e:
            self.logger.error(f"Failed to initialize Synchronization Service: {str(e)}")
            raise
    
    async def _initialize_azure_clients(self) -> None:
        """Initialize Azure service clients"""
        try:
            credential = DefaultAzureCredential()
            
            # Initialize Blob Storage client
            storage_account_url = self.config.get('azure_storage_account_url')
            if storage_account_url:
                self.blob_client = BlobServiceClient(
                    account_url=storage_account_url,
                    credential=credential
                )
                self.logger.info("Azure Blob Storage client initialized")
            
        except Exception as e:
            self.logger.error(f"Failed to initialize Azure clients: {str(e)}")
            raise
    
    async def perform_full_synchronization(self, view_types: List[str] = None) -> SyncResult:
        """
        Perform a complete synchronization of all content.
        
        Args:
            view_types: List of view types to synchronize
            
        Returns:
            SyncResult with operation details
        """
        operation_id = f"full_sync_{int(time.time())}"
        start_time = time.time()
        
        if view_types is None:
            view_types = ['personal', 'management']
        
        self.logger.info(f"Starting full synchronization for views: {view_types}")
        
        # Create sync operation
        sync_operation = SyncOperation(
            operation_id=operation_id,
            operation_type='full_sync',
            status='running',
            started_at=datetime.now().isoformat(),
            completed_at=None,
            urls_processed=0,
            urls_updated=0,
            urls_failed=0,
            errors=[],
            metadata={'view_types': view_types}
        )
        
        self.active_operations[operation_id] = sync_operation
        
        total_processed = 0
        newly_indexed = 0
        updated_indexed = 0
        removed_indexed = 0
        errors = []
        
        try:
            # Step 1: Discover all URLs
            all_discovered_urls = set()
            
            for view_type in view_types:
                try:
                    self.logger.info(f"Discovering URLs for {view_type} view")
                    
                    # Discover navigation structure
                    nav_structure = await self.discovery_service.discover_navigation_structure(
                        self.scraper.page, view_type
                    )
                    
                    # Extract URLs
                    urls = [link['full_url'] for link in nav_structure.get('all_links', [])]
                    all_discovered_urls.update(urls)
                    
                    self.logger.info(f"Discovered {len(urls)} URLs for {view_type} view")
                    
                except Exception as e:
                    error_msg = f"Error discovering URLs for {view_type}: {str(e)}"
                    errors.append(error_msg)
                    self.logger.error(error_msg)
            
            # Step 2: Validate discovered URLs
            self.logger.info(f"Validating {len(all_discovered_urls)} discovered URLs")
            
            valid_urls = []
            for url in all_discovered_urls:
                try:
                    # Quick validation - could be enhanced
                    if self._is_valid_url_format(url):
                        valid_urls.append(url)
                except Exception as e:
                    self.logger.warning(f"URL validation failed for {url}: {str(e)}")
            
            self.logger.info(f"Validated {len(valid_urls)} URLs for processing")
            
            # Step 3: Process URLs in batches
            batch_size = self.sync_config['batch_size']
            
            for i in range(0, len(valid_urls), batch_size):
                batch_urls = valid_urls[i:i + batch_size]
                
                self.logger.info(f"Processing batch {i//batch_size + 1}: {len(batch_urls)} URLs")
                
                batch_result = await self._process_url_batch(batch_urls, operation_id)
                
                total_processed += batch_result['processed']
                newly_indexed += batch_result['newly_indexed']
                updated_indexed += batch_result['updated_indexed']
                errors.extend(batch_result['errors'])
                
                # Update operation status
                sync_operation.urls_processed = total_processed
                sync_operation.urls_updated = newly_indexed + updated_indexed
                sync_operation.urls_failed = len(errors)
                sync_operation.errors = errors
                
                # Add delay between batches
                await asyncio.sleep(1)
            
            # Step 4: Clean up obsolete documents
            self.logger.info("Cleaning up obsolete documents from search index")
            
            try:
                removed_count = await self._cleanup_obsolete_documents(valid_urls)
                removed_indexed = removed_count
                
                self.logger.info(f"Removed {removed_count} obsolete documents from index")
                
            except Exception as e:
                error_msg = f"Error cleaning up obsolete documents: {str(e)}"
                errors.append(error_msg)
                self.logger.error(error_msg)
            
            # Complete operation
            execution_time = time.time() - start_time
            success = len(errors) == 0
            
            sync_operation.status = 'completed' if success else 'failed'
            sync_operation.completed_at = datetime.now().isoformat()
            
            # Update metrics
            self._update_sync_metrics(success, execution_time)
            
            # Record last full sync time
            self.last_full_sync = datetime.now()
            
            # Create result
            result = SyncResult(
                operation_id=operation_id,
                success=success,
                total_processed=total_processed,
                newly_indexed=newly_indexed,
                updated_indexed=updated_indexed,
                removed_indexed=removed_indexed,
                errors=errors,
                execution_time=execution_time,
                sync_statistics=self._get_sync_statistics()
            )
            
            self.sync_history.append(result)
            
            # Clean up operation
            del self.active_operations[operation_id]
            
            self.logger.info(f"Full synchronization completed: {total_processed} processed, "
                           f"{newly_indexed} new, {updated_indexed} updated, "
                           f"{removed_indexed} removed, {len(errors)} errors")
            
            return result
            
        except Exception as e:
            execution_time = time.time() - start_time
            error_msg = f"Full synchronization failed: {str(e)}"
            errors.append(error_msg)
            self.logger.error(error_msg)
            
            # Update operation status
            sync_operation.status = 'failed'
            sync_operation.completed_at = datetime.now().isoformat()
            sync_operation.errors = errors
            
            # Update metrics
            self._update_sync_metrics(False, execution_time)
            
            result = SyncResult(
                operation_id=operation_id,
                success=False,
                total_processed=total_processed,
                newly_indexed=newly_indexed,
                updated_indexed=updated_indexed,
                removed_indexed=removed_indexed,
                errors=errors,
                execution_time=execution_time,
                sync_statistics=self._get_sync_statistics()
            )
            
            self.sync_history.append(result)
            
            # Clean up operation
            del self.active_operations[operation_id]
            
            return result
    
    async def perform_incremental_synchronization(self) -> SyncResult:
        """
        Perform incremental synchronization based on change detection.
        
        Returns:
            SyncResult with operation details
        """
        operation_id = f"incremental_sync_{int(time.time())}"
        start_time = time.time()
        
        self.logger.info("Starting incremental synchronization")
        
        # Create sync operation
        sync_operation = SyncOperation(
            operation_id=operation_id,
            operation_type='incremental_sync',
            status='running',
            started_at=datetime.now().isoformat(),
            completed_at=None,
            urls_processed=0,
            urls_updated=0,
            urls_failed=0,
            errors=[],
            metadata={}
        )
        
        self.active_operations[operation_id] = sync_operation
        
        total_processed = 0
        newly_indexed = 0
        updated_indexed = 0
        removed_indexed = 0
        errors = []
        
        try:
            # Get URLs due for checking
            urls_to_check = self.change_detector.get_urls_due_for_check()
            
            self.logger.info(f"Found {len(urls_to_check)} URLs due for checking")
            
            if not urls_to_check:
                self.logger.info("No URLs due for checking")
                execution_time = time.time() - start_time
                
                result = SyncResult(
                    operation_id=operation_id,
                    success=True,
                    total_processed=0,
                    newly_indexed=0,
                    updated_indexed=0,
                    removed_indexed=0,
                    errors=[],
                    execution_time=execution_time,
                    sync_statistics=self._get_sync_statistics()
                )
                
                self.sync_history.append(result)
                del self.active_operations[operation_id]
                
                return result
            
            # Process URLs in batches
            batch_size = self.sync_config['batch_size']
            
            for i in range(0, len(urls_to_check), batch_size):
                batch_urls = urls_to_check[i:i + batch_size]
                
                self.logger.info(f"Processing incremental batch {i//batch_size + 1}: {len(batch_urls)} URLs")
                
                batch_result = await self._process_incremental_batch(batch_urls, operation_id)
                
                total_processed += batch_result['processed']
                updated_indexed += batch_result['updated_indexed']
                errors.extend(batch_result['errors'])
                
                # Update operation status
                sync_operation.urls_processed = total_processed
                sync_operation.urls_updated = updated_indexed
                sync_operation.urls_failed = len(errors)
                sync_operation.errors = errors
                
                # Add delay between batches
                await asyncio.sleep(0.5)
            
            # Complete operation
            execution_time = time.time() - start_time
            success = len(errors) == 0
            
            sync_operation.status = 'completed' if success else 'failed'
            sync_operation.completed_at = datetime.now().isoformat()
            
            # Update metrics
            self._update_sync_metrics(success, execution_time)
            
            # Record last incremental sync time
            self.last_incremental_sync = datetime.now()
            
            # Create result
            result = SyncResult(
                operation_id=operation_id,
                success=success,
                total_processed=total_processed,
                newly_indexed=newly_indexed,
                updated_indexed=updated_indexed,
                removed_indexed=removed_indexed,
                errors=errors,
                execution_time=execution_time,
                sync_statistics=self._get_sync_statistics()
            )
            
            self.sync_history.append(result)
            
            # Clean up operation
            del self.active_operations[operation_id]
            
            self.logger.info(f"Incremental synchronization completed: {total_processed} processed, "
                           f"{updated_indexed} updated, {len(errors)} errors")
            
            return result
            
        except Exception as e:
            execution_time = time.time() - start_time
            error_msg = f"Incremental synchronization failed: {str(e)}"
            errors.append(error_msg)
            self.logger.error(error_msg)
            
            # Update operation status
            sync_operation.status = 'failed'
            sync_operation.completed_at = datetime.now().isoformat()
            sync_operation.errors = errors
            
            # Update metrics
            self._update_sync_metrics(False, execution_time)
            
            result = SyncResult(
                operation_id=operation_id,
                success=False,
                total_processed=total_processed,
                newly_indexed=newly_indexed,
                updated_indexed=updated_indexed,
                removed_indexed=removed_indexed,
                errors=errors,
                execution_time=execution_time,
                sync_statistics=self._get_sync_statistics()
            )
            
            self.sync_history.append(result)
            
            # Clean up operation
            del self.active_operations[operation_id]
            
            return result
    
    async def _process_url_batch(self, urls: List[str], operation_id: str) -> Dict:
        """Process a batch of URLs for full synchronization"""
        processed = 0
        newly_indexed = 0
        updated_indexed = 0
        errors = []
        
        for url in urls:
            try:
                # Scrape the document
                scraping_result = await self.scraper.scrape_document(url)
                processed += 1
                
                if scraping_result.success:
                    # Create content fingerprint
                    fingerprint = self.change_detector.create_content_fingerprint(
                        url,
                        scraping_result.content,
                        asdict(scraping_result.metadata)
                    )
                    
                    # Check for changes
                    change_event = self.change_detector.detect_changes(url, fingerprint)
                    
                    # Prepare document for indexing
                    document_data = {
                        'url': url,
                        'title': scraping_result.metadata.title,
                        'content': scraping_result.content,
                        'metadata': asdict(scraping_result.metadata)
                    }
                    
                    # Index the document
                    index_success = await self.search_integration.index_document(document_data)
                    
                    if index_success:
                        if change_event and change_event.change_type == 'new':
                            newly_indexed += 1
                        else:
                            updated_indexed += 1
                        
                        # Setup monitoring schedule
                        content_type = scraping_result.metadata.content_type
                        self.change_detector.setup_monitoring_schedule(
                            url, content_type, 'medium'
                        )
                        
                        # Store content in blob storage
                        await self._store_content_in_blob(scraping_result)
                    else:
                        errors.append(f"Failed to index document: {url}")
                else:
                    errors.append(f"Failed to scrape document: {url} - {scraping_result.error_message}")
                
                # Add delay between requests
                await asyncio.sleep(self.config.get('request_delay', 1.0))
                
            except Exception as e:
                error_msg = f"Error processing {url}: {str(e)}"
                errors.append(error_msg)
                self.logger.error(error_msg)
        
        return {
            'processed': processed,
            'newly_indexed': newly_indexed,
            'updated_indexed': updated_indexed,
            'errors': errors
        }
    
    async def _process_incremental_batch(self, urls: List[str], operation_id: str) -> Dict:
        """Process a batch of URLs for incremental synchronization"""
        processed = 0
        updated_indexed = 0
        errors = []
        
        for url in urls:
            try:
                # Scrape the document
                scraping_result = await self.scraper.scrape_document(url)
                processed += 1
                
                if scraping_result.success:
                    # Create content fingerprint
                    fingerprint = self.change_detector.create_content_fingerprint(
                        url,
                        scraping_result.content,
                        asdict(scraping_result.metadata)
                    )
                    
                    # Check for changes
                    change_event = self.change_detector.detect_changes(url, fingerprint)
                    
                    if change_event:
                        self.logger.info(f"Change detected in {url}: {change_event.change_type}")
                        
                        # Prepare document for indexing
                        document_data = {
                            'url': url,
                            'title': scraping_result.metadata.title,
                            'content': scraping_result.content,
                            'metadata': asdict(scraping_result.metadata)
                        }
                        
                        # Update the document in search index
                        index_success = await self.search_integration.index_document(document_data)
                        
                        if index_success:
                            updated_indexed += 1
                            
                            # Store updated content in blob storage
                            await self._store_content_in_blob(scraping_result)
                        else:
                            errors.append(f"Failed to update index for: {url}")
                
                # Update monitoring schedule
                self.change_detector.update_monitoring_schedule(url)
                
                # Add delay between requests
                await asyncio.sleep(self.config.get('request_delay', 1.0))
                
            except Exception as e:
                error_msg = f"Error processing {url}: {str(e)}"
                errors.append(error_msg)
                self.logger.error(error_msg)
        
        return {
            'processed': processed,
            'updated_indexed': updated_indexed,
            'errors': errors
        }
    
    async def _cleanup_obsolete_documents(self, current_urls: List[str]) -> int:
        """Remove obsolete documents from the search index"""
        try:
            # Get all document IDs currently in the index
            # This is a simplified implementation - in practice, you'd need to
            # query the search index to get all document IDs
            
            # For now, we'll use the fingerprints as a proxy
            stored_urls = set(self.change_detector.content_fingerprints.keys())
            current_url_set = set(current_urls)
            
            # Find URLs that are no longer valid
            obsolete_urls = stored_urls - current_url_set
            
            removed_count = 0
            
            for url in obsolete_urls:
                try:
                    # Generate document ID (same method as used in indexing)
                    import hashlib
                    doc_id = hashlib.sha256(url.encode('utf-8')).hexdigest()
                    
                    # Delete from search index
                    delete_success = await self.search_integration.delete_document(doc_id)
                    
                    if delete_success:
                        removed_count += 1
                        
                        # Remove from change detector
                        if url in self.change_detector.content_fingerprints:
                            del self.change_detector.content_fingerprints[url]
                        
                        if url in self.change_detector.monitoring_schedules:
                            del self.change_detector.monitoring_schedules[url]
                    
                except Exception as e:
                    self.logger.warning(f"Failed to remove obsolete document {url}: {str(e)}")
            
            return removed_count
            
        except Exception as e:
            self.logger.error(f"Error cleaning up obsolete documents: {str(e)}")
            return 0
    
    async def _store_content_in_blob(self, scraping_result: ScrapingResult) -> None:
        """Store scraped content in Azure Blob Storage"""
        try:
            if not self.blob_client or not scraping_result.success:
                return
            
            # Prepare content data
            content_data = {
                'metadata': asdict(scraping_result.metadata),
                'content': scraping_result.content,
                'scraping_result': {
                    'success': scraping_result.success,
                    'processing_time': scraping_result.processing_time,
                    'timestamp': datetime.now().isoformat()
                }
            }
            
            # Create blob name based on URL hash
            url_hash = scraping_result.metadata.content_hash[:16]
            blob_name = f"content/{scraping_result.metadata.source_view}/{url_hash}.json"
            
            # Upload to blob storage
            container_name = self.config.get('content_container', 'scraped-content')
            blob_client = self.blob_client.get_blob_client(
                container=container_name,
                blob=blob_name
            )
            
            content_json = json.dumps(content_data, indent=2)
            blob_client.upload_blob(content_json, overwrite=True)
            
            self.logger.debug(f"Stored content for {scraping_result.metadata.url} in {blob_name}")
            
        except Exception as e:
            self.logger.error(f"Error storing content in blob: {str(e)}")
    
    def _is_valid_url_format(self, url: str) -> bool:
        """Validate URL format"""
        try:
            return (
                url.startswith('https://') and
                'exponenthr.com' in url and
                '#t=' in url
            )
        except:
            return False
    
    def _update_sync_metrics(self, success: bool, execution_time: float) -> None:
        """Update synchronization metrics"""
        try:
            self.sync_metrics['total_syncs'] += 1
            
            if success:
                self.sync_metrics['successful_syncs'] += 1
            else:
                self.sync_metrics['failed_syncs'] += 1
            
            # Update average execution time
            total_time = self.sync_metrics['average_sync_time'] * (self.sync_metrics['total_syncs'] - 1)
            self.sync_metrics['average_sync_time'] = (total_time + execution_time) / self.sync_metrics['total_syncs']
            
        except Exception as e:
            self.logger.error(f"Error updating sync metrics: {str(e)}")
    
    def _get_sync_statistics(self) -> Dict:
        """Get synchronization statistics"""
        try:
            return {
                'total_syncs': self.sync_metrics['total_syncs'],
                'successful_syncs': self.sync_metrics['successful_syncs'],
                'failed_syncs': self.sync_metrics['failed_syncs'],
                'success_rate': (self.sync_metrics['successful_syncs'] / max(self.sync_metrics['total_syncs'], 1)) * 100,
                'average_sync_time': self.sync_metrics['average_sync_time'],
                'last_full_sync': self.last_full_sync.isoformat() if self.last_full_sync else None,
                'last_incremental_sync': self.last_incremental_sync.isoformat() if self.last_incremental_sync else None,
                'active_operations': len(self.active_operations),
                'total_documents': len(self.change_detector.content_fingerprints),
                'monitored_urls': len(self.change_detector.monitoring_schedules)
            }
        except Exception as e:
            self.logger.error(f"Error getting sync statistics: {str(e)}")
            return {}
    
    async def _save_sync_state(self) -> None:
        """Save synchronization state to Azure"""
        try:
            if not self.blob_client:
                return
            
            # Prepare state data
            state_data = {
                'sync_metrics': self.sync_metrics,
                'last_full_sync': self.last_full_sync.isoformat() if self.last_full_sync else None,
                'last_incremental_sync': self.last_incremental_sync.isoformat() if self.last_incremental_sync else None,
                'sync_history': [asdict(result) for result in self.sync_history[-50:]],  # Keep last 50
                'active_operations': {op_id: asdict(op) for op_id, op in self.active_operations.items()},
                'saved_at': datetime.now().isoformat()
            }
            
            # Upload to blob storage
            state_json = json.dumps(state_data, indent=2)
            blob_name = f"sync_state_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            
            blob_client = self.blob_client.get_blob_client(
                container='system-state',
                blob=blob_name
            )
            
            blob_client.upload_blob(state_json, overwrite=True)
            self.logger.info("Synchronization state saved to Azure")
            
        except Exception as e:
            self.logger.error(f"Error saving sync state: {str(e)}")
    
    async def _load_sync_state(self) -> None:
        """Load synchronization state from Azure"""
        try:
            if not self.blob_client:
                return
            
            # Get the latest state file
            container_client = self.blob_client.get_container_client('system-state')
            blobs = list(container_client.list_blobs(name_starts_with='sync_state_'))
            
            if not blobs:
                self.logger.info("No previous sync state found")
                return
            
            # Get the most recent blob
            latest_blob = max(blobs, key=lambda b: b.last_modified)
            
            # Download and parse state data
            blob_client = self.blob_client.get_blob_client(
                container='system-state',
                blob=latest_blob.name
            )
            
            state_json = blob_client.download_blob().readall().decode('utf-8')
            state_data = json.loads(state_json)
            
            # Restore state
            self.sync_metrics = state_data.get('sync_metrics', self.sync_metrics)
            
            if state_data.get('last_full_sync'):
                self.last_full_sync = datetime.fromisoformat(state_data['last_full_sync'])
            
            if state_data.get('last_incremental_sync'):
                self.last_incremental_sync = datetime.fromisoformat(state_data['last_incremental_sync'])
            
            # Restore sync history
            self.sync_history = [
                SyncResult(**result_data)
                for result_data in state_data.get('sync_history', [])
            ]
            
            self.logger.info(f"Loaded sync state from {latest_blob.name}")
            
        except Exception as e:
            self.logger.warning(f"Could not load sync state: {str(e)}")
    
    def get_operation_status(self, operation_id: str) -> Optional[SyncOperation]:
        """Get status of a specific operation"""
        return self.active_operations.get(operation_id)
    
    def get_all_active_operations(self) -> List[SyncOperation]:
        """Get all active operations"""
        return list(self.active_operations.values())
    
    def get_sync_history(self, limit: int = 10) -> List[SyncResult]:
        """Get recent synchronization history"""
        return self.sync_history[-limit:]
    
    async def shutdown(self) -> None:
        """Shutdown the synchronization service"""
        try:
            self.logger.info("Shutting down Synchronization Service...")
            
            # Save current state
            await self._save_sync_state()
            
            # Close browser
            await self.scraper.close_browser()
            
            self.logger.info("Synchronization Service shutdown completed")
            
        except Exception as e:
            self.logger.error(f"Error during shutdown: {str(e)}")


# Example usage and testing
async def main():
    """Example usage of the synchronization service"""
    config = {
        'azure_storage_account_url': 'https://your-storage-account.blob.core.windows.net',
        'azure_search_endpoint': 'https://your-search-service.search.windows.net',
        'azure_search_key': 'your-search-key',
        'openai_api_key': 'your-openai-key',
        'content_container': 'scraped-content',
        'request_delay': 1.0,
        'sync_batch_size': 5,
        'max_concurrent_sync_operations': 2
    }
    
    sync_service = SynchronizationService(config)
    
    try:
        # Initialize the service
        await sync_service.initialize()
        
        # Perform incremental synchronization
        result = await sync_service.perform_incremental_synchronization()
        
        print(f"Synchronization completed:")
        print(f"  Success: {result.success}")
        print(f"  Total processed: {result.total_processed}")
        print(f"  Updated indexed: {result.updated_indexed}")
        print(f"  Errors: {len(result.errors)}")
        print(f"  Execution time: {result.execution_time:.2f} seconds")
        
        # Get statistics
        stats = sync_service._get_sync_statistics()
        print(f"\nSync Statistics:")
        for key, value in stats.items():
            print(f"  {key}: {value}")
    
    finally:
        await sync_service.shutdown()


if __name__ == "__main__":
    asyncio.run(main())

