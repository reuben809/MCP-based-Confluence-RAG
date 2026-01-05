"""
Skeleton Builder - Augmented Skeleton String Generator

Builds the augmented skeleton representation for each Confluence page.
The skeleton captures structural metadata WITHOUT full content:

[TITLE] Page Title
[SPACE] KAFKA
[LABELS] label1, label2
[HEADERS] Header 1 | Header 2 | Header 3
[LINKS] /pages/123, /pages/456
[EXCERPT] First 500 chars of cleaned content...

This skeleton is what gets embedded in the vector DB.
Full content is fetched live at query time.
"""

import hashlib
import logging
import re
from dataclasses import dataclass, field
from typing import List, Optional, Set

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


@dataclass
class PageSkeleton:
    """Augmented skeleton representation of a page."""
    page_id: str
    title: str
    space_key: str
    url: str
    labels: List[str] = field(default_factory=list)
    headers: List[str] = field(default_factory=list)
    internal_links: List[str] = field(default_factory=list)
    excerpt: str = ""
    content_hash: str = ""
    parent_id: Optional[str] = None
    last_updated: str = ""
    version: int = 1
    
    def to_skeleton_text(self) -> str:
        """
        Generate the augmented skeleton string for embedding.
        
        Returns:
            Formatted skeleton text
        """
        parts = [f"[TITLE] {self.title}"]
        
        if self.space_key:
            parts.append(f"[SPACE] {self.space_key}")
            
        if self.labels:
            parts.append(f"[LABELS] {', '.join(self.labels)}")
            
        if self.headers:
            parts.append(f"[HEADERS] {' | '.join(self.headers[:10])}")  # Max 10 headers
            
        if self.internal_links:
            parts.append(f"[LINKS] {', '.join(self.internal_links[:10])}")  # Max 10 links
            
        if self.excerpt:
            parts.append(f"[EXCERPT] {self.excerpt}")
            
        return "\n".join(parts)
    
    def to_payload(self) -> dict:
        """
        Convert to Qdrant payload format.
        
        Returns:
            Dict suitable for Qdrant upsert
        """
        return {
            "page_id": self.page_id,
            "title": self.title,
            "space_key": self.space_key,
            "url": self.url,
            "labels": self.labels,
            "headers": self.headers,
            "internal_links": self.internal_links,
            "excerpt": self.excerpt,
            "content_hash": self.content_hash,
            "parent_id": self.parent_id,
            "last_updated": self.last_updated,
            "version": self.version,
            "skeleton_text": self.to_skeleton_text(),
        }


