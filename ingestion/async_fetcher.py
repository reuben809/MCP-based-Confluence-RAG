"""
Async Parallel Page Fetcher

Fetches Confluence pages in parallel using asyncio + aiohttp.
Provides 5-10x speedup over synchronous fetching.

Features:
- Configurable concurrency (default: 10 parallel requests)
- Rate limit handling with backoff
- Progress tracking
- Graceful error handling per page
"""

import asyncio
import logging
from dataclasses import dataclass
from typing import List, Optional, Tuple

import aiohttp
from tqdm.asyncio import tqdm

from config.settings import settings

logger = logging.getLogger(__name__)


@dataclass
class FetchResult:
    """Result of fetching a page."""
    page_id: str
    title: str
    url: str
    space_key: str
    parent_id: Optional[str]
    html_content: Optional[str]
    error: Optional[str] = None


class AsyncConfluenceFetcher:
    """
    Async Confluence page fetcher with parallel execution.
    
    Fetches multiple pages concurrently for maximum throughput
    while respecting rate limits.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        pat: Optional[str] = None,
        space_key: Optional[str] = None,
        max_concurrent: int = 10,
        timeout: int = 30,
    ):
        """
        Initialize async fetcher.
        
        Args:
            base_url: Confluence URL
            pat: Personal Access Token or 'anonymous'
            space_key: Space to fetch from
            max_concurrent: Max parallel requests (default 10)
            timeout: Request timeout in seconds
        """
        self.base_url = (base_url or settings.confluence_base_url).rstrip("/")
        self.pat = pat or settings.confluence_pat
        self.space_key = space_key or settings.confluence_space_key
        self.max_concurrent = max_concurrent
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        
        # Rate limiting
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._rate_limit_delay = 0.0
        
    def _get_headers(self) -> dict:
        """Get HTTP headers for requests."""
        headers = {"Accept": "application/json"}
        if self.pat and self.pat.lower() != "anonymous":
            headers["Authorization"] = f"Bearer {self.pat}"
        return headers

    async def _fetch_page_list(
        self,
        session: aiohttp.ClientSession,
        max_pages: Optional[int] = None,
    ) -> List[dict]:
        """
        Fetch list of all pages in space (metadata only).
        
        This is done synchronously since it's paginated
        and we need all page IDs before parallel fetching.
        """
        pages = []
        url = f"{self.base_url}/rest/api/content"
        params = {
            "spaceKey": self.space_key,
            "type": "page",
            "limit": 100,
            "expand": "ancestors",
            "start": 0,
        }
        
        while url and (max_pages is None or len(pages) < max_pages):
            try:
                async with session.get(url, params=params) as response:
                    if response.status == 429:
                        retry_after = int(response.headers.get("Retry-After", 60))
                        logger.warning(f"Rate limited. Waiting {retry_after}s...")
                        await asyncio.sleep(retry_after)
                        continue
                    
                    response.raise_for_status()
                    data = await response.json()
                    
                    for page in data.get("results", []):
                        if max_pages and len(pages) >= max_pages:
                            break
                            
                        ancestors = page.get("ancestors", [])
                        parent_id = ancestors[-1]["id"] if ancestors else None
                        
                        pages.append({
                            "page_id": page["id"],
                            "title": page["title"],
                            "url": f"{self.base_url}/pages/viewpage.action?pageId={page['id']}",
                            "space_key": self.space_key,
                            "parent_id": parent_id,
                        })
                    
                    # Handle pagination
                    next_link = data.get("_links", {}).get("next")
                    if next_link:
                        url = f"{self.base_url}{next_link}"
                        params = None
                    else:
                        break
                        
            except Exception as e:
                logger.error(f"Error fetching page list: {e}")
                break
        
        logger.info(f"Found {len(pages)} pages in space {self.space_key}")
        return pages

    async def _fetch_single_page_content(
        self,
        session: aiohttp.ClientSession,
        page_info: dict,
    ) -> FetchResult:
        """
        Fetch content for a single page.
        
        Uses semaphore for rate limiting.
        """
        page_id = page_info["page_id"]
        
        async with self._semaphore:
            # Apply rate limit delay if needed
            if self._rate_limit_delay > 0:
                await asyncio.sleep(self._rate_limit_delay)
            
            url = f"{self.base_url}/rest/api/content/{page_id}"
            params = {"expand": "body.storage"}
            
            try:
                async with session.get(url, params=params) as response:
                    if response.status == 429:
                        # Rate limited - increase delay for future requests
                        retry_after = int(response.headers.get("Retry-After", 5))
                        self._rate_limit_delay = min(self._rate_limit_delay + 0.5, 2.0)
                        await asyncio.sleep(retry_after)
                        # Retry once
                        async with session.get(url, params=params) as retry_response:
                            retry_response.raise_for_status()
                            data = await retry_response.json()
                    elif response.status == 404:
                        return FetchResult(
                            page_id=page_id,
                            title=page_info["title"],
                            url=page_info["url"],
                            space_key=page_info["space_key"],
                            parent_id=page_info.get("parent_id"),
                            html_content=None,
                            error=f"Page not found: {page_id}",
                        )
                    else:
                        response.raise_for_status()
                        data = await response.json()
                    
                    html_content = data.get("body", {}).get("storage", {}).get("value", "")
                    
                    # Decrease rate limit delay on success
                    self._rate_limit_delay = max(0, self._rate_limit_delay - 0.1)
                    
                    return FetchResult(
                        page_id=page_id,
                        title=page_info["title"],
                        url=page_info["url"],
                        space_key=page_info["space_key"],
                        parent_id=page_info.get("parent_id"),
                        html_content=html_content,
                    )
                    
            except aiohttp.ClientError as e:
                logger.warning(f"Error fetching page {page_id}: {e}")
                return FetchResult(
                    page_id=page_id,
                    title=page_info["title"],
                    url=page_info["url"],
                    space_key=page_info["space_key"],
                    parent_id=page_info.get("parent_id"),
                    html_content=None,
                    error=str(e),
                )

    async def fetch_all_pages_async(
        self,
        max_pages: Optional[int] = None,
        show_progress: bool = True,
    ) -> List[FetchResult]:
        """
        Fetch all pages with content in parallel.
        
        Args:
            max_pages: Maximum pages to fetch
            show_progress: Show progress bar
            
        Returns:
            List of FetchResult with page content
        """
        async with aiohttp.ClientSession(
            headers=self._get_headers(),
            timeout=self.timeout,
        ) as session:
            # Step 1: Get list of all pages (sequential, paginated)
            logger.info("Fetching page list...")
            pages = await self._fetch_page_list(session, max_pages)
            
            if not pages:
                return []
            
            # Step 2: Fetch content for all pages in parallel
            logger.info(f"Fetching content for {len(pages)} pages ({self.max_concurrent} concurrent)...")
            
            tasks = [
                self._fetch_single_page_content(session, page)
                for page in pages
            ]
            
            if show_progress:
                results = await tqdm.gather(
                    *tasks,
                    desc="Fetching pages",
                    total=len(tasks),
                )
            else:
                results = await asyncio.gather(*tasks)
            
            # Count successes and failures
            success = sum(1 for r in results if r.html_content is not None)
            failed = len(results) - success
            
            logger.info(f"Fetch complete. Success: {success}, Failed: {failed}")
            
            return results

    def fetch_all_pages(
        self,
        max_pages: Optional[int] = None,
        show_progress: bool = True,
    ) -> List[FetchResult]:
        """
        Synchronous wrapper for fetch_all_pages_async.
        
        Creates event loop if needed.
        """
        try:
            loop = asyncio.get_running_loop()
            # Already in async context
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                return pool.submit(
                    asyncio.run,
                    self.fetch_all_pages_async(max_pages, show_progress)
                ).result()
        except RuntimeError:
            # No running loop - create one
            return asyncio.run(
                self.fetch_all_pages_async(max_pages, show_progress)
            )


async def run_async_ingestion(
    max_pages: Optional[int] = None,
    max_concurrent: int = 10,
) -> List[FetchResult]:
    """
    Run async page fetching.
    
    Args:
        max_pages: Max pages to fetch
        max_concurrent: Parallel request limit
        
    Returns:
        List of FetchResult
    """
    fetcher = AsyncConfluenceFetcher(max_concurrent=max_concurrent)
    return await fetcher.fetch_all_pages_async(max_pages)


if __name__ == "__main__":
    import time
    
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
    )
    
    print("🚀 Async Parallel Fetch Test")
    print("=" * 50)
    
    start = time.time()
    
    fetcher = AsyncConfluenceFetcher(max_concurrent=10)
    results = fetcher.fetch_all_pages(max_pages=50)
    
    elapsed = time.time() - start
    
    print(f"\n✅ Fetched {len(results)} pages in {elapsed:.1f}s")
    print(f"   Success: {sum(1 for r in results if r.html_content)}")
    print(f"   Failed: {sum(1 for r in results if r.error)}")
    print(f"   Rate: {len(results)/elapsed:.1f} pages/sec")
