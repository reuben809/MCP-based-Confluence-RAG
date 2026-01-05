"""
Document-Grounded Synthesis

Complete pipeline for question-to-answer with strict grounding:
1. User asks a question
2. System searches for relevant pages
3. System fetches live content from top results
4. System synthesizes a grounded summary from ALL sources
5. Summary is factual, sourced, with NO external knowledge

Flow:
USER: "What is a SWIFT message and its formats?"
     ↓
SEARCH: Find top 3-5 relevant pages
     ↓
FETCH: Get live content from each page
     ↓
COMBINE: Merge all content into context
     ↓
LLM: Produce grounded summary (ONLY from docs)
     ↓
VALIDATE: Check grounding score
     ↓
RETURN: Summary with citations

Hallucination Prevention:
- LLM sees ONLY the fetched document content
- LLM does NOT see the user's original question (prevents "helpful" additions)
- Strict prompt rules forbid external knowledge
- Token overlap validation catches drift
"""

import asyncio
import logging
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

from config.settings import settings
from ingestion.live_fetcher import LiveFetcher
from utils.llm_client import LLMClient
from utils.search import HybridSearcher

logger = logging.getLogger(__name__)


@dataclass
class SourceDocument:
    """A source document used in synthesis."""
    page_id: str
    title: str
    url: str
    content: str  # Markdown content
    relevance_rank: int


@dataclass 
class SynthesisResult:
    """Result from document-grounded synthesis."""
    query: str
    summary: List[str]  # Bullet points
    sources: List[Dict[str, str]]  # [{page_id, title, url}]
    grounding_score: float
    is_grounded: bool
    total_sources: int
    warning: Optional[str] = None
    error: Optional[str] = None
    
    def to_dict(self) -> dict:
        return {
            "query": self.query,
            "summary": self.summary,
            "sources": self.sources,
            "grounding_score": round(self.grounding_score, 2),
            "is_grounded": self.is_grounded,
            "total_sources": self.total_sources,
            "warning": self.warning,
            "error": self.error,
        }


# ========== Grounding Prompt ==========

# CRITICAL: The user's question is NOT passed to the LLM.
# This prevents the LLM from "helping" with external knowledge.
# The LLM only sees documents and must produce a GENERIC summary.

SYNTHESIS_PROMPT = """You are a document synthesis engine.

YOUR TASK:
Read the documents below and produce a high-level, factual summary of their content.

STRICT RULES:
1. Use ONLY information from the DOCUMENTS section below
2. Do NOT use any external knowledge or prior training
3. Do NOT answer questions - just summarize what the documents say
4. Do NOT infer, assume, or add any information not explicitly stated
5. For each point, cite the source document: [Source: Document Title]
6. If documents contain conflicting information, note both views
7. If documents are empty or unclear, say "Documents contain no extractable content"

OUTPUT FORMAT:
• [Source: Document Title] Key fact or information
• [Source: Document Title] Another key fact
• [Source: Document Title] Additional information

Maximum 10 bullet points. Focus on the most important information.

DOCUMENTS:
{documents}"""


# ========== Grounding Validation ==========

def calculate_grounding_score(response: str, combined_documents: str) -> float:
    """
    Calculate how well the response is grounded in the source documents.
    
    Uses token overlap as a simple but effective metric.
    """
    def tokenize(text: str) -> Set[str]:
        text = re.sub(r"[^\w\s]", " ", text.lower())
        words = set(text.split())
        stop_words = {
            "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
            "have", "has", "had", "do", "does", "did", "will", "would", "could",
            "should", "may", "might", "must", "shall", "can", "to", "of", "in",
            "for", "on", "with", "at", "by", "from", "as", "into", "through",
            "during", "before", "after", "above", "below", "between", "under",
            "and", "but", "or", "nor", "so", "yet", "both", "either", "neither",
            "not", "only", "own", "same", "than", "too", "very", "just", "also",
            "this", "that", "these", "those", "it", "its", "source", "document",
        }
        return words - stop_words
    
    response_tokens = tokenize(response)
    doc_tokens = tokenize(combined_documents)
    
    if not response_tokens:
        return 1.0
    
    overlap = response_tokens & doc_tokens
    return min(len(overlap) / len(response_tokens), 1.0)


