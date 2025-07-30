"""
ExponentHR Documentation Scraper
A comprehensive web scraping solution for ExponentHR help documentation
that handles dynamic content loading and fragment-based navigation.
"""

import asyncio
import json
import hashlib
import re
import time
import logging
from datetime import datetime
from typing import Dict, List, Set, Optional, Tuple
from urllib.parse import urljoin, urlparse, unquote
from dataclasses import dataclass, asdict

from playwright.async_api import async_playwright, Page, Browser
from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError
from bs4 import BeautifulSoup
import requests
from azure.storage.blob import BlobServiceClient
from azure.identity import DefaultAzureCredential


@dataclass
class DocumentMetadata:
    """Metadata structure for scraped documents"""
    url: str
    title: str
    content_hash: str
    last_modified: str
    content_type: str
    section_hierarchy: List[str]
    word_count: int
    links: List[str]
    images: List[str]
    extraction_timestamp: str
    source_view: str  # 'personal' or 'management'


@dataclass
class ScrapingResult:
    """Result structure for scraping operations"""
    success: bool
    metadata: Optional[DocumentMetadata]
    content: Optional[str]
    error_message: Optional[str]
    processing_time: float


class ExponentHRScraper:
    """
    Main scraper class for ExponentHR documentation system.
    Handles browser automation, content discovery, and data extraction.
    """
    
    def __init__(self, config: Dict):
        """
        Initialize the scraper with configuration parameters.
        
        Args:
            config: Configuration dictionary containing Azure credentials,
                   scraping parameters, and other settings
        """
        self.config = config
        self.logger = self._setup_logging()
        self.discovered_urls: Set[str] = set()
        self.processed_urls: Set[str] = set()
        self.failed_urls: Set[str] = set()
        self.content_cache: Dict[str, DocumentMetadata] = {}
        
        # Azure clients (will be initialized when needed)
        self.blob_client = None
        
        # Browser and page instances
        self.browser: Optional[Browser] = None
        self.page: Optional[Page] = None
        
        # Base URLs for different views
        self.base_urls = {
            'personal': 'https://www.exponenthr.com/service/Help/Online/Exempt/ExponentHR_Personal_View.htm',
            'management': 'https://www.exponenthr.com/service/Help/Online/Exempt/ExponentHR_Management_View.htm'
        }
        
        # URL patterns and fragment structures
        self.url_patterns = {
            'fragment_prefix': '#t=',
            'encoding_map': {
                '/': '%2F',
                ' ': '%20',
                '&': '%26',
                '?': '%3F',
                '#': '%23'
            }
        }
    
    def _setup_logging(self) -> logging.Logger:
        """Setup logging configuration"""
        logger = logging.getLogger('ExponentHRScraper')
        logger.setLevel(logging.INFO)
        
        if not logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            )
            handler.setFormatter(formatter)
            logger.addHandler(handler)
        
        return logger
    
    async def initialize_browser(self) -> None:
        """Initialize Playwright browser instance"""
        # Import the stealth plugin at the top of your file
        from playwright_stealth import stealth_async

        try:
            self.playwright = await async_playwright().start()
            self.browser = await self.playwright.chromium.launch(
                headless=True,
                args=['--no-sandbox', '--disable-dev-shm-usage']
            )

            # Create a new page
            self.page = await self.browser.new_page(
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36'
            )

            # Apply the stealth plugin to the page
            await stealth_async(self.page)

            await self.page.set_viewport_size({"width": 1920, "height": 1080})

            # Set reasonable timeouts
            self.page.set_default_timeout(60000)  # 60 seconds for general actions
            self.page.set_default_navigation_timeout(120000)  # 2 minutes for page navigation

            self.logger.info("Browser initialized successfully with stealth plugin")

        except Exception as e:
            self.logger.error(f"Failed to initialize browser: {str(e)}")
            raise
    
    async def close_browser(self) -> None:
        """Clean up browser resources"""
        try:
            if self.page:
                await self.page.close()
            if self.browser:
                await self.browser.close()
            if hasattr(self, 'playwright'):
                await self.playwright.stop()
            
            self.logger.info("Browser closed successfully")
            
        except Exception as e:
            self.logger.error(f"Error closing browser: {str(e)}")
    
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
    
    async def discover_all_urls(self, view_type: str = 'personal') -> List[str]:
        """
        Discover all available documentation URLs for a specific view.
        
        Args:
            view_type: Either 'personal' or 'management'
            
        Returns:
            List of discovered URLs
        """
        self.logger.info(f"Starting URL discovery for {view_type} view")
        
        if not self.page:
            await self.initialize_browser()
        
        base_url = self.base_urls.get(view_type)
        if not base_url:
            raise ValueError(f"Unknown view type: {view_type}")
        
        try:
            # Navigate to the base URL
            await self.page.goto(base_url, wait_until='networkidle')
            await self.page.wait_for_timeout(3000)  # Wait for dynamic content
            
            # Expand all navigation sections
            await self._expand_navigation_tree()
            
            # Extract all navigation links
            discovered_urls = await self._extract_navigation_urls(view_type)
            
            self.logger.info(f"Discovered {len(discovered_urls)} URLs for {view_type} view")
            return discovered_urls
            
        except Exception as e:
            self.logger.error(f"Error during URL discovery: {str(e)}")
            raise
    
    async def _expand_navigation_tree(self) -> None:
        """Expand all collapsible sections in the navigation tree"""
        try:
            # Look for expand/collapse all button
            expand_button = await self.page.query_selector('a[title*="Expand"]')
            if expand_button:
                await expand_button.click()
                await self.page.wait_for_timeout(2000)
            
            # Look for individual expandable sections
            expandable_elements = await self.page.query_selector_all(
                'li[class*="expandable"], .toc-item[class*="expandable"], [class*="collaps"]'
            )
            
            for element in expandable_elements:
                try:
                    await element.click()
                    await self.page.wait_for_timeout(500)
                except:
                    continue  # Skip if element is not clickable
            
            self.logger.info("Navigation tree expanded")
            
        except Exception as e:
            self.logger.warning(f"Error expanding navigation tree: {str(e)}")
    
    async def _extract_navigation_urls(self, view_type: str) -> List[str]:
        """Extract all navigation URLs from the current page"""
        urls = []
        
        try:
            # Get all links that contain fragment identifiers
            links = await self.page.query_selector_all('a[href*="#t="]')
            
            for link in links:
                href = await link.get_attribute('href')
                text = await link.inner_text()
                
                if href and '#t=' in href:
                    # Clean and validate the URL
                    full_url = urljoin(self.base_urls[view_type], href)
                    
                    # Extract fragment identifier
                    fragment = href.split('#t=')[1] if '#t=' in href else ''
                    
                    if fragment and self._is_valid_content_url(fragment, text):
                        urls.append(full_url)
                        self.discovered_urls.add(full_url)
            
            # Remove duplicates while preserving order
            unique_urls = list(dict.fromkeys(urls))
            
            return unique_urls
            
        except Exception as e:
            self.logger.error(f"Error extracting navigation URLs: {str(e)}")
            return []
    
    def _is_valid_content_url(self, fragment: str, link_text: str) -> bool:
        """
        Validate if a URL fragment represents actual content.
        
        Args:
            fragment: The fragment identifier part of the URL
            link_text: The text content of the link
            
        Returns:
            True if the URL appears to be valid content
        """
        # Skip navigation elements
        skip_patterns = [
            'table of contents',
            'index',
            'glossary',
            'search',
            'print',
            'expand',
            'collapse'
        ]
        
        if any(pattern in link_text.lower() for pattern in skip_patterns):
            return False
        
        # Skip empty or very short fragments
        if len(fragment) < 3:
            return False
        
        # Skip fragments that don't look like file paths
        if not any(char in fragment for char in ['/', '%2F', '.htm']):
            return False
        
        return True
    
    async def scrape_document(self, url: str) -> ScrapingResult:
        """
        Scrape a single document from the given URL.
        
        Args:
            url: The URL to scrape
            
        Returns:
            ScrapingResult containing the scraped content and metadata
        """
        start_time = time.time()
        
        try:
            if not self.page:
                await self.initialize_browser()
            
            self.logger.info(f"Scraping document: {url}")
            
            # Navigate to the URL
            await self.page.goto(url, wait_until='networkidle')
            await self.page.wait_for_timeout(3000)  # Wait for dynamic content
            
            # Extract content and metadata
            content = await self._extract_content()
            metadata = await self._extract_metadata(url, content)
            
            processing_time = time.time() - start_time
            
            self.processed_urls.add(url)
            
            return ScrapingResult(
                success=True,
                metadata=metadata,
                content=content,
                error_message=None,
                processing_time=processing_time
            )
            
        except Exception as e:
            processing_time = time.time() - start_time
            error_msg = f"Error scraping {url}: {str(e)}"
            self.logger.error(error_msg)
            
            self.failed_urls.add(url)
            
            return ScrapingResult(
                success=False,
                metadata=None,
                content=None,
                error_message=error_msg,
                processing_time=processing_time
            )
    
    async def _extract_content(self) -> str:
        """Extract the main content from the current page"""
        try:
            # Wait for content to load
            await self.page.wait_for_selector('body', timeout=10000)
            
            # Get the page HTML
            html_content = await self.page.content()
            
            # Parse with BeautifulSoup for better content extraction
            soup = BeautifulSoup(html_content, 'html.parser')
            
            # Remove navigation, headers, footers, and other non-content elements
            for element in soup.find_all(['nav', 'header', 'footer', 'aside']):
                element.decompose()
            
            # Remove elements with common navigation classes/IDs
            for selector in ['.navigation', '.nav', '.sidebar', '.toc', '#navigation', '#nav']:
                for element in soup.select(selector):
                    element.decompose()
            
            # Find the main content area
            main_content = None
            
            # Try common content selectors
            content_selectors = [
                'main',
                '.content',
                '.main-content',
                '#content',
                '#main-content',
                '.document-content',
                'article'
            ]
            
            for selector in content_selectors:
                main_content = soup.select_one(selector)
                if main_content:
                    break
            
            # If no specific content area found, use body but remove navigation
            if not main_content:
                main_content = soup.find('body')
                if main_content:
                    # Remove known navigation elements
                    for nav_element in main_content.find_all(class_=re.compile(r'nav|toc|sidebar')):
                        nav_element.decompose()
            
            if main_content:
                # Extract text content while preserving some structure
                text_content = self._extract_structured_text(main_content)
                return text_content
            else:
                # Fallback to page text
                return await self.page.inner_text('body')
                
        except Exception as e:
            self.logger.error(f"Error extracting content: {str(e)}")
            return ""
    
    def _extract_structured_text(self, element) -> str:
        """Extract text content while preserving document structure"""
        text_parts = []
        
        for child in element.descendants:
            if child.name in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']:
                text_parts.append(f"\n\n## {child.get_text().strip()}\n")
            elif child.name == 'p':
                text_parts.append(f"\n{child.get_text().strip()}\n")
            elif child.name in ['ul', 'ol']:
                for li in child.find_all('li'):
                    text_parts.append(f"- {li.get_text().strip()}\n")
            elif child.name == 'table':
                # Simple table extraction
                text_parts.append("\n[TABLE]\n")
                for row in child.find_all('tr'):
                    cells = [cell.get_text().strip() for cell in row.find_all(['td', 'th'])]
                    text_parts.append(" | ".join(cells) + "\n")
                text_parts.append("[/TABLE]\n")
            elif child.name in ['div', 'section'] and child.get_text().strip():
                if not any(ancestor.name in ['p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6'] 
                          for ancestor in child.parents):
                    text_parts.append(f"{child.get_text().strip()}\n")
        
        return ''.join(text_parts).strip()
    
    async def _extract_metadata(self, url: str, content: str) -> DocumentMetadata:
        """Extract metadata from the current page and content"""
        try:
            # Get page title
            title = await self.page.title()
            
            # Generate content hash
            content_hash = hashlib.sha256(content.encode('utf-8')).hexdigest()
            
            # Extract section hierarchy from URL
            section_hierarchy = self._extract_section_hierarchy(url)
            
            # Count words
            word_count = len(content.split())
            
            # Extract links
            links = await self._extract_links()
            
            # Extract images
            images = await self._extract_images()
            
            # Determine view type
            view_type = 'personal' if 'Personal_View' in url else 'management'
            
            # Determine content type
            content_type = self._classify_content_type(url, content)
            
            return DocumentMetadata(
                url=url,
                title=title,
                content_hash=content_hash,
                last_modified=datetime.now().isoformat(),
                content_type=content_type,
                section_hierarchy=section_hierarchy,
                word_count=word_count,
                links=links,
                images=images,
                extraction_timestamp=datetime.now().isoformat(),
                source_view=view_type
            )
            
        except Exception as e:
            self.logger.error(f"Error extracting metadata: {str(e)}")
            # Return minimal metadata
            return DocumentMetadata(
                url=url,
                title="Unknown",
                content_hash=hashlib.sha256(content.encode('utf-8')).hexdigest(),
                last_modified=datetime.now().isoformat(),
                content_type="unknown",
                section_hierarchy=[],
                word_count=len(content.split()),
                links=[],
                images=[],
                extraction_timestamp=datetime.now().isoformat(),
                source_view="unknown"
            )
    
    def _extract_section_hierarchy(self, url: str) -> List[str]:
        """Extract section hierarchy from URL fragment"""
        try:
            if '#t=' in url:
                fragment = url.split('#t=')[1]
                # Decode URL encoding
                decoded_fragment = unquote(fragment)
                
                # Split by path separators
                parts = decoded_fragment.replace('/', ' > ').replace('.htm', '').split(' > ')
                
                # Clean up parts
                hierarchy = [part.strip() for part in parts if part.strip()]
                
                return hierarchy
        except:
            pass
        
        return []
    
    async def _extract_links(self) -> List[str]:
        """Extract all links from the current page"""
        try:
            links = []
            link_elements = await self.page.query_selector_all('a[href]')
            
            for link in link_elements:
                href = await link.get_attribute('href')
                if href:
                    links.append(href)
            
            return links
        except:
            return []
    
    async def _extract_images(self) -> List[str]:
        """Extract all image URLs from the current page"""
        try:
            images = []
            img_elements = await self.page.query_selector_all('img[src]')
            
            for img in img_elements:
                src = await img.get_attribute('src')
                if src:
                    images.append(src)
            
            return images
        except:
            return []
    
    def _classify_content_type(self, url: str, content: str) -> str:
        """Classify the type of content based on URL and content analysis"""
        url_lower = url.lower()
        content_lower = content.lower()
        
        if 'faq' in url_lower or 'frequently asked' in content_lower:
            return 'faq'
        elif 'edit' in url_lower or 'change' in url_lower:
            return 'procedure'
        elif 'view' in url_lower and 'information' in url_lower:
            return 'reference'
        elif 'about' in url_lower:
            return 'overview'
        elif any(word in content_lower for word in ['step', 'click', 'select', 'enter']):
            return 'procedure'
        elif len(content.split()) < 100:
            return 'summary'
        else:
            return 'documentation'
    
    def calculate_content_hash(self, content: str) -> str:
        """Calculate SHA-256 hash of content for change detection"""
        return hashlib.sha256(content.encode('utf-8')).hexdigest()
    
    def get_scraping_statistics(self) -> Dict:
        """Get statistics about the scraping process"""
        return {
            'discovered_urls': len(self.discovered_urls),
            'processed_urls': len(self.processed_urls),
            'failed_urls': len(self.failed_urls),
            'success_rate': len(self.processed_urls) / max(len(self.discovered_urls), 1) * 100,
            'cached_documents': len(self.content_cache)
        }


