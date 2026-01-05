"""
MCP Tool Definitions

Defines the seven core tools for the MCP-based Confluence RAG:
1. search_documentation - Hybrid search with reranking
2. read_page - Live content fetch
3. get_child_pages - Page hierarchy navigation
4. get_page_metadata - Page info without content
5. summarize_page - Grounded summarization (single page)
6. answer_from_page - Query-focused extraction (single page)
7. search_and_summarize - Document-grounded synthesis (MAIN TOOL)

These tools are used by both SSE and STDIO transports.
"""

import asyncio
import logging
from typing import Any, Dict, List, Optional

from config.settings import settings
from ingestion.live_fetcher import LiveFetcher
from utils.search import HybridSearcher
from utils.summarizer import (
    get_summarizer,
    summarize_page_async,
    answer_from_page_async,
)
from utils.synthesizer import (
    search_and_summarize as search_and_summarize_sync,
    search_and_summarize_async,
)

logger = logging.getLogger(__name__)


# Lazy-loaded singletons
_searcher: Optional[HybridSearcher] = None
_fetcher: Optional[LiveFetcher] = None


def get_searcher() -> HybridSearcher:
    """Get or create searcher singleton."""
    global _searcher
    if _searcher is None:
        logger.info("Initializing HybridSearcher...")
        _searcher = HybridSearcher()
    return _searcher


def get_fetcher() -> LiveFetcher:
    """Get or create fetcher singleton."""
    global _fetcher
    if _fetcher is None:
        logger.info("Initializing LiveFetcher...")
        _fetcher = LiveFetcher()
    return _fetcher


# ========== Tool Implementations ==========


def search_documentation(
    query: str,
    limit: int = 5,
) -> List[Dict[str, Any]]:
    """
    Search Confluence documentation using hybrid search.
    
    Uses dense + sparse embeddings with Reciprocal Rank Fusion (RRF)
    and FlashRank reranking for optimal results.
    
    Args:
        query: The search query text
        limit: Maximum number of results to return (default: 5)
        
    Returns:
        List of search results, each containing:
        - page_id: Confluence page ID
        - title: Page title
        - url: Page URL
        - score: Relevance score
        - excerpt: Short excerpt from the page
        - space_key: Confluence space key
        - labels: List of page labels
        - headers: List of page headers
    """
    if not query or not query.strip():
        return []
    
    # Clamp limit
    limit = max(1, min(limit, 20))
    
    try:
        searcher = get_searcher()
        results = searcher.search(
            query=query.strip(),
            limit=limit,
            use_rerank=True,
        )
        return [r.to_dict() for r in results]
    except Exception as e:
        logger.error(f"Search failed: {e}")
        return [{"error": str(e)}]


def read_page(page_id: str) -> Dict[str, Any]:
    """
    Fetch the full, live content of a Confluence page.
    
    Content is fetched fresh from Confluence API (not cached),
    converted to Markdown format, and truncated at 12k chars if needed.
    
    Args:
        page_id: The Confluence page ID to fetch
        
    Returns:
        Dictionary containing:
        - page_id: The page ID
        - title: Page title
        - url: Full page URL
        - content: Page content in Markdown format
        - is_truncated: Whether content was truncated
        - last_updated: ISO timestamp of last update
        - labels: List of page labels
        - error: Error message if fetch failed (optional)
    """
    if not page_id or not page_id.strip():
        return {"error": "page_id is required"}
    
    try:
        fetcher = get_fetcher()
        result = fetcher.fetch_page(page_id.strip())
        return result.to_dict()
    except Exception as e:
        logger.error(f"Failed to fetch page {page_id}: {e}")
        return {
            "page_id": page_id,
            "error": str(e),
        }


def get_child_pages(page_id: str, limit: int = 50) -> List[Dict[str, Any]]:
    """
    List all child pages of a given Confluence page.
    
    Use this to navigate the page hierarchy and discover related content.
    
    Args:
        page_id: The parent page ID
        limit: Maximum number of children to return (default: 50)
        
    Returns:
        List of child pages, each containing:
        - page_id: Child page ID
        - title: Child page title
        - url: Child page URL
    """
    if not page_id or not page_id.strip():
        return []
    
    # Clamp limit
    limit = max(1, min(limit, 100))
    
    try:
        fetcher = get_fetcher()
        children = fetcher.get_child_pages(page_id.strip(), limit=limit)
        return children
    except Exception as e:
        logger.error(f"Failed to get children for {page_id}: {e}")
        return [{"error": str(e)}]