def parse_bullet_points(response: str) -> List[str]:
    """Parse bullet points from LLM response."""
    lines = response.strip().split("\n")
    bullets = []
    for line in lines:
        line = line.strip()
        if line.startswith(("•", "-", "*")):
            bullet = line.lstrip("•-*").strip()
            if bullet:
                bullets.append(bullet)
    return bullets


# ========== Main Synthesis Pipeline ==========

class DocumentSynthesizer:
    """
    Complete pipeline for document-grounded synthesis.
    
    Flow:
    1. Search for relevant pages
    2. Fetch live content
    3. Combine into context
    4. Generate grounded summary (LLM sees ONLY docs, not query)
    5. Validate grounding
    """

    def __init__(
        self,
        llm_base_url: Optional[str] = None,
        llm_model: Optional[str] = None,
        max_sources: int = 5,
        max_content_per_source: int = 4000,
        grounding_threshold: float = 0.5,
    ):
        self.llm_url = llm_base_url or settings.llm_base_url
        self.llm_model = llm_model or settings.llm_model
        self.max_sources = max_sources
        self.max_content_per_source = max_content_per_source
        self.grounding_threshold = grounding_threshold
        
        self._llm: Optional[LLMClient] = None
        self._searcher: Optional[HybridSearcher] = None
        self._fetcher: Optional[LiveFetcher] = None

    @property
    def llm(self) -> LLMClient:
        if self._llm is None:
            self._llm = LLMClient(base_url=self.llm_url)
        return self._llm

    @property
    def searcher(self) -> HybridSearcher:
        if self._searcher is None:
            self._searcher = HybridSearcher()
        return self._searcher

    @property
    def fetcher(self) -> LiveFetcher:
        if self._fetcher is None:
            self._fetcher = LiveFetcher()
        return self._fetcher

    async def search_and_summarize(self, query: str, max_sources: Optional[int] = None) -> SynthesisResult:
        """
        Complete pipeline: search → fetch → synthesize.
        
        Args:
            query: User's question/topic
            
        Returns:
            SynthesisResult with grounded summary and sources
        """
        logger.info(f"Starting synthesis for: {query[:50]}...")
        
        if not query or not query.strip():
            return SynthesisResult(
                query=query,
                summary=[],
                sources=[],
                grounding_score=0.0,
                is_grounded=False,
                total_sources=0,
                error="Query is required",
            )
        
        # ========== STEP 1: SEARCH ==========
        logger.info("Step 1: Searching for relevant pages...")
        search_limit = max_sources if max_sources is not None else self.max_sources
        try:
            search_results = self.searcher.search(
                query=query.strip(),
                limit=search_limit,
                use_rerank=True,
            )
        except Exception as e:
            logger.error(f"Search failed: {e}")
            return SynthesisResult(
                query=query,
                summary=[],
                sources=[],
                grounding_score=0.0,
                is_grounded=False,
                total_sources=0,
                error=f"Search failed: {e}",
            )
        
        if not search_results:
            return SynthesisResult(
                query=query,
                summary=["No relevant documents found for this query."],
                sources=[],
                grounding_score=1.0,
                is_grounded=True,
                total_sources=0,
            )
        
        logger.info(f"Found {len(search_results)} relevant pages")
        
        # ========== STEP 2: FETCH LIVE CONTENT ==========
        logger.info("Step 2: Fetching live content from sources...")
        sources: List[SourceDocument] = []
        
        for rank, result in enumerate(search_results, 1):
            try:
                page = self.fetcher.fetch_page(result.page_id)
                if page.error:
                    logger.warning(f"Skipping page {result.page_id}: {page.error}")
                    continue
                
                # Truncate content if too long
                content = page.content
                if len(content) > self.max_content_per_source:
                    content = content[:self.max_content_per_source] + "..."
                
                sources.append(SourceDocument(
                    page_id=result.page_id,
                    title=result.title,
                    url=result.url,
                    content=content,
                    relevance_rank=rank,
                ))
            except Exception as e:
                logger.warning(f"Failed to fetch {result.page_id}: {e}")
                continue
        
        if not sources:
            return SynthesisResult(
                query=query,
                summary=["Could not fetch content from any of the found pages."],
                sources=[],
                grounding_score=1.0,
                is_grounded=True,
                total_sources=0,
                warning="Search found pages but content fetch failed",
            )
        
        logger.info(f"Fetched content from {len(sources)} sources")
        
        # ========== STEP 3: COMBINE DOCUMENTS ==========
        logger.info("Step 3: Combining documents into context...")
        document_sections = []
        for src in sources:
            section = f"--- Document: {src.title} ---\n{src.content}\n"
            document_sections.append(section)
        
        combined_documents = "\n".join(document_sections)
        
        # ========== STEP 4: GENERATE GROUNDED SUMMARY ==========
        # CRITICAL: LLM sees ONLY the documents, NOT the user's query
        # This prevents the LLM from "helping" with external knowledge
        logger.info("Step 4: Generating grounded summary...")
        
        prompt = SYNTHESIS_PROMPT.format(documents=combined_documents)
        
        try:
            response = await self.llm.generate(prompt, model=self.llm_model)
        except Exception as e:
            logger.error(f"LLM generation failed: {e}")
            return SynthesisResult(
                query=query,
                summary=[],
                sources=[{"page_id": s.page_id, "title": s.title, "url": s.url} for s in sources],
                grounding_score=0.0,
                is_grounded=False,
                total_sources=len(sources),
                error=f"LLM error: {e}",
            )
        
        if not response:
            return SynthesisResult(
                query=query,
                summary=[],
                sources=[{"page_id": s.page_id, "title": s.title, "url": s.url} for s in sources],
                grounding_score=0.0,
                is_grounded=False,
                total_sources=len(sources),
                error="LLM returned empty response",
            )
        
        # ========== STEP 5: VALIDATE GROUNDING ==========
        logger.info("Step 5: Validating grounding...")
        bullets = parse_bullet_points(response)
        grounding_score = calculate_grounding_score(response, combined_documents)
        is_grounded = grounding_score >= self.grounding_threshold
        
        warning = None
        if not is_grounded:
            warning = f"Low grounding score ({grounding_score:.2f}). Summary may contain information not from sources."
        
        source_list = [
            {"page_id": s.page_id, "title": s.title, "url": s.url}
            for s in sources
        ]
        
        logger.info(f"Synthesis complete. Grounding score: {grounding_score:.2f}")
        
        return SynthesisResult(
            query=query,
            summary=bullets if bullets else [response.strip()],
            sources=source_list,
            grounding_score=grounding_score,
            is_grounded=is_grounded,
            total_sources=len(sources),
            warning=warning,
        )


