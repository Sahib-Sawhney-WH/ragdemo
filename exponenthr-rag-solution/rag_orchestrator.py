"""
RAG Orchestrator for ExponentHR Documentation
Main orchestrator that coordinates scraping, discovery, and change detection.
"""

import asyncio
import json
import logging
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict
import schedule
import time

from exponenthr_scraper import ExponentHRScraper, ScrapingResult
from content_discovery import ContentDiscoveryService
from change_detection import ChangeDetectionSystem, ChangeEvent
from azure.storage.blob import BlobServiceClient
from azure.identity import DefaultAzureCredential


@dataclass
class OrchestrationResult:
    """Result structure for orchestration operations"""
    operation: str
    success: bool
    processed_urls: int
    new_content: int
    updated_content: int
    errors: List[str]
    execution_time: float
    timestamp: str


@dataclass
class SystemStatus:
    """System status information"""
    last_full_scan: Optional[str]
    last_incremental_scan: Optional[str]
    total_documents: int
    monitored_urls: int
    pending_changes: int
    system_health: str
    error_rate: float


class RAGOrchestrator:
    """
    Main orchestrator for the ExponentHR RAG scraping solution.
    Coordinates all components and manages the overall workflow.
    """
    
    def __init__(self, config: Dict):
        """
        Initialize the RAG orchestrator.
        
        Args:
            config: Configuration dictionary
        """
        self.config = config
        self.logger = self._setup_logging()
        
        # Initialize components
        self.scraper = ExponentHRScraper(config)
        self.discovery_service = ContentDiscoveryService(config)
        self.change_detector = ChangeDetectionSystem(config)
        
        # Azure clients
        self.blob_client = None
        
        # Orchestration state
        self.system_status = SystemStatus(
            last_full_scan=None,
            last_incremental_scan=None,
            total_documents=0,
            monitored_urls=0,
            pending_changes=0,
            system_health='unknown',
            error_rate=0.0
        )
        
        # Operation history
        self.operation_history: List[OrchestrationResult] = []
        
        # Scheduling
        self.scheduler_running = False
    
    def _setup_logging(self) -> logging.Logger:
        """Setup logging configuration"""
        logger = logging.getLogger('RAGOrchestrator')
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
        """Initialize all components and Azure services"""
        try:
            self.logger.info("Initializing RAG Orchestrator...")
            
            # Initialize Azure clients
            await self._initialize_azure_clients()
            
            # Initialize scraper
            await self.scraper.initialize_browser()
            
            # Initialize change detector
            self.change_detector.initialize_azure_clients()
            
            # Load previous state if available
            await self._load_system_state()
            
            self.logger.info("RAG Orchestrator initialized successfully")
            
        except Exception as e:
            self.logger.error(f"Failed to initialize RAG Orchestrator: {str(e)}")
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
            
            # Initialize other Azure clients as needed
            self.scraper.initialize_azure_clients()
            
        except Exception as e:
            self.logger.error(f"Failed to initialize Azure clients: {str(e)}")
            raise
    
    async def perform_full_discovery_and_scraping(self, view_types: List[str] = None) -> OrchestrationResult:
        """
        Perform a complete discovery and scraping operation.
        
        Args:
            view_types: List of view types to process ('personal', 'management')
            
        Returns:
            OrchestrationResult with operation details
        """
        start_time = time.time()
        operation = "full_discovery_and_scraping"
        
        if view_types is None:
            view_types = ['personal', 'management']
        
        self.logger.info(f"Starting full discovery and scraping for views: {view_types}")
        
        processed_urls = 0
        new_content = 0
        updated_content = 0
        errors = []
        
        try:
            for view_type in view_types:
                try:
                    # Discover navigation structure
                    self.logger.info(f"Discovering navigation structure for {view_type} view")
                    nav_structure = await self.discovery_service.discover_navigation_structure(
                        self.scraper.page, view_type
                    )
                    
                    # Extract URLs to scrape
                    urls_to_scrape = [
                        link['full_url'] for link in nav_structure.get('all_links', [])
                    ]
                    
                    self.logger.info(f"Found {len(urls_to_scrape)} URLs to scrape for {view_type} view")
                    
                    # Validate URLs
                    validation_results = await self.discovery_service.validate_discovered_urls(
                        self.scraper.page, urls_to_scrape
                    )
                    
                    valid_urls = [url for url, is_valid in validation_results.items() if is_valid]
                    self.logger.info(f"Validated {len(valid_urls)} URLs for scraping")
                    
                    # Scrape each valid URL
                    for url in valid_urls:
                        try:
                            # Scrape the document
                            scraping_result = await self.scraper.scrape_document(url)
                            processed_urls += 1
                            
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
                                    if change_event.change_type == 'new':
                                        new_content += 1
                                    else:
                                        updated_content += 1
                                
                                # Setup monitoring schedule
                                content_type = scraping_result.metadata.content_type
                                self.change_detector.setup_monitoring_schedule(
                                    url, content_type, 'medium'
                                )
                                
                                # Store content in Azure Blob Storage
                                await self._store_content_in_azure(scraping_result)
                                
                            else:
                                errors.append(f"Failed to scrape {url}: {scraping_result.error_message}")
                            
                            # Add delay between requests
                            await asyncio.sleep(self.config.get('request_delay', 1.0))
                            
                        except Exception as e:
                            error_msg = f"Error processing {url}: {str(e)}"
                            errors.append(error_msg)
                            self.logger.error(error_msg)
                    
                except Exception as e:
                    error_msg = f"Error processing {view_type} view: {str(e)}"
                    errors.append(error_msg)
                    self.logger.error(error_msg)
            
            # Update system status
            self.system_status.last_full_scan = datetime.now().isoformat()
            self.system_status.total_documents = len(self.change_detector.content_fingerprints)
            self.system_status.monitored_urls = len(self.change_detector.monitoring_schedules)
            
            execution_time = time.time() - start_time
            
            result = OrchestrationResult(
                operation=operation,
                success=len(errors) == 0,
                processed_urls=processed_urls,
                new_content=new_content,
                updated_content=updated_content,
                errors=errors,
                execution_time=execution_time,
                timestamp=datetime.now().isoformat()
            )
            
            self.operation_history.append(result)
            
            self.logger.info(f"Full discovery and scraping completed: {processed_urls} URLs processed, "
                           f"{new_content} new, {updated_content} updated, {len(errors)} errors")
            
            return result
            
        except Exception as e:
            execution_time = time.time() - start_time
            error_msg = f"Full discovery and scraping failed: {str(e)}"
            errors.append(error_msg)
            self.logger.error(error_msg)
            
            result = OrchestrationResult(
                operation=operation,
                success=False,
                processed_urls=processed_urls,
                new_content=new_content,
                updated_content=updated_content,
                errors=errors,
                execution_time=execution_time,
                timestamp=datetime.now().isoformat()
            )
            
            self.operation_history.append(result)
            return result
    
    async def perform_incremental_update(self) -> OrchestrationResult:
        """
        Perform incremental update by checking URLs due for monitoring.
        
        Returns:
            OrchestrationResult with operation details
        """
        start_time = time.time()
        operation = "incremental_update"
        
        self.logger.info("Starting incremental update")
        
        processed_urls = 0
        new_content = 0
        updated_content = 0
        errors = []
        
        try:
            # Get URLs due for checking
            urls_to_check = self.change_detector.get_urls_due_for_check()
            
            self.logger.info(f"Found {len(urls_to_check)} URLs due for checking")
            
            for url in urls_to_check:
                try:
                    # Scrape the document
                    scraping_result = await self.scraper.scrape_document(url)
                    processed_urls += 1
                    
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
                            if change_event.change_type == 'new':
                                new_content += 1
                            else:
                                updated_content += 1
                            
                            # Store updated content
                            await self._store_content_in_azure(scraping_result)
                            
                            self.logger.info(f"Change detected in {url}: {change_event.change_type}")
                    
                    # Update monitoring schedule
                    self.change_detector.update_monitoring_schedule(url)
                    
                    # Add delay between requests
                    await asyncio.sleep(self.config.get('request_delay', 1.0))
                    
                except Exception as e:
                    error_msg = f"Error checking {url}: {str(e)}"
                    errors.append(error_msg)
                    self.logger.error(error_msg)
            
            # Update system status
            self.system_status.last_incremental_scan = datetime.now().isoformat()
            self.system_status.pending_changes = len(self.change_detector.get_recent_changes(24))
            
            execution_time = time.time() - start_time
            
            result = OrchestrationResult(
                operation=operation,
                success=len(errors) == 0,
                processed_urls=processed_urls,
                new_content=new_content,
                updated_content=updated_content,
                errors=errors,
                execution_time=execution_time,
                timestamp=datetime.now().isoformat()
            )
            
            self.operation_history.append(result)
            
            self.logger.info(f"Incremental update completed: {processed_urls} URLs checked, "
                           f"{updated_content} updated, {len(errors)} errors")
            
            return result
            
        except Exception as e:
            execution_time = time.time() - start_time
            error_msg = f"Incremental update failed: {str(e)}"
            errors.append(error_msg)
            self.logger.error(error_msg)
            
            result = OrchestrationResult(
                operation=operation,
                success=False,
                processed_urls=processed_urls,
                new_content=new_content,
                updated_content=updated_content,
                errors=errors,
                execution_time=execution_time,
                timestamp=datetime.now().isoformat()
            )
            
            self.operation_history.append(result)
            return result
    
    async def _store_content_in_azure(self, scraping_result: ScrapingResult) -> None:
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
            self.logger.error(f"Error storing content in Azure: {str(e)}")
    
    def start_scheduler(self) -> None:
        """Start the background scheduler for automated operations"""
        try:
            if self.scheduler_running:
                self.logger.warning("Scheduler is already running")
                return
            
            # Schedule incremental updates
            schedule.every(self.config.get('incremental_update_hours', 6)).hours.do(
                self._schedule_incremental_update
            )
            
            # Schedule full scans
            schedule.every(self.config.get('full_scan_days', 7)).days.do(
                self._schedule_full_scan
            )
            
            # Schedule cleanup operations
            schedule.every().day.at("02:00").do(self._schedule_cleanup)
            
            self.scheduler_running = True
            self.logger.info("Scheduler started")
            
            # Start scheduler loop
            asyncio.create_task(self._scheduler_loop())
            
        except Exception as e:
            self.logger.error(f"Error starting scheduler: {str(e)}")
    
    def _schedule_incremental_update(self) -> None:
        """Schedule incremental update task"""
        asyncio.create_task(self.perform_incremental_update())
    
    def _schedule_full_scan(self) -> None:
        """Schedule full scan task"""
        asyncio.create_task(self.perform_full_discovery_and_scraping())
    
    def _schedule_cleanup(self) -> None:
        """Schedule cleanup task"""
        asyncio.create_task(self._perform_cleanup())
    
    async def _scheduler_loop(self) -> None:
        """Background scheduler loop"""
        while self.scheduler_running:
            try:
                schedule.run_pending()
                await asyncio.sleep(60)  # Check every minute
            except Exception as e:
                self.logger.error(f"Error in scheduler loop: {str(e)}")
                await asyncio.sleep(60)
    
    def stop_scheduler(self) -> None:
        """Stop the background scheduler"""
        self.scheduler_running = False
        schedule.clear()
        self.logger.info("Scheduler stopped")
    
    async def _perform_cleanup(self) -> None:
        """Perform cleanup operations"""
        try:
            self.logger.info("Performing cleanup operations")
            
            # Clean up old change history
            self.change_detector.cleanup_old_history()
            
            # Clean up old operation history
            cutoff_date = datetime.now() - timedelta(days=30)
            self.operation_history = [
                op for op in self.operation_history
                if datetime.fromisoformat(op.timestamp) >= cutoff_date
            ]
            
            # Save current state
            await self._save_system_state()
            
            self.logger.info("Cleanup operations completed")
            
        except Exception as e:
            self.logger.error(f"Error during cleanup: {str(e)}")
    
    async def _save_system_state(self) -> None:
        """Save system state to Azure"""
        try:
            # Save change detection state
            await self.change_detector.save_state_to_azure()
            
            # Save orchestrator state
            orchestrator_state = {
                'system_status': asdict(self.system_status),
                'operation_history': [asdict(op) for op in self.operation_history[-100:]],  # Keep last 100
                'config': self.config,
                'saved_at': datetime.now().isoformat()
            }
            
            if self.blob_client:
                state_json = json.dumps(orchestrator_state, indent=2)
                blob_name = f"orchestrator_state_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
                
                blob_client = self.blob_client.get_blob_client(
                    container='system-state',
                    blob=blob_name
                )
                
                blob_client.upload_blob(state_json, overwrite=True)
                self.logger.info("System state saved to Azure")
            
        except Exception as e:
            self.logger.error(f"Error saving system state: {str(e)}")
    
    async def _load_system_state(self) -> None:
        """Load system state from Azure"""
        try:
            # Load change detection state
            await self.change_detector.load_state_from_azure()
            
            # Load orchestrator state (implementation would be similar to save)
            # For brevity, this is simplified
            
            self.logger.info("System state loaded from Azure")
            
        except Exception as e:
            self.logger.warning(f"Could not load system state: {str(e)}")
    
    def get_system_status(self) -> SystemStatus:
        """Get current system status"""
        try:
            # Update dynamic status information
            self.system_status.total_documents = len(self.change_detector.content_fingerprints)
            self.system_status.monitored_urls = len(self.change_detector.monitoring_schedules)
            self.system_status.pending_changes = len(self.change_detector.get_recent_changes(24))
            
            # Calculate error rate from recent operations
            recent_ops = [op for op in self.operation_history[-10:]]  # Last 10 operations
            if recent_ops:
                error_count = sum(1 for op in recent_ops if not op.success)
                self.system_status.error_rate = error_count / len(recent_ops)
            
            # Determine system health
            if self.system_status.error_rate < 0.1:
                self.system_status.system_health = 'healthy'
            elif self.system_status.error_rate < 0.3:
                self.system_status.system_health = 'warning'
            else:
                self.system_status.system_health = 'critical'
            
            return self.system_status
            
        except Exception as e:
            self.logger.error(f"Error getting system status: {str(e)}")
            return self.system_status
    
    async def shutdown(self) -> None:
        """Shutdown the orchestrator and clean up resources"""
        try:
            self.logger.info("Shutting down RAG Orchestrator...")
            
            # Stop scheduler
            self.stop_scheduler()
            
            # Save current state
            await self._save_system_state()
            
            # Close browser
            await self.scraper.close_browser()
            
            self.logger.info("RAG Orchestrator shutdown completed")
            
        except Exception as e:
            self.logger.error(f"Error during shutdown: {str(e)}")


