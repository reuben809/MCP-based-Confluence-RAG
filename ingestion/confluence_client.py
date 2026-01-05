"""
Confluence REST API Client

Thin wrapper around the Confluence REST API for fetching pages, metadata,
and content. Supports both authenticated and anonymous (public) access.

Features:
- Paginated page listing
- Single page content fetch
- Metadata-only fetch
- Child page enumeration
- Retry with exponential backoff
- Rate limit handling
"""

import logging
import time
from dataclasses import dataclass
from typing import Iterator, List, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from config.settings import settings

logger = logging.getLogger(__name__)


@dataclass
class PageSummary:
    """Lightweight page representation for listings."""
    page_id: str
    title: str
    url: str
    space_key: str
    parent_id: Optional[str] = None


@dataclass
class PageMetadata:
    """Full page metadata without content."""
    page_id: str
    title: str
    url: str
    space_key: str
    parent_id: Optional[str]
    version: int
    last_updated: str
    labels: List[str]


class ConfluenceClient:
    """
    Confluence REST API client with resilient HTTP handling.
    
    Supports both authenticated (PAT) and anonymous access for public Confluence.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        pat: Optional[str] = None,
        space_key: Optional[str] = None,
        timeout: int = 40,
        max_retries: int = 3,
    ):
        """
        Initialize Confluence client.
        
        Args:
            base_url: Confluence instance URL (defaults to settings)
            pat: Personal Access Token or 'anonymous' (defaults to settings)
            space_key: Space key to operate on (defaults to settings)
            timeout: Request timeout in seconds
            max_retries: Maximum retry attempts
        """
        self.base_url = (base_url or settings.confluence_base_url).rstrip("/")
        self.pat = pat or settings.confluence_pat
        self.space_key = space_key or settings.confluence_space_key
        self.timeout = timeout
        
        # Setup session with retry strategy
        self.session = requests.Session()
        
        retry_strategy = Retry(
            total=max_retries,
            backoff_factor=1.5,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET"],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)
        
        # Set headers based on auth mode
        self.session.headers.update({"Accept": "application/json"})
        if self.pat and self.pat.lower() != "anonymous":
            self.session.headers.update({"Authorization": f"Bearer {self.pat}"})
            logger.info(f"Confluence client initialized with PAT auth for {self.base_url}")
        else:
            logger.info(f"Confluence client initialized for anonymous access to {self.base_url}")

    def _safe_request(self, url: str, params: Optional[dict] = None) -> Optional[dict]:
        """
        Execute HTTP GET with error handling.
        
        Args:
            url: Full URL to fetch
            params: Optional query parameters
            
        Returns:
            JSON response as dict, or None on failure
        """
        try:
            response = self.session.get(url, params=params, timeout=self.timeout)
            
            if response.status_code == 429:
                # Rate limited - wait and retry
                retry_after = int(response.headers.get("Retry-After", 60))
                logger.warning(f"Rate limited. Waiting {retry_after}s...")
                time.sleep(retry_after)
                return self._safe_request(url, params)
            
            response.raise_for_status()
            return response.json()
            
        except requests.exceptions.Timeout:
            logger.error(f"Timeout fetching {url}")
            return None
        except requests.exceptions.HTTPError as e:
            logger.error(f"HTTP error {e.response.status_code} for {url}: {e}")
            return None
        except requests.exceptions.RequestException as e:
            logger.error(f"Request error for {url}: {e}")
            return None

    def get_space_homepage_id(self) -> Optional[str]:
        """
        Get the homepage ID for the configured space.
        
        Returns:
            Page ID of space homepage, or None on failure
        """
        url = f"{self.base_url}/rest/api/space/{self.space_key}"
        data = self._safe_request(url, {"expand": "homepage"})
        
        if data and "homepage" in data:
            return data["homepage"]["id"]
        return None

    def get_all_pages(
        self,
        limit: int = 100,
        max_pages: Optional[int] = None,
        expand: str = "version,metadata.labels"
    ) -> Iterator[PageSummary]:
        """
        Iterate over all pages in the space.
        
        Args:
            limit: Results per API call (max 100)
            max_pages: Maximum total pages to return (None = all)
            expand: Fields to expand in response
            
        Yields:
            PageSummary for each page
        """
        url = f"{self.base_url}/rest/api/content"
        params = {
            "spaceKey": self.space_key,
            "type": "page",
            "limit": min(limit, 100),
            "expand": expand,
            "start": 0,
        }
        
        count = 0
        while url:
            data = self._safe_request(url, params)
            if not data:
                break
                
            for page in data.get("results", []):
                if max_pages and count >= max_pages:
                    return
                    
                ancestors = page.get("ancestors", [])
                parent_id = ancestors[-1]["id"] if ancestors else None
                
                yield PageSummary(
                    page_id=page["id"],
                    title=page["title"],
                    url=f"{self.base_url}/pages/viewpage.action?pageId={page['id']}",
                    space_key=self.space_key,
                    parent_id=parent_id,
                )
                count += 1
                
            # Handle pagination
            next_link = data.get("_links", {}).get("next")
            if next_link:
                url = f"{self.base_url}{next_link}"
                params = None  # Next URL includes params
            else:
                break
        
        logger.info(f"Enumerated {count} pages from space {self.space_key}")

    def get_page_content(self, page_id: str) -> Optional[str]:
        """
        Fetch the HTML content of a specific page.
        
        Args:
            page_id: Confluence page ID
            
        Returns:
            HTML content string, or None on failure
        """
        url = f"{self.base_url}/rest/api/content/{page_id}"
        data = self._safe_request(url, {"expand": "body.storage"})
        
        if data:
            return data.get("body", {}).get("storage", {}).get("value", "")
        return None

    def get_page_metadata(self, page_id: str) -> Optional[PageMetadata]:
        """
        Fetch page metadata without content.
        
        Args:
            page_id: Confluence page ID
            
        Returns:
            PageMetadata object, or None on failure
        """
        url = f"{self.base_url}/rest/api/content/{page_id}"
        data = self._safe_request(url, {"expand": "version,ancestors,metadata.labels,space"})
        
        if not data:
            return None
            
        ancestors = data.get("ancestors", [])
        parent_id = ancestors[-1]["id"] if ancestors else None
        
        labels = [
            label["name"] 
            for label in data.get("metadata", {}).get("labels", {}).get("results", [])
        ]
        
        space = data.get("space", {})
        
        return PageMetadata(
            page_id=data["id"],
            title=data["title"],
            url=f"{self.base_url}/pages/viewpage.action?pageId={data['id']}",
            space_key=space.get("key", self.space_key),
            parent_id=parent_id,
            version=data.get("version", {}).get("number", 1),
            last_updated=data.get("version", {}).get("when", ""),
            labels=labels,
        )

    def get_child_pages(self, page_id: str, limit: int = 100) -> List[PageSummary]:
        """
        Get all child pages of a given page.
        
        Args:
            page_id: Parent page ID
            limit: Maximum children to return
            
        Returns:
            List of PageSummary objects for child pages
        """
        url = f"{self.base_url}/rest/api/content/{page_id}/child/page"
        children = []
        
        while url and len(children) < limit:
            data = self._safe_request(url, {"limit": min(100, limit - len(children))})
            if not data:
                break
                
            for page in data.get("results", []):
                children.append(PageSummary(
                    page_id=page["id"],
                    title=page["title"],
                    url=f"{self.base_url}/pages/viewpage.action?pageId={page['id']}",
                    space_key=self.space_key,
                    parent_id=page_id,
                ))
                
            # Handle pagination
            next_link = data.get("_links", {}).get("next")
            url = f"{self.base_url}{next_link}" if next_link else None
            
        return children

    def get_page_with_content(self, page_id: str) -> Optional[dict]:
        """
        Fetch complete page data including content.
        
        Args:
            page_id: Confluence page ID
            
        Returns:
            Full page dict with body.storage.value, or None on failure
        """
        url = f"{self.base_url}/rest/api/content/{page_id}"
        return self._safe_request(url, {
            "expand": "body.storage,version,ancestors,metadata.labels,space"
        })


if __name__ == "__main__":
    # Quick test
    logging.basicConfig(level=logging.INFO)
    client = ConfluenceClient()
    
    print(f"Testing connection to {client.base_url}")
    homepage_id = client.get_space_homepage_id()
    if homepage_id:
        print(f"✅ Space homepage ID: {homepage_id}")
        meta = client.get_page_metadata(homepage_id)
        if meta:
            print(f"✅ Homepage title: {meta.title}")
    else:
        print("❌ Failed to connect")
