"""
Ingestion Orchestrator

Simple entry point for running the ingestion pipeline.
Supports both sync and async (parallel) modes.
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
    parser.add_argument(
        "--sync",
        action="store_true",
        help="Use sync sequential fetch (default: async parallel)",
    )
    parser.add_argument(
        "--concurrent",
        type=int,
        default=10,
        help="Max concurrent requests for async mode (default: 10)",
    )
    
    args = parser.parse_args()
    
    print("🧭 MCP-based Confluence RAG - Ingestion")
    print("=" * 50)
    
    if not args.sync:
        print(f"⚡ Using async parallel fetch ({args.concurrent} concurrent requests)")
    else:
        print("🐢 Using sync sequential fetch")
    
    indexed = run_ingestion(
        max_pages=args.max_pages,
        recreate=args.recreate,
        incremental=not args.full,
        use_async=not args.sync,
        max_concurrent=args.concurrent,
    )
    
    print(f"\n✅ Ingestion complete! {indexed} pages indexed.")
