"""
Hybrid Search Engine

Provides hybrid search (dense + sparse) with Reciprocal Rank Fusion (RRF)
and FlashRank reranking. Designed for the skeleton vector index.

Search Pipeline:
1. Generate dense + sparse query embeddings
2. Execute Qdrant prefetch for both
3. Fuse results using RRF
4. Rerank top results with FlashRank
5. Return structured results
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from fastembed import SparseTextEmbedding, TextEmbedding
from flashrank import Ranker, RerankRequest
from qdrant_client import QdrantClient, models

from config.settings import settings

logger = logging.getLogger(__name__)


@dataclass
class SearchResult:
    """Structured search result."""
    page_id: str
    title: str
    url: str
    score: float
    excerpt: str = ""
    space_key: str = ""
    labels: List[str] = field(default_factory=list)
    headers: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "page_id": self.page_id,
            "title": self.title,
            "url": self.url,
            "score": self.score,
            "excerpt": self.excerpt,
            "space_key": self.space_key,
            "labels": self.labels,
            "headers": self.headers,
        }


class HybridSearcher:
    """
    Hybrid search engine using dense + sparse embeddings with RRF fusion.
    
    Uses locally cached FastEmbed models for embedding generation
    and FlashRank for reranking.
    """

    def __init__(
        self,
        qdrant_url: Optional[str] = None,
        collection_name: Optional[str] = None,
        dense_model: Optional[str] = None,
        sparse_model: Optional[str] = None,
        rerank_model: Optional[str] = None,
        cache_path: Optional[str] = None,
    ):
        """
        Initialize hybrid searcher.
        
        Args:
            qdrant_url: Qdrant server URL
            collection_name: Collection to search
            dense_model: Dense embedding model name
            sparse_model: Sparse embedding model name
            rerank_model: Reranker model name
            cache_path: Path to local model cache
        """
        self.qdrant_url = qdrant_url or settings.qdrant_url
        self.collection_name = collection_name or settings.qdrant_collection
        self.cache_path = cache_path or settings.fastembed_cache_path
        
        # Initialize Qdrant client
        self.qdrant = QdrantClient(url=self.qdrant_url)
        logger.info(f"Connected to Qdrant at {self.qdrant_url}")
        
        # Initialize embedding models (lazy loading)
        self._dense_model: Optional[TextEmbedding] = None
        self._sparse_model: Optional[SparseTextEmbedding] = None
        self._reranker: Optional[Ranker] = None
        
        self.dense_model_name = dense_model or settings.dense_model
        self.sparse_model_name = sparse_model or settings.sparse_model
        self.rerank_model_name = rerank_model or settings.rerank_model

    @property
    def dense_model(self) -> TextEmbedding:
        """Lazy-load dense embedding model."""
        if self._dense_model is None:
            logger.info(f"Loading dense model: {self.dense_model_name}")
            self._dense_model = TextEmbedding(
                model_name=self.dense_model_name,
                cache_dir=self.cache_path,
                local_files_only=True,
            )
        return self._dense_model

    @property
    def sparse_model(self) -> SparseTextEmbedding:
        """Lazy-load sparse embedding model."""
        if self._sparse_model is None:
            logger.info(f"Loading sparse model: {self.sparse_model_name}")
            self._sparse_model = SparseTextEmbedding(
                model_name=self.sparse_model_name,
                cache_dir=self.cache_path,
                local_files_only=True,
            )
        return self._sparse_model

    @property
    def reranker(self) -> Optional[Ranker]:
        """Lazy-load reranker model."""
        if self._reranker is None:
            try:
                logger.info(f"Loading reranker: {self.rerank_model_name}")
                self._reranker = Ranker(model_name=self.rerank_model_name)
            except Exception as e:
                logger.warning(f"Failed to load reranker: {e}. Will skip reranking.")
                self._reranker = None
        return self._reranker

    def search(
        self,
        query: str,
        limit: int = 5,
        fetch_multiplier: int = 4,
        use_rerank: bool = True,
        score_threshold: float = 0.0,
    ) -> List[SearchResult]:
        """
        Perform hybrid search with RRF fusion and optional reranking.
        
        Args:
            query: Search query text
            limit: Number of results to return
            fetch_multiplier: Multiplier for initial fetch (before reranking)
            use_rerank: Whether to apply reranking
            score_threshold: Minimum score threshold
            
        Returns:
            List of SearchResult objects
        """
        if not query.strip():
            return []
        
        # 1. Generate query embeddings
        logger.debug(f"Generating embeddings for query: {query[:50]}...")
        
        query_dense = list(self.dense_model.embed([query]))[0]
        query_sparse_obj = list(self.sparse_model.embed([query]))[0]
        
        query_sparse = models.SparseVector(
            indices=query_sparse_obj.indices.tolist(),
            values=query_sparse_obj.values.tolist(),
        )
        
        # 2. Execute hybrid search with RRF fusion
        fetch_limit = limit * fetch_multiplier if use_rerank else limit
        
        prefetch = [
            models.Prefetch(
                query=query_dense.tolist(),
                using="dense",
                limit=fetch_limit,
            ),
            models.Prefetch(
                query=query_sparse,
                using="sparse",
                limit=fetch_limit,
            ),
        ]
        
        try:
            results = self.qdrant.query_points(
                collection_name=self.collection_name,
                prefetch=prefetch,
                query=models.FusionQuery(fusion=models.Fusion.RRF),
                limit=fetch_limit,
                with_payload=True,
                score_threshold=score_threshold if score_threshold > 0 else None,
            ).points
        except Exception as e:
            logger.error(f"Qdrant search failed: {e}")
            return []
        
        if not results:
            logger.info("No results found")
            return []
        
        # 3. Convert to SearchResult objects
        candidates = []
        for hit in results:
            payload = hit.payload or {}
            candidates.append(SearchResult(
                page_id=payload.get("page_id", str(hit.id)),
                title=payload.get("title", "Untitled"),
                url=payload.get("url", ""),
                score=hit.score or 0.0,
                excerpt=payload.get("excerpt", ""),
                space_key=payload.get("space_key", ""),
                labels=payload.get("labels", []),
                headers=payload.get("headers", []),
            ))
        
        # 4. Apply reranking if enabled
        if use_rerank and self.reranker is not None and len(candidates) > 0:
            candidates = self._rerank(query, candidates, limit)
        else:
            candidates = candidates[:limit]
        
        logger.info(f"Search returned {len(candidates)} results")
        return candidates

    def _rerank(
        self,
        query: str,
        candidates: List[SearchResult],
        top_n: int,
    ) -> List[SearchResult]:
        """
        Rerank candidates using FlashRank.
        
        Args:
            query: Original search query
            candidates: List of search results to rerank
            top_n: Number of results to return
            
        Returns:
            Reranked list of SearchResult objects
        """
        if not candidates or self.reranker is None:
            return candidates[:top_n]
        
        # Prepare passages for reranking
        # Use skeleton_text or excerpt for reranking
        passages = []
        for i, c in enumerate(candidates):
            text = c.excerpt or c.title
            passages.append({
                "id": str(i),
                "text": text,
                "meta": {"original_index": i},
            })
        
        try:
            rerank_request = RerankRequest(query=query, passages=passages)
            reranked = self.reranker.rerank(rerank_request)
            
            # Map back to SearchResult objects
            result = []
            for r in reranked[:top_n]:
                original_idx = int(r["id"])
                original = candidates[original_idx]
                # Update score with rerank score
                original.score = r.get("score", original.score)
                result.append(original)
            
            return result
            
        except Exception as e:
            logger.warning(f"Reranking failed: {e}. Using original order.")
            return candidates[:top_n]

    def get_collection_stats(self) -> Dict[str, Any]:
        """
        Get statistics about the search collection.
        
        Returns:
            Dict with collection info
        """
        try:
            info = self.qdrant.get_collection(self.collection_name)
            return {
                "collection_name": self.collection_name,
                "points_count": info.points_count,
                "vectors_count": info.vectors_count,
                "status": info.status.value if info.status else "unknown",
            }
        except Exception as e:
            logger.error(f"Failed to get collection stats: {e}")
            return {"error": str(e)}


# Convenience function for simple searches
def search_documentation(
    query: str,
    limit: int = 5,
    use_rerank: bool = True,
) -> List[Dict[str, Any]]:
    """
    Simple search interface for MCP tools.
    
    Args:
        query: Search query
        limit: Number of results
        use_rerank: Whether to apply reranking
        
    Returns:
        List of result dictionaries
    """
    searcher = HybridSearcher()
    results = searcher.search(query, limit=limit, use_rerank=use_rerank)
    return [r.to_dict() for r in results]


if __name__ == "__main__":
    # Quick test
    logging.basicConfig(level=logging.INFO)
    
    searcher = HybridSearcher()
    print(f"Collection stats: {searcher.get_collection_stats()}")
    
    # Test search (will only work if collection is populated)
    results = searcher.search("kafka producer configuration", limit=3)
    for i, r in enumerate(results, 1):
        print(f"\n{i}. {r.title}")
        print(f"   Score: {r.score:.4f}")
        print(f"   URL: {r.url}")
        print(f"   Excerpt: {r.excerpt[:100]}...")
