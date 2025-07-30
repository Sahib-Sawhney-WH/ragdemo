"""
Change Detection System for ExponentHR Documentation
Monitors content changes, manages update detection, and triggers synchronization.
"""

import asyncio
import json
import hashlib
import logging
from typing import Dict, List, Set, Optional, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict
import schedule
import time

from azure.storage.blob import BlobServiceClient
from azure.identity import DefaultAzureCredential


@dataclass
class ContentFingerprint:
    """Structure for content fingerprinting"""
    url: str
    content_hash: str
    structural_hash: str
    metadata_hash: str
    last_modified: str
    word_count: int
    title: str
    section_count: int
    link_count: int


@dataclass
class ChangeEvent:
    """Structure for change event information"""
    url: str
    change_type: str  # 'content', 'structure', 'metadata', 'new', 'deleted'
    old_fingerprint: Optional[ContentFingerprint]
    new_fingerprint: Optional[ContentFingerprint]
    detected_at: str
    confidence_score: float
    change_details: Dict


@dataclass
class MonitoringSchedule:
    """Structure for monitoring schedule configuration"""
    content_type: str
    frequency_hours: int
    priority: str  # 'high', 'medium', 'low'
    last_check: Optional[str]
    next_check: str


class ChangeDetectionSystem:
    """
    System for detecting changes in ExponentHR documentation.
    Handles content fingerprinting, change detection, and update scheduling.
    """
    
    def __init__(self, config: Dict):
        """
        Initialize the change detection system.
        
        Args:
            config: Configuration dictionary
        """
        self.config = config
        self.logger = self._setup_logging()
        
        # Storage for fingerprints and change history
        self.content_fingerprints: Dict[str, ContentFingerprint] = {}
        self.change_history: List[ChangeEvent] = []
        self.monitoring_schedules: Dict[str, MonitoringSchedule] = {}
        
        # Azure clients
        self.blob_client = None
        
        # Change detection settings
        self.detection_settings = {
            'content_similarity_threshold': 0.95,
            'structural_change_threshold': 0.8,
            'minimum_change_interval_hours': 1,
            'max_history_days': 90
        }
        
        # Monitoring frequency by content type
        self.default_frequencies = {
            'procedure': 6,    # Every 6 hours
            'reference': 24,   # Daily
            'overview': 72,    # Every 3 days
            'faq': 12,         # Every 12 hours
            'documentation': 48  # Every 2 days
        }
    
    def _setup_logging(self) -> logging.Logger:
        """Setup logging configuration"""
        logger = logging.getLogger('ChangeDetectionSystem')
        logger.setLevel(logging.INFO)
        
        if not logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            )
            handler.setFormatter(formatter)
            logger.addHandler(handler)
        
        return logger
    
    def initialize_azure_clients(self) -> None:
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
    
    def create_content_fingerprint(self, url: str, content: str, metadata: Dict) -> ContentFingerprint:
        """
        Create a comprehensive fingerprint for content.
        
        Args:
            url: URL of the content
            content: Text content
            metadata: Content metadata
            
        Returns:
            ContentFingerprint object
        """
        try:
            # Generate content hash
            content_hash = hashlib.sha256(content.encode('utf-8')).hexdigest()
            
            # Generate structural hash (based on headings and structure)
            structural_elements = self._extract_structural_elements(content)
            structural_hash = hashlib.sha256(
                json.dumps(structural_elements, sort_keys=True).encode('utf-8')
            ).hexdigest()
            
            # Generate metadata hash
            metadata_str = json.dumps(metadata, sort_keys=True, default=str)
            metadata_hash = hashlib.sha256(metadata_str.encode('utf-8')).hexdigest()
            
            # Extract content statistics
            word_count = len(content.split())
            section_count = content.count('\n##') + content.count('\n#')
            link_count = content.count('http') + content.count('[')
            
            return ContentFingerprint(
                url=url,
                content_hash=content_hash,
                structural_hash=structural_hash,
                metadata_hash=metadata_hash,
                last_modified=datetime.now().isoformat(),
                word_count=word_count,
                title=metadata.get('title', ''),
                section_count=section_count,
                link_count=link_count
            )
            
        except Exception as e:
            self.logger.error(f"Error creating content fingerprint: {str(e)}")
            raise
    
    def _extract_structural_elements(self, content: str) -> Dict:
        """Extract structural elements from content for fingerprinting"""
        try:
            elements = {
                'headings': [],
                'sections': [],
                'lists': 0,
                'tables': 0
            }
            
            lines = content.split('\n')
            for line in lines:
                line = line.strip()
                
                # Extract headings
                if line.startswith('#'):
                    level = len(line) - len(line.lstrip('#'))
                    heading_text = line.lstrip('#').strip()
                    elements['headings'].append({
                        'level': level,
                        'text': heading_text[:50]  # Truncate for fingerprinting
                    })
                
                # Count structural elements
                if line.startswith('-') or line.startswith('*'):
                    elements['lists'] += 1
                elif '[TABLE]' in line:
                    elements['tables'] += 1
            
            # Extract section structure
            current_section = []
            for heading in elements['headings']:
                if heading['level'] <= 2:  # Major sections
                    if current_section:
                        elements['sections'].append(current_section)
                    current_section = [heading['text']]
                else:
                    current_section.append(heading['text'])
            
            if current_section:
                elements['sections'].append(current_section)
            
            return elements
            
        except Exception as e:
            self.logger.warning(f"Error extracting structural elements: {str(e)}")
            return {}
    
    def detect_changes(self, url: str, new_fingerprint: ContentFingerprint) -> Optional[ChangeEvent]:
        """
        Detect changes by comparing fingerprints.
        
        Args:
            url: URL of the content
            new_fingerprint: New content fingerprint
            
        Returns:
            ChangeEvent if changes detected, None otherwise
        """
        try:
            old_fingerprint = self.content_fingerprints.get(url)
            
            if not old_fingerprint:
                # New content
                change_event = ChangeEvent(
                    url=url,
                    change_type='new',
                    old_fingerprint=None,
                    new_fingerprint=new_fingerprint,
                    detected_at=datetime.now().isoformat(),
                    confidence_score=1.0,
                    change_details={'reason': 'New content discovered'}
                )
                
                self.content_fingerprints[url] = new_fingerprint
                self.change_history.append(change_event)
                
                return change_event
            
            # Check for changes
            changes_detected = []
            change_details = {}
            
            # Content changes
            if old_fingerprint.content_hash != new_fingerprint.content_hash:
                changes_detected.append('content')
                change_details['content_change'] = {
                    'old_word_count': old_fingerprint.word_count,
                    'new_word_count': new_fingerprint.word_count,
                    'word_count_change': new_fingerprint.word_count - old_fingerprint.word_count
                }
            
            # Structural changes
            if old_fingerprint.structural_hash != new_fingerprint.structural_hash:
                changes_detected.append('structure')
                change_details['structural_change'] = {
                    'old_section_count': old_fingerprint.section_count,
                    'new_section_count': new_fingerprint.section_count,
                    'section_count_change': new_fingerprint.section_count - old_fingerprint.section_count
                }
            
            # Metadata changes
            if old_fingerprint.metadata_hash != new_fingerprint.metadata_hash:
                changes_detected.append('metadata')
                change_details['metadata_change'] = {
                    'old_title': old_fingerprint.title,
                    'new_title': new_fingerprint.title
                }
            
            if changes_detected:
                # Calculate confidence score
                confidence_score = self._calculate_change_confidence(
                    old_fingerprint, new_fingerprint, changes_detected
                )
                
                # Determine primary change type
                primary_change_type = self._determine_primary_change_type(changes_detected)
                
                change_event = ChangeEvent(
                    url=url,
                    change_type=primary_change_type,
                    old_fingerprint=old_fingerprint,
                    new_fingerprint=new_fingerprint,
                    detected_at=datetime.now().isoformat(),
                    confidence_score=confidence_score,
                    change_details=change_details
                )
                
                # Update stored fingerprint
                self.content_fingerprints[url] = new_fingerprint
                self.change_history.append(change_event)
                
                return change_event
            
            # No changes detected, update timestamp
            new_fingerprint.last_modified = old_fingerprint.last_modified
            self.content_fingerprints[url] = new_fingerprint
            
            return None
            
        except Exception as e:
            self.logger.error(f"Error detecting changes for {url}: {str(e)}")
            return None
    
    def _calculate_change_confidence(self, old_fp: ContentFingerprint, 
                                   new_fp: ContentFingerprint, 
                                   changes: List[str]) -> float:
        """Calculate confidence score for detected changes"""
        try:
            confidence = 0.0
            
            # Content change confidence
            if 'content' in changes:
                word_change_ratio = abs(new_fp.word_count - old_fp.word_count) / max(old_fp.word_count, 1)
                content_confidence = min(word_change_ratio * 2, 1.0)
                confidence = max(confidence, content_confidence)
            
            # Structural change confidence
            if 'structure' in changes:
                section_change_ratio = abs(new_fp.section_count - old_fp.section_count) / max(old_fp.section_count, 1)
                structural_confidence = min(section_change_ratio * 3, 1.0)
                confidence = max(confidence, structural_confidence)
            
            # Metadata change confidence
            if 'metadata' in changes:
                if old_fp.title != new_fp.title:
                    confidence = max(confidence, 0.8)
                else:
                    confidence = max(confidence, 0.3)
            
            return min(confidence, 1.0)
            
        except:
            return 0.5  # Default confidence
    
    def _determine_primary_change_type(self, changes: List[str]) -> str:
        """Determine the primary change type from detected changes"""
        # Priority order for change types
        priority_order = ['structure', 'content', 'metadata']
        
        for change_type in priority_order:
            if change_type in changes:
                return change_type
        
        return changes[0] if changes else 'unknown'
    
    def setup_monitoring_schedule(self, url: str, content_type: str, priority: str = 'medium') -> None:
        """
        Setup monitoring schedule for a URL.
        
        Args:
            url: URL to monitor
            content_type: Type of content
            priority: Monitoring priority
        """
        try:
            frequency_hours = self.default_frequencies.get(content_type, 24)
            
            # Adjust frequency based on priority
            if priority == 'high':
                frequency_hours = max(frequency_hours // 2, 1)
            elif priority == 'low':
                frequency_hours = frequency_hours * 2
            
            next_check = (datetime.now() + timedelta(hours=frequency_hours)).isoformat()
            
            schedule_entry = MonitoringSchedule(
                content_type=content_type,
                frequency_hours=frequency_hours,
                priority=priority,
                last_check=None,
                next_check=next_check
            )
            
            self.monitoring_schedules[url] = schedule_entry
            
            self.logger.info(f"Setup monitoring for {url}: {frequency_hours}h frequency")
            
        except Exception as e:
            self.logger.error(f"Error setting up monitoring schedule: {str(e)}")
    
    def get_urls_due_for_check(self) -> List[str]:
        """Get list of URLs that are due for monitoring check"""
        due_urls = []
        current_time = datetime.now()
        
        try:
            for url, schedule_entry in self.monitoring_schedules.items():
                next_check_time = datetime.fromisoformat(schedule_entry.next_check)
                
                if current_time >= next_check_time:
                    due_urls.append(url)
            
            # Sort by priority
            def priority_sort_key(url):
                priority = self.monitoring_schedules[url].priority
                priority_values = {'high': 0, 'medium': 1, 'low': 2}
                return priority_values.get(priority, 1)
            
            due_urls.sort(key=priority_sort_key)
            
            return due_urls
            
        except Exception as e:
            self.logger.error(f"Error getting URLs due for check: {str(e)}")
            return []
    
    def update_monitoring_schedule(self, url: str) -> None:
        """Update monitoring schedule after a check"""
        try:
            if url in self.monitoring_schedules:
                schedule_entry = self.monitoring_schedules[url]
                
                current_time = datetime.now()
                schedule_entry.last_check = current_time.isoformat()
                
                next_check_time = current_time + timedelta(hours=schedule_entry.frequency_hours)
                schedule_entry.next_check = next_check_time.isoformat()
                
                self.logger.debug(f"Updated monitoring schedule for {url}")
            
        except Exception as e:
            self.logger.error(f"Error updating monitoring schedule: {str(e)}")
    
    def get_recent_changes(self, hours: int = 24) -> List[ChangeEvent]:
        """Get changes detected in the last N hours"""
        try:
            cutoff_time = datetime.now() - timedelta(hours=hours)
            
            recent_changes = []
            for change in self.change_history:
                change_time = datetime.fromisoformat(change.detected_at)
                if change_time >= cutoff_time:
                    recent_changes.append(change)
            
            # Sort by detection time (newest first)
            recent_changes.sort(key=lambda x: x.detected_at, reverse=True)
            
            return recent_changes
            
        except Exception as e:
            self.logger.error(f"Error getting recent changes: {str(e)}")
            return []
    
    def get_change_statistics(self) -> Dict:
        """Get statistics about detected changes"""
        try:
            stats = {
                'total_monitored_urls': len(self.monitoring_schedules),
                'total_fingerprints': len(self.content_fingerprints),
                'total_changes': len(self.change_history),
                'changes_by_type': {},
                'changes_last_24h': 0,
                'changes_last_week': 0,
                'average_confidence': 0.0
            }
            
            # Count changes by type
            for change in self.change_history:
                change_type = change.change_type
                stats['changes_by_type'][change_type] = stats['changes_by_type'].get(change_type, 0) + 1
            
            # Count recent changes
            now = datetime.now()
            day_ago = now - timedelta(days=1)
            week_ago = now - timedelta(days=7)
            
            confidences = []
            for change in self.change_history:
                change_time = datetime.fromisoformat(change.detected_at)
                confidences.append(change.confidence_score)
                
                if change_time >= day_ago:
                    stats['changes_last_24h'] += 1
                if change_time >= week_ago:
                    stats['changes_last_week'] += 1
            
            # Calculate average confidence
            if confidences:
                stats['average_confidence'] = sum(confidences) / len(confidences)
            
            return stats
            
        except Exception as e:
            self.logger.error(f"Error calculating change statistics: {str(e)}")
            return {}
    
    def cleanup_old_history(self, days: int = None) -> None:
        """Clean up old change history entries"""
        try:
            if days is None:
                days = self.detection_settings['max_history_days']
            
            cutoff_time = datetime.now() - timedelta(days=days)
            
            original_count = len(self.change_history)
            self.change_history = [
                change for change in self.change_history
                if datetime.fromisoformat(change.detected_at) >= cutoff_time
            ]
            
            removed_count = original_count - len(self.change_history)
            if removed_count > 0:
                self.logger.info(f"Cleaned up {removed_count} old change history entries")
            
        except Exception as e:
            self.logger.error(f"Error cleaning up old history: {str(e)}")
    
    async def save_state_to_azure(self, container_name: str = 'change-detection') -> None:
        """Save change detection state to Azure Blob Storage"""
        try:
            if not self.blob_client:
                self.initialize_azure_clients()
            
            # Prepare state data
            state_data = {
                'fingerprints': {url: asdict(fp) for url, fp in self.content_fingerprints.items()},
                'change_history': [asdict(change) for change in self.change_history],
                'monitoring_schedules': {url: asdict(schedule) for url, schedule in self.monitoring_schedules.items()},
                'saved_at': datetime.now().isoformat()
            }
            
            # Convert to JSON
            state_json = json.dumps(state_data, indent=2)
            
            # Upload to blob storage
            blob_name = f"change_detection_state_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            blob_client = self.blob_client.get_blob_client(
                container=container_name,
                blob=blob_name
            )
            
            blob_client.upload_blob(state_json, overwrite=True)
            
            self.logger.info(f"Saved change detection state to {blob_name}")
            
        except Exception as e:
            self.logger.error(f"Error saving state to Azure: {str(e)}")
    
    async def load_state_from_azure(self, container_name: str = 'change-detection', 
                                  blob_name: str = None) -> None:
        """Load change detection state from Azure Blob Storage"""
        try:
            if not self.blob_client:
                self.initialize_azure_clients()
            
            # If no specific blob name, get the latest
            if not blob_name:
                container_client = self.blob_client.get_container_client(container_name)
                blobs = list(container_client.list_blobs(name_starts_with='change_detection_state_'))
                if not blobs:
                    self.logger.warning("No saved state found in Azure")
                    return
                
                # Get the most recent blob
                latest_blob = max(blobs, key=lambda b: b.last_modified)
                blob_name = latest_blob.name
            
            # Download and parse state data
            blob_client = self.blob_client.get_blob_client(
                container=container_name,
                blob=blob_name
            )
            
            state_json = blob_client.download_blob().readall().decode('utf-8')
            state_data = json.loads(state_json)
            
            # Restore state
            self.content_fingerprints = {
                url: ContentFingerprint(**fp_data)
                for url, fp_data in state_data.get('fingerprints', {}).items()
            }
            
            self.change_history = [
                ChangeEvent(**change_data)
                for change_data in state_data.get('change_history', [])
            ]
            
            self.monitoring_schedules = {
                url: MonitoringSchedule(**schedule_data)
                for url, schedule_data in state_data.get('monitoring_schedules', {}).items()
            }
            
            self.logger.info(f"Loaded change detection state from {blob_name}")
            
        except Exception as e:
            self.logger.error(f"Error loading state from Azure: {str(e)}")


