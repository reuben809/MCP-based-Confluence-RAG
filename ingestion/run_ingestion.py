"""
Ingestion Orchestrator

Simple entry point for running the ingestion pipeline.
"""

from ingestion.embedder import run_ingestion

if __name__ == "__main__":
    import argparse
    import logging
    
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
    )
    
    parser = argparse.ArgumentParser(description="Index Confluence pages into Qdrant")
    parser.add_argument(
        "--max-pages",
        type=int,
        default=None,
        help="Maximum pages to index (default: from settings)",
    )
    parser.add_argument(
        "--recreate",
        action="store_true",
        help="Delete and recreate the collection",
    )
    parser.add_argument(
        "--full",
        action="store_true", 
        help="Full reindex (skip incremental hash checking)",
    )
    
    args = parser.parse_args()
    
    print("🧭 MCP-based Confluence RAG - Ingestion")
    print("=" * 50)
    
    indexed = run_ingestion(
        max_pages=args.max_pages,
        recreate=args.recreate,
        incremental=not args.full,
    )
    
    print(f"\n✅ Ingestion complete! {indexed} pages indexed.")