class SkeletonBuilder:
    """
    Builds augmented skeleton representations from Confluence pages.
    
    The skeleton captures the structure and metadata of a page
    without storing the full content.
    """

    def __init__(
        self,
        base_url: str,
        excerpt_max_chars: int = 500,
        max_headers: int = 20,
        max_links: int = 20,
    ):
        """
        Initialize skeleton builder.
        
        Args:
            base_url: Confluence base URL for link resolution
            excerpt_max_chars: Maximum characters for excerpt
            max_headers: Maximum headers to extract
            max_links: Maximum internal links to extract
        """
        self.base_url = base_url.rstrip("/")
        self.excerpt_max_chars = excerpt_max_chars
        self.max_headers = max_headers
        self.max_links = max_links

    def build_skeleton(
        self,
        page_id: str,
        title: str,
        html_content: str,
        space_key: str,
        url: str,
        labels: Optional[List[str]] = None,
        parent_id: Optional[str] = None,
        last_updated: str = "",
        version: int = 1,
    ) -> PageSkeleton:
        """
        Build a skeleton from page data.
        
        Args:
            page_id: Confluence page ID
            title: Page title
            html_content: Raw HTML content
            space_key: Space key
            url: Page URL
            labels: Page labels/tags
            parent_id: Parent page ID
            last_updated: ISO timestamp of last update
            version: Page version number
            
        Returns:
            PageSkeleton object
        """
        # Parse HTML
        soup = BeautifulSoup(html_content or "", "lxml")
        
        # Remove scripts and styles
        for tag in soup(["script", "style"]):
            tag.decompose()
        
        # Extract components
        headers = self._extract_headers(soup)
        links = self._extract_internal_links(soup)
        excerpt = self._extract_excerpt(soup)
        content_hash = self._compute_hash(html_content or "")
        
        return PageSkeleton(
            page_id=page_id,
            title=title,
            space_key=space_key,
            url=url,
            labels=labels or [],
            headers=headers,
            internal_links=links,
            excerpt=excerpt,
            content_hash=content_hash,
            parent_id=parent_id,
            last_updated=last_updated,
            version=version,
        )

    def _extract_headers(self, soup: BeautifulSoup) -> List[str]:
        """
        Extract header texts from HTML.
        
        Args:
            soup: Parsed BeautifulSoup object
            
        Returns:
            List of header texts
        """
        headers = []
        for tag in soup.find_all(["h1", "h2", "h3", "h4"], limit=self.max_headers * 2):
            text = tag.get_text(strip=True)
            if text and len(text) > 2:
                # Clean up whitespace
                text = re.sub(r"\s+", " ", text)
                headers.append(text[:100])  # Limit header length
                
                if len(headers) >= self.max_headers:
                    break
                    
        return headers

    def _extract_internal_links(self, soup: BeautifulSoup) -> List[str]:
        """
        Extract internal Confluence page links.
        
        Args:
            soup: Parsed BeautifulSoup object
            
        Returns:
            List of page IDs referenced
        """
        links: Set[str] = set()
        
        for a in soup.find_all("a", href=True):
            href = a["href"]
            
            # Match pageId parameter
            match = re.search(r"pageId=(\d+)", href)
            if match:
                links.add(match.group(1))
                continue
                
            # Match /pages/ID format
            match = re.search(r"/pages/(\d+)", href)
            if match:
                links.add(match.group(1))
                continue
                
            # Match /display/SPACE/PAGE format (convert to ID later if needed)
            if "/display/" in href and href.startswith(("/", self.base_url)):
                # Store the path for now
                path = href.replace(self.base_url, "")
                if path and not path.startswith("http"):
                    links.add(path)
        
        return list(links)[: self.max_links]

    def _extract_excerpt(self, soup: BeautifulSoup) -> str:
        """
        Extract a clean excerpt from page content.
        
        Args:
            soup: Parsed BeautifulSoup object
            
        Returns:
            Clean excerpt text
        """
        # Get all text
        text = soup.get_text(separator=" ", strip=True)
        
        # Normalize whitespace
        text = re.sub(r"\s+", " ", text)
        
        # Truncate smartly (don't cut mid-word)
        if len(text) > self.excerpt_max_chars:
            text = text[: self.excerpt_max_chars]
            # Find last space
            last_space = text.rfind(" ")
            if last_space > self.excerpt_max_chars // 2:
                text = text[:last_space]
            text += "..."
            
        return text

    def _compute_hash(self, content: str) -> str:
        """
        Compute content hash for change detection.
        
        Args:
            content: Raw HTML content
            
        Returns:
            MD5 hex digest
        """
        return hashlib.md5(content.encode("utf-8")).hexdigest()

    def should_update(self, old_hash: str, new_content: str) -> bool:
        """
        Check if content has changed based on hash.
        
        Args:
            old_hash: Previously stored content hash
            new_content: New HTML content
            
        Returns:
            True if content has changed
        """
        new_hash = self._compute_hash(new_content)
        return old_hash != new_hash


if __name__ == "__main__":
    # Quick test
    logging.basicConfig(level=logging.INFO)
    
    sample_html = """
    <html>
    <body>
        <h1>Getting Started with Kafka</h1>
        <p>Apache Kafka is a distributed streaming platform. This guide covers installation and basic usage.</p>
        <h2>Installation</h2>
        <p>Download Kafka from the official website.</p>
        <h2>Configuration</h2>
        <p>Configure your broker settings in server.properties.</p>
        <a href="/pages/12345">See Producer Guide</a>
        <a href="/pages/67890">See Consumer Guide</a>
    </body>
    </html>
    """
    
    builder = SkeletonBuilder(base_url="https://cwiki.apache.org/confluence")
    skeleton = builder.build_skeleton(
        page_id="99999",
        title="Getting Started with Kafka",
        html_content=sample_html,
        space_key="KAFKA",
        url="https://cwiki.apache.org/confluence/pages/viewpage.action?pageId=99999",
        labels=["getting-started", "kafka", "tutorial"],
    )
    
    print("=== Skeleton Text ===")
    print(skeleton.to_skeleton_text())
    print("\n=== Payload ===")
    import json
    print(json.dumps(skeleton.to_payload(), indent=2))