# Example usage and testing
async def main():
    """Example usage of the RAG orchestrator"""
    config = {
        'azure_storage_account_url': 'https://your-storage-account.blob.core.windows.net',
        'content_container': 'scraped-content',
        'request_delay': 1.0,
        'incremental_update_hours': 6,
        'full_scan_days': 7
    }
    
    orchestrator = RAGOrchestrator(config)
    
    try:
        # Initialize the system
        await orchestrator.initialize()
        
        # Perform a full discovery and scraping (limited for testing)
        result = await orchestrator.perform_full_discovery_and_scraping(['personal'])
        
        print(f"Operation: {result.operation}")
        print(f"Success: {result.success}")
        print(f"Processed URLs: {result.processed_urls}")
        print(f"New content: {result.new_content}")
        print(f"Updated content: {result.updated_content}")
        print(f"Errors: {len(result.errors)}")
        print(f"Execution time: {result.execution_time:.2f} seconds")
        
        # Get system status
        status = orchestrator.get_system_status()
        print(f"\nSystem Status:")
        print(f"  Total documents: {status.total_documents}")
        print(f"  Monitored URLs: {status.monitored_urls}")
        print(f"  System health: {status.system_health}")
        print(f"  Error rate: {status.error_rate:.2%}")
    
    finally:
        await orchestrator.shutdown()


if __name__ == "__main__":
    asyncio.run(main())