# Example usage and testing
async def main():
    """Example usage of the change detection system"""
    config = {
        'azure_storage_account_url': 'https://your-storage-account.blob.core.windows.net'
    }
    
    change_detector = ChangeDetectionSystem(config)
    
    # Example content for testing
    test_content = """
    # Edit Direct Deposit
    
    This page allows you to edit your direct deposit information.
    
    ## Steps to Edit
    1. Click on the Edit button
    2. Enter your bank information
    3. Submit the changes
    """
    
    test_metadata = {
        'title': 'Edit Direct Deposit',
        'url': 'https://example.com/edit_direct_deposit',
        'content_type': 'procedure'
    }
    
    # Create fingerprint
    fingerprint = change_detector.create_content_fingerprint(
        test_metadata['url'],
        test_content,
        test_metadata
    )
    
    print(f"Created fingerprint for: {fingerprint.title}")
    print(f"Content hash: {fingerprint.content_hash[:16]}...")
    print(f"Word count: {fingerprint.word_count}")
    
    # Setup monitoring
    change_detector.setup_monitoring_schedule(
        test_metadata['url'],
        test_metadata['content_type'],
        'high'
    )
    
    # Simulate content change
    modified_content = test_content + "\n\n## Additional Information\nNew section added."
    
    new_fingerprint = change_detector.create_content_fingerprint(
        test_metadata['url'],
        modified_content,
        test_metadata
    )
    
    # Detect changes
    change_event = change_detector.detect_changes(test_metadata['url'], new_fingerprint)
    
    if change_event:
        print(f"\nChange detected!")
        print(f"Change type: {change_event.change_type}")
        print(f"Confidence: {change_event.confidence_score:.2f}")
        print(f"Details: {change_event.change_details}")
    
    # Print statistics
    stats = change_detector.get_change_statistics()
    print(f"\nChange Detection Statistics:")
    for key, value in stats.items():
        print(f"  {key}: {value}")


if __name__ == "__main__":
    asyncio.run(main())

