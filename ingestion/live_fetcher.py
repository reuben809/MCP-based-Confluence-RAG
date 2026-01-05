"""
Live Content Fetcher

Fetches live content from Confluence on-demand.
Converts HTML to Markdown and applies smart truncation.

Features:
- Fresh content fetch (zero staleness)
- HTML → Markdown conversion
- Smart truncation at 12k chars
- Table preservation
- Retry with backoff
- Graceful error handling
"""

import logging
from dataclasses import dataclass
from typing import Optional

from config.settings import settings
from ingestion.confluence_client import ConfluenceClient, PageMetadata
from utils.html_to_markdown import html_to_markdown, smart_truncate

logger = logging.getLogger(__name__)


@dataclass
class PageContent:
    """Full page content returned by live fetcher."""
    page_id: str
    title: str
    url: str
    content: str  # Markdown content
    is_truncated: bool
    last_updated: str
    labels: list
    error: Optional[str] = None
    
    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "page_id": self.page_id,
            "title": self.title,
            "url": self.url,
            "content": self.content,
            "is_truncated": self.is_truncated,
            "last_updated": self.last_updated,
            "labels": self.labels,
            "error": self.error,
        }


class LiveFetcher:
    """
    Fetches live content from Confluence.
    
    Provides on-demand content retrieval with HTML→Markdown conversion
    and intelligent truncation.
    """

    def __init__(
        self,
        confluence_client: Optional[ConfluenceClient] = None,
        max_content_chars: Optional[int] = None,
    ):
        """
        Initialize live fetcher.
        
        Args:
            confluence_client: Confluence API client (creates default if None)
            max_content_chars: Maximum content length (default from settings)
        """
        self.client = confluence_client or ConfluenceClient()
        self.max_chars = max_content_chars or settings.max_content_chars

    def fetch_page(self, page_id: str) -> PageContent:
        """
        Fetch and convert a page to Markdown.
        
        Args:
            page_id: Confluence page ID
            
        Returns:
            PageContent object with Markdown content
        """
        logger.info(f"Fetching live content for page {page_id}")
        
        # Get full page data
        page_data = self.client.get_page_with_content(page_id)
        
        if not page_data:
            return PageContent(
                page_id=page_id,
                title="Unknown",
                url="",
                content="",
                is_truncated=False,
                last_updated="",
                labels=[],
                error=f"Page not found: {page_id}",
            )
        
        # Extract metadata
        title = page_data.get("title", "Untitled")
        url = f"{self.client.base_url}/pages/viewpage.action?pageId={page_id}"
        last_updated = page_data.get("version", {}).get("when", "")
        
        labels = [
            label["name"]
            for label in page_data.get("metadata", {}).get("labels", {}).get("results", [])
        ]
        
        # Get HTML content
        html_content = page_data.get("body", {}).get("storage", {}).get("value", "")
        
        if not html_content:
            return PageContent(
                page_id=page_id,
                title=title,
                url=url,
                content="*This page has no content.*",
                is_truncated=False,
                last_updated=last_updated,
                labels=labels,
            )
        
        # Convert to Markdown
        try:
            markdown = html_to_markdown(html_content)
        except Exception as e:
            logger.error(f"Markdown conversion failed for {page_id}: {e}")
            # Fallback to basic text extraction
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html_content, "lxml")
            markdown = soup.get_text(separator="\n", strip=True)
        
        # Apply truncation if needed
        original_length = len(markdown)
        is_truncated = original_length > self.max_chars
        
        if is_truncated:
            markdown = smart_truncate(
                markdown,
                max_chars=self.max_chars,
                url=url,
            )
            logger.info(f"Truncated content from {original_length} to {len(markdown)} chars")
        
        return PageContent(
            page_id=page_id,
            title=title,
            url=url,
            content=markdown,
            is_truncated=is_truncated,
            last_updated=last_updated,
            labels=labels,
        )

    def get_page_metadata(self, page_id: str) -> Optional[PageMetadata]:
        """
        Get page metadata without content.
        
        Args:
            page_id: Confluence page ID
            
        Returns:
            PageMetadata object or None
        """
        return self.client.get_page_metadata(page_id)

    def get_child_pages(self, page_id: str, limit: int = 50) -> list:
        """
        Get child pages of a given page.
        
        Args:
            page_id: Parent page ID
            limit: Maximum children to return
            
        Returns:
            List of PageSummary objects
        """
        children = self.client.get_child_pages(page_id, limit=limit)
        return [
            {
                "page_id": child.page_id,
                "title": child.title,
                "url": child.url,
            }
            for child in children
        ]


# Convenience functions for MCP tools
def read_page(page_id: str) -> dict:
    """
    Read a page and return its content.
    
    Args:
        page_id: Confluence page ID
        
    Returns:
        Dict with page content
    """
    fetcher = LiveFetcher()
    result = fetcher.fetch_page(page_id)
    return result.to_dict()


def get_child_pages(page_id: str) -> list:
    """
    Get child pages of a given page.
    
    Args:
        page_id: Parent page ID
        
    Returns:
        List of child page summaries
    """
    fetcher = LiveFetcher()
    return fetcher.get_child_pages(page_id)


def get_page_metadata(page_id: str) -> Optional[dict]:
    """
    Get page metadata without content.
    
    Args:
        page_id: Confluence page ID
        
    Returns:
        Dict with metadata or None
    """
    fetcher = LiveFetcher()
    meta = fetcher.get_page_metadata(page_id)
    if meta:
        return {
            "page_id": meta.page_id,
            "title": meta.title,
            "url": meta.url,
            "space_key": meta.space_key,
            "parent_id": meta.parent_id,
            "version": meta.version,
            "last_updated": meta.last_updated,
            "labels": meta.labels,
        }
    return None


if __name__ == "__main__":
    # Quick test
    logging.basicConfig(level=logging.INFO)
    
    # Test with Apache Kafka Confluence (public)
    fetcher = LiveFetcher()
    
    # Get space homepage
    homepage_id = fetcher.client.get_space_homepage_id()
    if homepage_id:
        print(f"Testing with homepage: {homepage_id}")
        
        # Fetch content
        content = fetcher.fetch_page(homepage_id)
        print(f"\nTitle: {content.title}")
        print(f"URL: {content.url}")
        print(f"Labels: {content.labels}")
        print(f"Truncated: {content.is_truncated}")
        print(f"Content preview:\n{content.content[:500]}...")
        
        # Get children
        children = fetcher.get_child_pages(homepage_id, limit=5)
        print(f"\nChild pages ({len(children)}):")
        for child in children:
            print(f"  - {child['title']} ({child['page_id']})")
    else:
        print("Could not get homepage ID")
