"""
Grounded Summarization Service

Provides LLM-based summarization with strict grounding constraints.
Two modes:
1. Generic summarization (no query) - pure document summary
2. Query-focused extraction (with query) - answer from document

Key features:
- Strict prompts that prevent hallucination
- Token overlap validation for grounding
- Citation tracking
- "Not found" handling for missing information
"""

import asyncio
import logging
import re
from dataclasses import dataclass, field
from typing import List, Optional, Set

from config.settings import settings
from ingestion.live_fetcher import LiveFetcher
from utils.llm_client import LLMClient

logger = logging.getLogger(__name__)


# ========== Response Types ==========

@dataclass
class SummaryResult:
    """Result from summarization."""
    page_id: str
    title: str
    url: str
    summary: List[str]  # Bullet points
    grounding_score: float
    is_grounded: bool
    source_sections: List[str] = field(default_factory=list)
    warning: Optional[str] = None
    error: Optional[str] = None
    
    def to_dict(self) -> dict:
        return {
            "page_id": self.page_id,
            "title": self.title,
            "url": self.url,
            "summary": self.summary,
            "grounding_score": round(self.grounding_score, 2),
            "is_grounded": self.is_grounded,
            "source_sections": self.source_sections,
            "warning": self.warning,
            "error": self.error,
        }


@dataclass
class AnswerResult:
    """Result from query-focused extraction."""
    page_id: str
    title: str
    url: str
    question: str
    answer: List[str]  # Bullet points with citations
    found_in_document: bool
    grounding_score: float
    is_grounded: bool
    warning: Optional[str] = None
    error: Optional[str] = None
    
    def to_dict(self) -> dict:
        return {
            "page_id": self.page_id,
            "title": self.title,
            "url": self.url,
            "question": self.question,
            "answer": self.answer,
            "found_in_document": self.found_in_document,
            "grounding_score": round(self.grounding_score, 2),
            "is_grounded": self.is_grounded,
            "warning": self.warning,
            "error": self.error,
        }


# ========== Prompts ==========

SUMMARIZE_SYSTEM_PROMPT = """You are a document summarization engine.

STRICT RULES:
1. Use ONLY information from the DOCUMENT below
2. Do NOT use external knowledge or prior training
3. Do NOT infer, assume, or add any information
4. For each point, cite the section in [brackets]
5. If the document is empty or unclear, say "Document contains no extractable content"
6. Maximum 10 bullet points

OUTPUT FORMAT (one per line):
- [Section Name] Key fact or information
- [Section Name] Another key fact

DOCUMENT:
\"\"\"
{content}
\"\"\""""

ANSWER_SYSTEM_PROMPT = """You are a document extraction engine answering a specific question.

STRICT RULES:
1. Use ONLY information from the DOCUMENT below
2. Do NOT use external knowledge or prior training
3. If the answer is NOT in the document, respond ONLY with: "NOT_FOUND: The document does not contain information about this."
4. For each point, cite the section in [brackets]
5. Do NOT infer or make assumptions
6. Maximum 5 bullet points

QUESTION: {question}

OUTPUT FORMAT (one per line):
- [Section Name] Relevant information
- [Section Name] Another relevant point
OR if not found:
NOT_FOUND: The document does not contain information about this.

DOCUMENT:
\"\"\"
{content}
\"\"\""""


# ========== Grounding Validation ==========

def calculate_grounding_score(response: str, document: str) -> float:
    """
    Calculate how well the response is grounded in the document.
    
    Uses token overlap as a simple but effective metric.
    Score 0.0-1.0 where higher is better grounded.
    """
    # Tokenize (simple word-based)
    def tokenize(text: str) -> Set[str]:
        # Remove punctuation, lowercase, split
        text = re.sub(r"[^\w\s]", " ", text.lower())
        words = set(text.split())
        # Remove common stop words
        stop_words = {"the", "a", "an", "is", "are", "was", "were", "be", "been",
                      "being", "have", "has", "had", "do", "does", "did", "will",
                      "would", "could", "should", "may", "might", "must", "shall",
                      "can", "need", "dare", "ought", "used", "to", "of", "in",
                      "for", "on", "with", "at", "by", "from", "as", "into",
                      "through", "during", "before", "after", "above", "below",
                      "between", "under", "again", "further", "then", "once",
                      "and", "but", "or", "nor", "so", "yet", "both", "either",
                      "neither", "not", "only", "own", "same", "than", "too",
                      "very", "just", "also", "now", "here", "there", "when",
                      "where", "why", "how", "all", "each", "every", "any",
                      "this", "that", "these", "those", "it", "its"}
        return words - stop_words
    
    response_tokens = tokenize(response)
    document_tokens = tokenize(document)
    
    if not response_tokens:
        return 1.0  # Empty response is technically grounded
    
    # Calculate overlap
    overlap = response_tokens & document_tokens
    score = len(overlap) / len(response_tokens)
    
    return min(score, 1.0)