def get_page_metadata(page_id: str) -> Dict[str, Any]:
    """
    Get metadata for a Confluence page without fetching content.
    
    Use this for quick page info lookup without the overhead
    of fetching and processing full content.
    
    Args:
        page_id: The Confluence page ID
        
    Returns:
        Dictionary containing:
        - page_id: The page ID
        - title: Page title
        - url: Full page URL
        - space_key: Confluence space key
        - parent_id: Parent page ID (if any)
        - version: Page version number
        - last_updated: ISO timestamp
        - labels: List of page labels
    """
    if not page_id or not page_id.strip():
        return {"error": "page_id is required"}
    
    try:
        fetcher = get_fetcher()
        meta = fetcher.get_page_metadata(page_id.strip())
        
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
        else:
            return {
                "page_id": page_id,
                "error": f"Page not found: {page_id}",
            }
    except Exception as e:
        logger.error(f"Failed to get metadata for {page_id}: {e}")
        return {
            "page_id": page_id,
            "error": str(e),
        }


# ========== Health Check ==========


def health_check() -> Dict[str, Any]:
    """
    Check health of all system components.
    
    Returns:
        Dictionary with component statuses
    """
    status = {
        "status": "healthy",
        "components": {},
    }
    
    # Check Qdrant
    try:
        searcher = get_searcher()
        stats = searcher.get_collection_stats()
        status["components"]["qdrant"] = {
            "status": "ok",
            "collection": stats.get("collection_name"),
            "points_count": stats.get("points_count"),
        }
    except Exception as e:
        status["components"]["qdrant"] = {"status": "error", "error": str(e)}
        status["status"] = "degraded"
    
    # Check Confluence
    try:
        fetcher = get_fetcher()
        homepage = fetcher.client.get_space_homepage_id()
        status["components"]["confluence"] = {
            "status": "ok" if homepage else "warning",
            "space": settings.confluence_space_key,
            "homepage_id": homepage,
        }
    except Exception as e:
        status["components"]["confluence"] = {"status": "error", "error": str(e)}
        status["status"] = "degraded"
    
    return status


# ========== Grounded Summarization Tools ==========


def summarize_page(page_id: str) -> Dict[str, Any]:
    """
    Generate a grounded summary of a Confluence page.
    
    Fetches live content and uses LLM to summarize with strict grounding rules.
    The LLM sees ONLY the document content - no external knowledge is used.
    
    Args:
        page_id: The Confluence page ID to summarize
        
    Returns:
        Dictionary containing:
        - page_id: The page ID
        - title: Page title
        - url: Page URL
        - summary: List of bullet points
        - grounding_score: 0.0-1.0 indicating how grounded the summary is
        - is_grounded: Boolean indicating if summary passes grounding threshold
        - source_sections: Cited sections from the document
        - warning: Warning message if grounding is low (optional)
        - error: Error message if failed (optional)
    """
    if not page_id or not page_id.strip():
        return {"error": "page_id is required"}
    
    try:
        return asyncio.run(summarize_page_async(page_id.strip()))
    except Exception as e:
        logger.error(f"Summarization failed for {page_id}: {e}")
        return {
            "page_id": page_id,
            "error": str(e),
        }


def answer_from_page(page_id: str, question: str) -> Dict[str, Any]:
    """
    Answer a question using ONLY content from a specific Confluence page.
    
    Fetches live content and uses LLM to extract relevant information.
    The LLM sees ONLY the document content - no external knowledge is used.
    If the answer is not in the document, it will explicitly say so.
    
    Args:
        page_id: The Confluence page ID
        question: The question to answer from the page content
        
    Returns:
        Dictionary containing:
        - page_id: The page ID
        - title: Page title
        - url: Page URL
        - question: The original question
        - answer: List of bullet points with citations
        - found_in_document: Boolean indicating if answer was found
        - grounding_score: 0.0-1.0 indicating how grounded the answer is
        - is_grounded: Boolean indicating if answer passes grounding threshold
        - warning: Warning message if grounding is low (optional)
        - error: Error message if failed (optional)
    """
    if not page_id or not page_id.strip():
        return {"error": "page_id is required"}
    if not question or not question.strip():
        return {"error": "question is required"}
    
    try:
        return asyncio.run(answer_from_page_async(page_id.strip(), question.strip()))
    except Exception as e:
        logger.error(f"Answer extraction failed for {page_id}: {e}")
        return {
            "page_id": page_id,
            "question": question,
            "error": str(e),
        }


