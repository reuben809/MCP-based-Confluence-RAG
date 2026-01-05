"""
Skeleton Embedder

Generates hybrid embeddings (dense + sparse) for skeleton pages
and stores them in Qdrant. No MongoDB dependency.

Pipeline:
1. Fetch pages from Confluence
2. Build skeleton representations
3. Generate dense + sparse embeddings
4. Upsert to Qdrant with payloads

Features:
- Incremental indexing (hash-based change detection)
- Batch embedding for efficiency
- Progress tracking
- Graceful error handling
"""

import logging
import uuid
from typing import Iterator, List, Optional, Tuple

from fastembed import SparseTextEmbedding, TextEmbedding
from qdrant_client import QdrantClient, models
from tqdm import tqdm

from config.settings import settings
from ingestion.confluence_client import ConfluenceClient, PageSummary
from ingestion.skeleton_builder import PageSkeleton, SkeletonBuilder

logger = logging.getLogger(__name__)

# Namespace for deterministic UUIDs
SKELETON_NAMESPACE = uuid.UUID("1b671a64-40d5-491e-99b0-da01ff1f3341")


class SkeletonEmbedder:
    """
    Generates and stores skeleton embeddings in Qdrant.
    
    Uses hybrid embeddings (dense + sparse) for optimal search performance.
    """

    def __init__(
        self,
        qdrant_url: Optional[str] = None,
        collection_name: Optional[str] = None,
        dense_model: Optional[str] = None,
        sparse_model: Optional[str] = None,
        cache_path: Optional[str] = None,
        batch_size: int = 64,
    ):
        """
        Initialize embedder.
        
        Args:
            qdrant_url: Qdrant server URL
            collection_name: Collection to use
            dense_model: Dense embedding model name
            sparse_model: Sparse embedding model name  
            cache_path: Path to model cache
            batch_size: Batch size for embedding
        """
        self.qdrant_url = qdrant_url or settings.qdrant_url
        self.collection_name = collection_name or settings.qdrant_collection
        self.cache_path = cache_path or settings.fastembed_cache_path
        self.batch_size = batch_size
        
        # Initialize clients
        self.qdrant = QdrantClient(url=self.qdrant_url)
        
        # Model names
        self.dense_model_name = dense_model or settings.dense_model
        self.sparse_model_name = sparse_model or settings.sparse_model
        
        # Lazy-loaded models
        self._dense_model: Optional[TextEmbedding] = None
        self._sparse_model: Optional[SparseTextEmbedding] = None

    @property
    def dense_model(self) -> TextEmbedding:
        """Lazy-load dense model."""
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
        """Lazy-load sparse model."""
        if self._sparse_model is None:
            logger.info(f"Loading sparse model: {self.sparse_model_name}")
            self._sparse_model = SparseTextEmbedding(
                model_name=self.sparse_model_name,
                cache_dir=self.cache_path,
                local_files_only=True,
            )
        return self._sparse_model

    def init_collection(self, recreate: bool = False) -> None:
        """
        Initialize Qdrant collection with hybrid vector config.
        
        Args:
            recreate: If True, delete and recreate collection
        """
        if recreate and self.qdrant.collection_exists(self.collection_name):
            logger.warning(f"Deleting existing collection: {self.collection_name}")
            self.qdrant.delete_collection(self.collection_name)
        
        if not self.qdrant.collection_exists(self.collection_name):
            logger.info(f"Creating collection: {self.collection_name}")
            self.qdrant.create_collection(
                collection_name=self.collection_name,
                vectors_config={
                    "dense": models.VectorParams(
                        size=384,  # bge-small-en-v1.5 dimension
                        distance=models.Distance.COSINE,
                    )
                },
                sparse_vectors_config={
                    "sparse": models.SparseVectorParams(
                        index=models.SparseIndexParams(on_disk=False)
                    )
                },
            )
            logger.info("Collection created successfully")
        else:
            logger.info(f"Collection {self.collection_name} already exists")

    def get_existing_hashes(self) -> dict:
        """
        Get content hashes for all existing pages.
        
        Returns:
            Dict mapping page_id to content_hash
        """
        hashes = {}
        
        try:
            # Scroll through all points to get hashes
            offset = None
            while True:
                result = self.qdrant.scroll(
                    collection_name=self.collection_name,
                    limit=1000,
                    offset=offset,
                    with_payload=["page_id", "content_hash"],
                )
                
                points, next_offset = result
                for point in points:
                    if point.payload:
                        page_id = point.payload.get("page_id")
                        content_hash = point.payload.get("content_hash")
                        if page_id and content_hash:
                            hashes[page_id] = content_hash
                
                if next_offset is None:
                    break
                offset = next_offset
                
        except Exception as e:
            logger.warning(f"Could not fetch existing hashes: {e}")
            
        return hashes

    def embed_batch(
        self,
        skeletons: List[PageSkeleton],
    ) -> List[models.PointStruct]:
        """
        Generate embeddings for a batch of skeletons.
        
        Args:
            skeletons: List of PageSkeleton objects
            
        Returns:
            List of PointStruct ready for upsert
        """
        texts = [s.to_skeleton_text() for s in skeletons]
        
        # Generate embeddings
        dense_embeddings = list(self.dense_model.embed(texts))
        sparse_embeddings = list(self.sparse_model.embed(texts))
        
        # Create points
        points = []
        for skeleton, dense, sparse in zip(skeletons, dense_embeddings, sparse_embeddings):
            # Deterministic UUID from page_id
            point_id = str(uuid.uuid5(SKELETON_NAMESPACE, skeleton.page_id))
            
            sparse_vector = models.SparseVector(
                indices=sparse.indices.tolist(),
                values=sparse.values.tolist(),
            )
            
            points.append(models.PointStruct(
                id=point_id,
                vector={
                    "dense": dense.tolist(),
                    "sparse": sparse_vector,
                },
                payload=skeleton.to_payload(),
            ))
            
        return points

    def index_pages(
        self,
        pages: Iterator[Tuple[PageSummary, str]],
        total: Optional[int] = None,
        incremental: bool = True,
    ) -> int:
        """
        Index pages into Qdrant.
        
        Args:
            pages: Iterator of (PageSummary, html_content) tuples
            total: Total count for progress bar (optional)
            incremental: If True, skip unchanged pages
            
        Returns:
            Number of pages indexed
        """
        # Get existing hashes for incremental indexing
        existing_hashes = self.get_existing_hashes() if incremental else {}
        logger.info(f"Found {len(existing_hashes)} existing pages in collection")
        
        # Build skeletons
        builder = SkeletonBuilder(base_url=settings.confluence_base_url)
        
        batch: List[PageSkeleton] = []
        indexed = 0
        skipped = 0
        
        pbar = tqdm(pages, total=total, desc="Indexing pages")
        
        for page_summary, html_content in pbar:
            # Build skeleton
            skeleton = builder.build_skeleton(
                page_id=page_summary.page_id,
                title=page_summary.title,
                html_content=html_content,
                space_key=page_summary.space_key,
                url=page_summary.url,
                parent_id=page_summary.parent_id,
            )
            
            # Check if changed (incremental mode)
            if incremental:
                old_hash = existing_hashes.get(page_summary.page_id)
                if old_hash and old_hash == skeleton.content_hash:
                    skipped += 1
                    pbar.set_postfix(indexed=indexed, skipped=skipped)
                    continue
            
            batch.append(skeleton)
            
            # Process batch
            if len(batch) >= self.batch_size:
                points = self.embed_batch(batch)
                self.qdrant.upsert(
                    collection_name=self.collection_name,
                    points=points,
                )
                indexed += len(batch)
                batch = []
                pbar.set_postfix(indexed=indexed, skipped=skipped)
        
        # Process remaining batch
        if batch:
            points = self.embed_batch(batch)
            self.qdrant.upsert(
                collection_name=self.collection_name,
                points=points,
            )
            indexed += len(batch)
        
        logger.info(f"Indexing complete. Indexed: {indexed}, Skipped: {skipped}")
        return indexed