# ========== Convenience Functions ==========

def _run_async(coro):
    """
    Run async coroutine safely, handling both sync and async contexts.
    """
    try:
        # Check if we're already in an async context
        loop = asyncio.get_running_loop()
        # We're in an async context - this shouldn't happen for sync wrappers
        # but handle it by creating a new thread
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as pool:
            future = pool.submit(asyncio.run, coro)
            return future.result()
    except RuntimeError:
        # No running loop - safe to use asyncio.run()
        return asyncio.run(coro)


async def search_and_summarize_async(query: str, max_sources: int = 5) -> dict:
    """Async convenience function for MCP tools."""
    # Create synthesizer with the requested max_sources
    synthesizer = DocumentSynthesizer(max_sources=max_sources)
    result = await synthesizer.search_and_summarize(query, max_sources=max_sources)
    return result.to_dict()


def search_and_summarize(query: str, max_sources: int = 5) -> dict:
    """Sync wrapper for MCP tools."""
    return _run_async(search_and_summarize_async(query, max_sources))


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)
    
    if len(sys.argv) < 2:
        print("Usage: python synthesizer.py 'your question here'")
        sys.exit(1)
    
    query = " ".join(sys.argv[1:])
    
    async def test():
        synthesizer = DocumentSynthesizer()
        result = await synthesizer.search_and_summarize(query)
        
        print(f"\n{'='*60}")
        print(f"Query: {result.query}")
        print(f"{'='*60}")
        print(f"\nSources ({result.total_sources}):")
        for src in result.sources:
            print(f"  • {src['title']}")
            print(f"    {src['url']}")
        
        print(f"\nSummary (grounding: {result.grounding_score:.2f}):")
        for bullet in result.summary:
            print(f"  • {bullet}")
        
        if result.warning:
            print(f"\n⚠️ Warning: {result.warning}")
        if result.error:
            print(f"\n❌ Error: {result.error}")
    
    asyncio.run(test())
