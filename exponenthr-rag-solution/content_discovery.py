"""
Content Discovery Service for ExponentHR Documentation
Handles URL pattern recognition, content mapping, and discovery optimization.
"""

import asyncio
import json
import re
import logging
from typing import Dict, List, Set, Optional, Tuple, Pattern
from urllib.parse import urljoin, urlparse, unquote, quote
from dataclasses import dataclass, asdict
from datetime import datetime
import hashlib

from playwright.async_api import Page
from bs4 import BeautifulSoup


@dataclass
class URLPattern:
    """Structure for URL pattern information"""
    pattern: str
    fragment_template: str
    view_type: str
    content_type: str
    examples: List[str]
    confidence_score: float


@dataclass
class ContentMap:
    """Structure for content mapping information"""
    url: str
    title: str
    section_path: List[str]
    parent_url: Optional[str]
    child_urls: List[str]
    content_type: str
    last_discovered: str
    validation_status: str


class ContentDiscoveryService:
    """
    Service for discovering and mapping ExponentHR documentation content.
    Handles URL pattern recognition, content hierarchy mapping, and discovery optimization.
    """
    
    def __init__(self, config: Dict):
        """
        Initialize the content discovery service.
        
        Args:
            config: Configuration dictionary
        """
        self.config = config
        self.logger = self._setup_logging()
        
        # Discovery state
        self.discovered_patterns: List[URLPattern] = []
        self.content_map: Dict[str, ContentMap] = {}
        self.url_validation_cache: Dict[str, bool] = {}
        
        # Base URLs and patterns
        self.base_urls = {
            'personal': 'https://www.exponenthr.com/service/Help/Online/Exempt/ExponentHR_Personal_View.htm',
            'management': 'https://www.exponenthr.com/service/Help/Online/Exempt/ExponentHR_Management_View.htm'
        }
        
        # Known URL patterns from analysis
        self.known_patterns = {
            'accepted_prefix': 'Accepted%2F',
            'direct_topics': [
                'Edit_Direct_Deposit.htm',
                'Edit_Retirement_Plan_Contributions.htm',
                'Edit_W-4_Payroll_Withholding.htm'
            ],
            'encoding_rules': {
                '/': '%2F',
                ' ': '%20',
                '&': '%26',
                '?': '%3F',
                '#': '%23',
                '+': '%2B',
                '=': '%3D'
            }
        }
        
        # Content type classification patterns
        self.content_type_patterns = {
            'procedure': [
                r'edit_.*\.htm',
                r'change_.*\.htm',
                r'update_.*\.htm',
                r'modify_.*\.htm'
            ],
            'reference': [
                r'view_.*\.htm',
                r'display_.*\.htm',
                r'show_.*\.htm'
            ],
            'overview': [
                r'about_.*\.htm',
                r'overview_.*\.htm',
                r'introduction_.*\.htm'
            ],
            'faq': [
                r'faq.*\.htm',
                r'frequently.*\.htm',
                r'questions.*\.htm'
            ]
        }
    
    def _setup_logging(self) -> logging.Logger:
        """Setup logging configuration"""
        logger = logging.getLogger('ContentDiscoveryService')
        logger.setLevel(logging.INFO)
        
        if not logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            )
            handler.setFormatter(formatter)
            logger.addHandler(handler)
        
        return logger
    
    async def discover_navigation_structure(self, page: Page, view_type: str) -> Dict:
        """
        Discover the complete navigation structure for a view.
        
        Args:
            page: Playwright page instance
            view_type: 'personal' or 'management'
            
        Returns:
            Dictionary containing the navigation structure
        """
        self.logger.info(f"Discovering navigation structure for {view_type} view")
        
        try:
            # Navigate to the base URL
            base_url = self.base_urls[view_type]
            await page.goto(base_url, wait_until='networkidle')
            await page.wait_for_timeout(3000)
            
            # Expand all navigation sections
            await self._expand_all_sections(page)
            
            # Extract navigation hierarchy
            navigation_structure = await self._extract_navigation_hierarchy(page, view_type)
            
            # Analyze URL patterns
            patterns = self._analyze_url_patterns(navigation_structure)
            self.discovered_patterns.extend(patterns)
            
            # Build content map
            self._build_content_map(navigation_structure, view_type)
            
            return navigation_structure
            
        except Exception as e:
            self.logger.error(f"Error discovering navigation structure: {str(e)}")
            raise
    
    async def _expand_all_sections(self, page: Page) -> None:
        """Expand all collapsible sections in the navigation"""
        try:
            # Click expand/collapse all button if available
            expand_buttons = await page.query_selector_all('a[title*="Expand"], button[title*="Expand"]')
            for button in expand_buttons:
                try:
                    await button.click()
                    await page.wait_for_timeout(1000)
                except:
                    continue
            
            # Find and expand individual collapsible elements
            collapsible_selectors = [
                'li[class*="collaps"]',
                'div[class*="collaps"]',
                '.expandable',
                '[data-toggle="collapse"]',
                '.tree-node[class*="closed"]'
            ]
            
            for selector in collapsible_selectors:
                elements = await page.query_selector_all(selector)
                for element in elements:
                    try:
                        await element.click()
                        await page.wait_for_timeout(500)
                    except:
                        continue
            
            # Wait for all expansions to complete
            await page.wait_for_timeout(2000)
            
            self.logger.info("Navigation sections expanded")
            
        except Exception as e:
            self.logger.warning(f"Error expanding navigation sections: {str(e)}")
    
    async def _extract_navigation_hierarchy(self, page: Page, view_type: str) -> Dict:
        """Extract the complete navigation hierarchy"""
        try:
            # Get the page HTML for parsing
            html_content = await page.content()
            soup = BeautifulSoup(html_content, 'html.parser')
            
            # Find navigation containers
            nav_containers = self._find_navigation_containers(soup)
            
            hierarchy = {
                'view_type': view_type,
                'base_url': self.base_urls[view_type],
                'sections': [],
                'all_links': [],
                'discovered_at': datetime.now().isoformat()
            }
            
            for container in nav_containers:
                section_data = self._parse_navigation_section(container, view_type)
                if section_data:
                    hierarchy['sections'].append(section_data)
            
            # Extract all links with fragment identifiers
            all_links = soup.find_all('a', href=re.compile(r'#t='))
            for link in all_links:
                link_data = self._parse_navigation_link(link, view_type)
                if link_data:
                    hierarchy['all_links'].append(link_data)
            
            return hierarchy
            
        except Exception as e:
            self.logger.error(f"Error extracting navigation hierarchy: {str(e)}")
            return {}
    
    def _find_navigation_containers(self, soup: BeautifulSoup) -> List:
        """Find navigation containers in the HTML"""
        containers = []
        
        # Common navigation container selectors
        nav_selectors = [
            '.toc',
            '.navigation',
            '.nav-tree',
            '.sidebar',
            '#navigation',
            '#toc',
            'nav',
            '.menu'
        ]
        
        for selector in nav_selectors:
            elements = soup.select(selector)
            containers.extend(elements)
        
        # If no specific containers found, look for lists with links
        if not containers:
            lists = soup.find_all(['ul', 'ol'])
            for lst in lists:
                if lst.find('a', href=re.compile(r'#t=')):
                    containers.append(lst)
        
        return containers
    
    def _parse_navigation_section(self, container, view_type: str) -> Optional[Dict]:
        """Parse a navigation section to extract structure"""
        try:
            section = {
                'title': '',
                'level': 0,
                'items': [],
                'subsections': []
            }
            
            # Try to find section title
            title_elements = container.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6'])
            if title_elements:
                section['title'] = title_elements[0].get_text().strip()
            
            # Parse navigation items
            items = container.find_all('a', href=re.compile(r'#t='))
            for item in items:
                item_data = self._parse_navigation_link(item, view_type)
                if item_data:
                    section['items'].append(item_data)
            
            # Parse nested sections
            nested_lists = container.find_all(['ul', 'ol'])
            for nested_list in nested_lists:
                if nested_list.parent == container:  # Direct child
                    nested_section = self._parse_navigation_section(nested_list, view_type)
                    if nested_section:
                        section['subsections'].append(nested_section)
            
            return section if section['items'] or section['subsections'] else None
            
        except Exception as e:
            self.logger.warning(f"Error parsing navigation section: {str(e)}")
            return None
    
    def _parse_navigation_link(self, link_element, view_type: str) -> Optional[Dict]:
        """Parse a navigation link to extract information"""
        try:
            href = link_element.get('href', '')
            text = link_element.get_text().strip()
            
            if not href or '#t=' not in href:
                return None
            
            # Extract fragment identifier
            fragment = href.split('#t=')[1] if '#t=' in href else ''
            
            # Build full URL
            full_url = urljoin(self.base_urls[view_type], href)
            
            # Decode fragment for analysis
            decoded_fragment = unquote(fragment)
            
            # Extract section path
            section_path = self._extract_section_path(decoded_fragment)
            
            # Classify content type
            content_type = self._classify_content_type(decoded_fragment, text)
            
            return {
                'text': text,
                'href': href,
                'full_url': full_url,
                'fragment': fragment,
                'decoded_fragment': decoded_fragment,
                'section_path': section_path,
                'content_type': content_type,
                'view_type': view_type
            }
            
        except Exception as e:
            self.logger.warning(f"Error parsing navigation link: {str(e)}")
            return None
    
    def _extract_section_path(self, decoded_fragment: str) -> List[str]:
        """Extract hierarchical section path from fragment"""
        try:
            # Remove file extension
            path = decoded_fragment.replace('.htm', '').replace('.html', '')
            
            # Split by common separators
            parts = re.split(r'[/\\]', path)
            
            # Clean up parts
            clean_parts = []
            for part in parts:
                # Convert underscores to spaces and clean up
                clean_part = part.replace('_', ' ').strip()
                if clean_part and clean_part.lower() not in ['accepted', 'default']:
                    clean_parts.append(clean_part)
            
            return clean_parts
            
        except:
            return []
    
    def _classify_content_type(self, fragment: str, text: str) -> str:
        """Classify content type based on fragment and text"""
        fragment_lower = fragment.lower()
        text_lower = text.lower()
        
        # Check against known patterns
        for content_type, patterns in self.content_type_patterns.items():
            for pattern in patterns:
                if re.search(pattern, fragment_lower):
                    return content_type
        
        # Check text content for clues
        if any(word in text_lower for word in ['edit', 'change', 'update', 'modify']):
            return 'procedure'
        elif any(word in text_lower for word in ['view', 'display', 'show']):
            return 'reference'
        elif any(word in text_lower for word in ['about', 'overview', 'introduction']):
            return 'overview'
        elif any(word in text_lower for word in ['faq', 'questions', 'help']):
            return 'faq'
        else:
            return 'documentation'
    
    def _analyze_url_patterns(self, navigation_structure: Dict) -> List[URLPattern]:
        """Analyze discovered URLs to identify patterns"""
        patterns = []
        
        try:
            all_links = navigation_structure.get('all_links', [])
            
            # Group links by pattern characteristics
            pattern_groups = {}
            
            for link in all_links:
                fragment = link.get('decoded_fragment', '')
                content_type = link.get('content_type', 'unknown')
                
                # Create pattern key based on structure
                pattern_key = self._create_pattern_key(fragment)
                
                if pattern_key not in pattern_groups:
                    pattern_groups[pattern_key] = {
                        'examples': [],
                        'content_types': set(),
                        'view_types': set()
                    }
                
                pattern_groups[pattern_key]['examples'].append(link['full_url'])
                pattern_groups[pattern_key]['content_types'].add(content_type)
                pattern_groups[pattern_key]['view_types'].add(link['view_type'])
            
            # Create URLPattern objects
            for pattern_key, group_data in pattern_groups.items():
                if len(group_data['examples']) >= 2:  # Only patterns with multiple examples
                    pattern = URLPattern(
                        pattern=pattern_key,
                        fragment_template=self._create_fragment_template(pattern_key),
                        view_type=list(group_data['view_types'])[0],
                        content_type=list(group_data['content_types'])[0],
                        examples=group_data['examples'][:5],  # Limit examples
                        confidence_score=min(len(group_data['examples']) / 10.0, 1.0)
                    )
                    patterns.append(pattern)
            
            self.logger.info(f"Identified {len(patterns)} URL patterns")
            return patterns
            
        except Exception as e:
            self.logger.error(f"Error analyzing URL patterns: {str(e)}")
            return []
    
    def _create_pattern_key(self, fragment: str) -> str:
        """Create a pattern key for grouping similar URLs"""
        try:
            # Remove specific identifiers and create a pattern
            pattern = fragment
            
            # Replace specific terms with placeholders
            pattern = re.sub(r'\d+', '{ID}', pattern)
            pattern = re.sub(r'[A-Z]{2,}', '{CODE}', pattern)
            
            # Normalize path separators
            pattern = pattern.replace('/', '_')
            
            return pattern
            
        except:
            return fragment
    
    def _create_fragment_template(self, pattern_key: str) -> str:
        """Create a fragment template from a pattern key"""
        # Convert pattern key back to fragment template
        template = pattern_key.replace('_', '/')
        template = template.replace('{ID}', '{id}')
        template = template.replace('{CODE}', '{code}')
        
        return template
    
    def _build_content_map(self, navigation_structure: Dict, view_type: str) -> None:
        """Build a content map from the navigation structure"""
        try:
            all_links = navigation_structure.get('all_links', [])
            
            for link in all_links:
                url = link['full_url']
                
                content_map_entry = ContentMap(
                    url=url,
                    title=link['text'],
                    section_path=link['section_path'],
                    parent_url=None,  # Will be determined later
                    child_urls=[],    # Will be populated later
                    content_type=link['content_type'],
                    last_discovered=datetime.now().isoformat(),
                    validation_status='pending'
                )
                
                self.content_map[url] = content_map_entry
            
            # Build parent-child relationships
            self._build_content_relationships()
            
            self.logger.info(f"Built content map with {len(self.content_map)} entries")
            
        except Exception as e:
            self.logger.error(f"Error building content map: {str(e)}")
    
    def _build_content_relationships(self) -> None:
        """Build parent-child relationships in the content map"""
        try:
            # Sort URLs by section path depth
            sorted_urls = sorted(
                self.content_map.keys(),
                key=lambda url: len(self.content_map[url].section_path)
            )
            
            for url in sorted_urls:
                entry = self.content_map[url]
                
                # Find potential parent
                for parent_url in sorted_urls:
                    parent_entry = self.content_map[parent_url]
                    
                    if (len(parent_entry.section_path) < len(entry.section_path) and
                        self._is_parent_child_relationship(parent_entry.section_path, entry.section_path)):
                        
                        entry.parent_url = parent_url
                        parent_entry.child_urls.append(url)
                        break
            
        except Exception as e:
            self.logger.error(f"Error building content relationships: {str(e)}")
    
    def _is_parent_child_relationship(self, parent_path: List[str], child_path: List[str]) -> bool:
        """Check if two section paths have a parent-child relationship"""
        if len(parent_path) >= len(child_path):
            return False
        
        # Check if parent path is a prefix of child path
        for i, parent_part in enumerate(parent_path):
            if i >= len(child_path) or parent_part.lower() != child_path[i].lower():
                return False
        
        return True
    
    async def validate_discovered_urls(self, page: Page, urls: List[str]) -> Dict[str, bool]:
        """
        Validate that discovered URLs actually contain content.
        
        Args:
            page: Playwright page instance
            urls: List of URLs to validate
            
        Returns:
            Dictionary mapping URLs to validation status
        """
        validation_results = {}
        
        for url in urls:
            if url in self.url_validation_cache:
                validation_results[url] = self.url_validation_cache[url]
                continue
            
            try:
                await page.goto(url, wait_until='networkidle', timeout=15000)
                await page.wait_for_timeout(2000)
                
                # Check if content is loaded
                content = await page.inner_text('body')
                
                # Validate content quality
                is_valid = self._validate_content_quality(content, url)
                
                validation_results[url] = is_valid
                self.url_validation_cache[url] = is_valid
                
                # Update content map
                if url in self.content_map:
                    self.content_map[url].validation_status = 'valid' if is_valid else 'invalid'
                
            except Exception as e:
                self.logger.warning(f"Failed to validate URL {url}: {str(e)}")
                validation_results[url] = False
                self.url_validation_cache[url] = False
                
                if url in self.content_map:
                    self.content_map[url].validation_status = 'error'
        
        return validation_results
    
    def _validate_content_quality(self, content: str, url: str) -> bool:
        """Validate the quality of extracted content"""
        try:
            # Check minimum content length
            if len(content.strip()) < 50:
                return False
            
            # Check for error indicators
            error_indicators = [
                'page not found',
                '404',
                'error',
                'not available',
                'access denied'
            ]
            
            content_lower = content.lower()
            if any(indicator in content_lower for indicator in error_indicators):
                return False
            
            # Check for meaningful content
            word_count = len(content.split())
            if word_count < 10:
                return False
            
            # Check for navigation-only content
            if content_lower.count('click') > word_count * 0.1:  # Too many "click" instructions
                return False
            
            return True
            
        except:
            return False
    
    def generate_urls_from_patterns(self, pattern: URLPattern, parameters: Dict) -> List[str]:
        """
        Generate URLs from discovered patterns with given parameters.
        
        Args:
            pattern: URLPattern to use for generation
            parameters: Dictionary of parameters to substitute
            
        Returns:
            List of generated URLs
        """
        generated_urls = []
        
        try:
            template = pattern.fragment_template
            
            # Substitute parameters in template
            for key, value in parameters.items():
                placeholder = f'{{{key}}}'
                if placeholder in template:
                    template = template.replace(placeholder, str(value))
            
            # Encode the fragment
            encoded_fragment = self._encode_fragment(template)
            
            # Build full URL
            base_url = self.base_urls.get(pattern.view_type, self.base_urls['personal'])
            full_url = f"{base_url}#t={encoded_fragment}"
            
            generated_urls.append(full_url)
            
        except Exception as e:
            self.logger.error(f"Error generating URLs from pattern: {str(e)}")
        
        return generated_urls
    
    def _encode_fragment(self, fragment: str) -> str:
        """Encode fragment identifier according to ExponentHR conventions"""
        # Apply known encoding rules
        encoded = fragment
        for char, encoded_char in self.known_patterns['encoding_rules'].items():
            encoded = encoded.replace(char, encoded_char)
        
        return encoded
    
    def get_discovery_statistics(self) -> Dict:
        """Get statistics about the discovery process"""
        return {
            'discovered_patterns': len(self.discovered_patterns),
            'content_map_entries': len(self.content_map),
            'validated_urls': len([url for url, valid in self.url_validation_cache.items() if valid]),
            'invalid_urls': len([url for url, valid in self.url_validation_cache.items() if not valid]),
            'content_types': list(set(entry.content_type for entry in self.content_map.values())),
            'view_types': list(set(entry.source_view for entry in self.content_map.values() if hasattr(entry, 'source_view')))
        }
    
    def export_discovery_results(self) -> Dict:
        """Export discovery results for persistence or analysis"""
        return {
            'patterns': [asdict(pattern) for pattern in self.discovered_patterns],
            'content_map': {url: asdict(entry) for url, entry in self.content_map.items()},
            'validation_cache': self.url_validation_cache,
            'statistics': self.get_discovery_statistics(),
            'export_timestamp': datetime.now().isoformat()
        }


# Example usage
async def main():
    """Example usage of the content discovery service"""
    from exponenthr_scraper import ExponentHRScraper
    
    config = {
        'max_concurrent_requests': 5,
        'request_delay': 1.0
    }
    
    discovery_service = ContentDiscoveryService(config)
    scraper = ExponentHRScraper(config)
    
    try:
        await scraper.initialize_browser()
        
        # Discover navigation structure for personal view
        nav_structure = await discovery_service.discover_navigation_structure(
            scraper.page, 'personal'
        )
        
        print(f"Discovered {len(nav_structure.get('all_links', []))} links")
        
        # Validate some URLs
        sample_urls = [link['full_url'] for link in nav_structure.get('all_links', [])[:5]]
        validation_results = await discovery_service.validate_discovered_urls(
            scraper.page, sample_urls
        )
        
        print("Validation results:")
        for url, is_valid in validation_results.items():
            print(f"  {url}: {'Valid' if is_valid else 'Invalid'}")
        
        # Print statistics
        stats = discovery_service.get_discovery_statistics()
        print("\nDiscovery Statistics:")
        for key, value in stats.items():
            print(f"  {key}: {value}")
    
    finally:
        await scraper.close_browser()


if __name__ == "__main__":
    asyncio.run(main())