def run_ingestion(
    max_pages: Optional[int] = None,
    recreate: bool = False,
    incremental: bool = True,
) -> int:
    """
    Run the full ingestion pipeline.
    
    Args:
        max_pages: Maximum pages to index
        recreate: If True, recreate the collection
        incremental: If True, skip unchanged pages
        
    Returns:
        Number of pages indexed
    """
    max_pages = max_pages or settings.ingestion_max_pages
    
    logger.info(f"Starting ingestion for space: {settings.confluence_space_key}")
    logger.info(f"Max pages: {max_pages}, Recreate: {recreate}, Incremental: {incremental}")
    
    # Initialize embedder
    embedder = SkeletonEmbedder()
    embedder.init_collection(recreate=recreate)
    
    # Initialize Confluence client
    client = ConfluenceClient()
    
    def page_generator():
        """Yield pages with their content."""
        for page in client.get_all_pages(max_pages=max_pages):
            html_content = client.get_page_content(page.page_id)
            if html_content is not None:
                yield page, html_content
    
    # Index pages
    indexed = embedder.index_pages(
        pages=page_generator(),
        total=max_pages,
        incremental=incremental,
    )
    
    logger.info(f"Ingestion complete! {indexed} pages indexed.")
    return indexed


if __name__ == "__main__":
    import argparse
    
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
    )
    
    parser = argparse.ArgumentParser(description="Index Confluence pages")
    parser.add_argument("--max-pages", type=int, default=None, help="Max pages to index")
    parser.add_argument("--recreate", action="store_true", help="Recreate collection")
    parser.add_argument("--full", action="store_true", help="Full reindex (no incremental)")
    
    args = parser.parse_args()
    
    run_ingestion(
        max_pages=args.max_pages,
        recreate=args.recreate,
        incremental=not args.full,
    )