def extract_citations(response: str) -> List[str]:
    """Extract [Section Name] citations from response."""
    citations = re.findall(r"\[([^\]]+)\]", response)
    return list(set(citations))


def parse_bullet_points(response: str) -> List[str]:
    """Parse bullet points from LLM response."""
    lines = response.strip().split("\n")
    bullets = []
    for line in lines:
        line = line.strip()
        if line.startswith("-") or line.startswith("•"):
            bullets.append(line.lstrip("-•").strip())
        elif line.startswith("*"):
            bullets.append(line.lstrip("*").strip())
    return bullets


# ========== Summarization Service ==========

class GroundedSummarizer:
    """
    Provides grounded summarization using LLM.
    
    Two modes:
    1. summarize_page() - Generic summary of entire document
    2. answer_from_page() - Query-focused extraction
    """

    def __init__(
        self,
        llm_base_url: Optional[str] = None,
        llm_model: Optional[str] = None,
        grounding_threshold: float = 0.5,
    ):
        """
        Initialize summarizer.
        
        Args:
            llm_base_url: LLM server URL (default from settings)
            llm_model: Model name/ID (default from settings)
            grounding_threshold: Min score to consider grounded (0.0-1.0)
        """
        self.llm_url = llm_base_url or settings.llm_base_url
        self.llm_model = llm_model or settings.llm_model
        self.grounding_threshold = grounding_threshold
        
        self._llm: Optional[LLMClient] = None
        self._fetcher: Optional[LiveFetcher] = None

    @property
    def llm(self) -> LLMClient:
        """Lazy-load LLM client."""
        if self._llm is None:
            self._llm = LLMClient(base_url=self.llm_url)
        return self._llm

    @property
    def fetcher(self) -> LiveFetcher:
        """Lazy-load fetcher."""
        if self._fetcher is None:
            self._fetcher = LiveFetcher()
        return self._fetcher

    async def summarize_page(self, page_id: str) -> SummaryResult:
        """
        Generate a grounded summary of a page.
        
        Args:
            page_id: Confluence page ID
            
        Returns:
            SummaryResult with bullet points and grounding info
        """
        logger.info(f"Summarizing page: {page_id}")
        
        # 1. Fetch live content
        page = self.fetcher.fetch_page(page_id)
        
        if page.error:
            return SummaryResult(
                page_id=page_id,
                title="Unknown",
                url="",
                summary=[],
                grounding_score=0.0,
                is_grounded=False,
                error=page.error,
            )
        
        if not page.content or len(page.content.strip()) < 50:
            return SummaryResult(
                page_id=page_id,
                title=page.title,
                url=page.url,
                summary=["Document contains no extractable content"],
                grounding_score=1.0,
                is_grounded=True,
            )
        
        # 2. Build prompt (NO user query - pure summarization)
        prompt = SUMMARIZE_SYSTEM_PROMPT.format(content=page.content)
        
        # 3. Call LLM
        try:
            response = await self.llm.generate(prompt, model=self.llm_model)
        except Exception as e:
            logger.error(f"LLM call failed: {e}")
            return SummaryResult(
                page_id=page_id,
                title=page.title,
                url=page.url,
                summary=[],
                grounding_score=0.0,
                is_grounded=False,
                error=f"LLM error: {e}",
            )
        
        if not response:
            return SummaryResult(
                page_id=page_id,
                title=page.title,
                url=page.url,
                summary=[],
                grounding_score=0.0,
                is_grounded=False,
                error="LLM returned empty response",
            )
        
        # 4. Parse response
        bullets = parse_bullet_points(response)
        citations = extract_citations(response)
        
        # 5. Validate grounding
        grounding_score = calculate_grounding_score(response, page.content)
        is_grounded = grounding_score >= self.grounding_threshold
        
        warning = None
        if not is_grounded:
            warning = f"Low grounding score ({grounding_score:.2f}). Summary may contain hallucinations."
        
        return SummaryResult(
            page_id=page_id,
            title=page.title,
            url=page.url,
            summary=bullets if bullets else [response.strip()],
            grounding_score=grounding_score,
            is_grounded=is_grounded,
            source_sections=citations,
            warning=warning,
        )

    async def answer_from_page(self, page_id: str, question: str) -> AnswerResult:
        """
        Answer a question using only content from a specific page.
        
        Args:
            page_id: Confluence page ID
            question: User's question
            
        Returns:
            AnswerResult with answer and grounding info
        """
        logger.info(f"Answering from page {page_id}: {question[:50]}...")
        
        # 1. Fetch live content
        page = self.fetcher.fetch_page(page_id)
        
        if page.error:
            return AnswerResult(
                page_id=page_id,
                title="Unknown",
                url="",
                question=question,
                answer=[],
                found_in_document=False,
                grounding_score=0.0,
                is_grounded=False,
                error=page.error,
            )
        
        if not page.content or len(page.content.strip()) < 50:
            return AnswerResult(
                page_id=page_id,
                title=page.title,
                url=page.url,
                question=question,
                answer=["The document contains no content to answer this question."],
                found_in_document=False,
                grounding_score=1.0,
                is_grounded=True,
            )
        
        # 2. Build prompt (WITH user query)
        prompt = ANSWER_SYSTEM_PROMPT.format(
            question=question,
            content=page.content,
        )
        
        # 3. Call LLM
        try:
            response = await self.llm.generate(prompt, model=self.llm_model)
        except Exception as e:
            logger.error(f"LLM call failed: {e}")
            return AnswerResult(
                page_id=page_id,
                title=page.title,
                url=page.url,
                question=question,
                answer=[],
                found_in_document=False,
                grounding_score=0.0,
                is_grounded=False,
                error=f"LLM error: {e}",
            )
        
        if not response:
            return AnswerResult(
                page_id=page_id,
                title=page.title,
                url=page.url,
                question=question,
                answer=[],
                found_in_document=False,
                grounding_score=0.0,
                is_grounded=False,
                error="LLM returned empty response",
            )
        
        # 4. Check for NOT_FOUND
        found_in_document = "NOT_FOUND" not in response.upper()
        
        # 5. Parse response
        if found_in_document:
            bullets = parse_bullet_points(response)
            answer = bullets if bullets else [response.strip()]
        else:
            answer = ["The document does not contain information about this question."]
        
        # 6. Validate grounding
        grounding_score = calculate_grounding_score(response, page.content)
        is_grounded = grounding_score >= self.grounding_threshold or not found_in_document
        
        warning = None
        if not is_grounded and found_in_document:
            warning = f"Low grounding score ({grounding_score:.2f}). Answer may contain hallucinations."
        
        return AnswerResult(
            page_id=page_id,
            title=page.title,
            url=page.url,
            question=question,
            answer=answer,
            found_in_document=found_in_document,
            grounding_score=grounding_score,
            is_grounded=is_grounded,
            warning=warning,
        )