# Example usage and testing functions
async def main():
    """Example usage of the ExponentHR scraper"""
    config = {
        'azure_storage_account_url': 'https://your-storage-account.blob.core.windows.net',
        'max_concurrent_requests': 5,
        'request_delay': 1.0,
        'timeout': 30
    }
    
    scraper = ExponentHRScraper(config)
    
    try:
        # Initialize browser
        await scraper.initialize_browser()
        
        # Discover URLs for personal view
        personal_urls = await scraper.discover_all_urls('personal')
        print(f"Discovered {len(personal_urls)} URLs in personal view")
        
        # Scrape a few documents as examples
        for i, url in enumerate(personal_urls[:3]):  # Limit to first 3 for testing
            result = await scraper.scrape_document(url)
            if result.success:
                print(f"Successfully scraped: {result.metadata.title}")
                print(f"Content length: {len(result.content)} characters")
                print(f"Processing time: {result.processing_time:.2f} seconds")
            else:
                print(f"Failed to scrape: {url}")
                print(f"Error: {result.error_message}")
            print("-" * 50)
        
        # Print statistics
        stats = scraper.get_scraping_statistics()
        print("Scraping Statistics:")
        for key, value in stats.items():
            print(f"  {key}: {value}")
    
    finally:
        await scraper.close_browser()


if __name__ == "__main__":
    asyncio.run(main())