def search_and_summarize(query: str, max_sources: int = 5) -> Dict[str, Any]:
    """
    🎯 MAIN TOOL: Document-grounded synthesis from user question.
    
    Complete pipeline:
    1. Takes user's question/topic
    2. Searches for relevant Confluence pages
    3. Fetches LIVE content from top results
    4. Combines all content into context
    5. LLM produces grounded summary (sees ONLY docs, NOT the question)
    6. Validates grounding score
    
    CRITICAL: The LLM never sees the user's question - only the documents.
    This prevents hallucination and ensures the summary is purely from sources.
    
    Args:
        query: User's question or topic (e.g., "What is a SWIFT message?")
        max_sources: Maximum number of documents to synthesize (default: 5)
        
    Returns:
        Dictionary containing:
        - query: The original query
        - summary: List of bullet points with [Source: Title] citations
        - sources: List of source documents used [{page_id, title, url}]
        - grounding_score: 0.0-1.0 indicating how grounded the summary is
        - is_grounded: Boolean indicating if summary passes threshold
        - total_sources: Number of documents synthesized
        - warning: Warning message if grounding is low (optional)
        - error: Error message if failed (optional)
    """
    if not query or not query.strip():
        return {"error": "query is required"}
    
    # Clamp max_sources
    max_sources = max(1, min(max_sources, 10))
    
    try:
        return search_and_summarize_sync(query.strip(), max_sources)
    except Exception as e:
        logger.error(f"Synthesis failed for query: {e}")
        return {
            "query": query,
            "error": str(e),
        }


# ========== Tool Registry ==========

TOOLS = {
    "search_documentation": {
        "function": search_documentation,
        "description": "Search Confluence documentation using hybrid search with reranking",
        "parameters": {
            "query": {"type": "string", "description": "Search query text", "required": True},
            "limit": {"type": "integer", "description": "Max results (default: 5)", "required": False},
        },
    },
    "read_page": {
        "function": read_page,
        "description": "Fetch full page content from Confluence (live, not cached)",
        "parameters": {
            "page_id": {"type": "string", "description": "Confluence page ID", "required": True},
        },
    },
    "get_child_pages": {
        "function": get_child_pages,
        "description": "List child pages of a given page",
        "parameters": {
            "page_id": {"type": "string", "description": "Parent page ID", "required": True},
            "limit": {"type": "integer", "description": "Max children (default: 50)", "required": False},
        },
    },
    "get_page_metadata": {
        "function": get_page_metadata,
        "description": "Get page metadata without content",
        "parameters": {
            "page_id": {"type": "string", "description": "Confluence page ID", "required": True},
        },
    },
    "summarize_page": {
        "function": summarize_page,
        "description": "Generate a grounded summary of a page using LLM (no external knowledge)",
        "parameters": {
            "page_id": {"type": "string", "description": "Confluence page ID", "required": True},
        },
    },
    "answer_from_page": {
        "function": answer_from_page,
        "description": "Answer a question using ONLY content from a specific page (grounded extraction)",
        "parameters": {
            "page_id": {"type": "string", "description": "Confluence page ID", "required": True},
            "question": {"type": "string", "description": "Question to answer", "required": True},
        },
    },
    "search_and_summarize": {
        "function": search_and_summarize,
        "description": "🎯 MAIN TOOL: Search docs and produce grounded synthesis. Takes a question, finds relevant pages, fetches live content, produces summary sourced ONLY from documents (no external knowledge).",
        "parameters": {
            "query": {"type": "string", "description": "User question or topic", "required": True},
            "max_sources": {"type": "integer", "description": "Max documents to synthesize (default: 5)", "required": False},
        },
    },
}


if __name__ == "__main__":
    # Quick test
    logging.basicConfig(level=logging.INFO)
    
    print("Testing health check...")
    print(health_check())
    
    print("\nTesting search...")
    results = search_documentation("kafka producer", limit=3)
    for r in results:
        print(f"  - {r.get('title')} (score: {r.get('score', 0):.3f})")