# ========== Convenience Functions ==========

_summarizer: Optional[GroundedSummarizer] = None


def _run_async(coro):
    """
    Run async coroutine safely, handling both sync and async contexts.
    """
    try:
        # Check if we're already in an async context
        loop = asyncio.get_running_loop()
        # We're in an async context - run in a separate thread
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as pool:
            future = pool.submit(asyncio.run, coro)
            return future.result()
    except RuntimeError:
        # No running loop - safe to use asyncio.run()
        return asyncio.run(coro)


def get_summarizer() -> GroundedSummarizer:
    """Get or create summarizer singleton."""
    global _summarizer
    if _summarizer is None:
        _summarizer = GroundedSummarizer()
    return _summarizer


async def summarize_page_async(page_id: str) -> dict:
    """Async convenience function for MCP tools."""
    summarizer = get_summarizer()
    result = await summarizer.summarize_page(page_id)
    return result.to_dict()


async def answer_from_page_async(page_id: str, question: str) -> dict:
    """Async convenience function for MCP tools."""
    summarizer = get_summarizer()
    result = await summarizer.answer_from_page(page_id, question)
    return result.to_dict()


# Sync wrappers for non-async contexts
def summarize_page(page_id: str) -> dict:
    """Sync wrapper for summarize_page."""
    return _run_async(summarize_page_async(page_id))


def answer_from_page(page_id: str, question: str) -> dict:
    """Sync wrapper for answer_from_page."""
    return _run_async(answer_from_page_async(page_id, question))


if __name__ == "__main__":
    # Quick test
    import sys
    logging.basicConfig(level=logging.INFO)
    
    if len(sys.argv) < 2:
        print("Usage: python summarizer.py <page_id> [question]")
        sys.exit(1)
    
    page_id = sys.argv[1]
    question = sys.argv[2] if len(sys.argv) > 2 else None
    
    async def test():
        summarizer = GroundedSummarizer()
        
        if question:
            print(f"\n=== Answering: {question} ===")
            result = await summarizer.answer_from_page(page_id, question)
            print(f"Found: {result.found_in_document}")
            print(f"Grounding: {result.grounding_score:.2f}")
            for bullet in result.answer:
                print(f"  • {bullet}")
        else:
            print(f"\n=== Summarizing page {page_id} ===")
            result = await summarizer.summarize_page(page_id)
            print(f"Title: {result.title}")
            print(f"Grounding: {result.grounding_score:.2f}")
            for bullet in result.summary:
                print(f"  • {bullet}")
    
    asyncio.run(test())
