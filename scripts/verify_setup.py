#!/usr/bin/env python3
"""
Setup Verification Script

Verifies all system components are properly configured:
1. Qdrant connection
2. Dense embedding model
3. Sparse embedding model
4. Reranker model
5. Confluence API access
"""

import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import settings


def check_qdrant():
    """Check Qdrant connection."""
    print("1️⃣ Checking Qdrant...")
    try:
        from qdrant_client import QdrantClient
        client = QdrantClient(url=settings.qdrant_url)
        collections = client.get_collections()
        print(f"   ✅ Connected to {settings.qdrant_url}")
        print(f"   📊 Collections: {[c.name for c in collections.collections]}")
        return True
    except Exception as e:
        print(f"   ❌ Failed: {e}")
        print(f"   💡 Run: docker-compose up -d")
        return False


def check_dense_model():
    """Check dense embedding model."""
    print("\n2️⃣ Checking Dense Model...")
    try:
        from fastembed import TextEmbedding
        model = TextEmbedding(
            model_name=settings.dense_model,
            cache_dir=settings.fastembed_cache_path,
            local_files_only=True,
        )
        # Quick test
        embeddings = list(model.embed(["test"]))
        print(f"   ✅ {settings.dense_model} loaded")
        print(f"   📐 Dimension: {len(embeddings[0])}")
        return True
    except Exception as e:
        print(f"   ❌ Failed: {e}")
        print(f"   💡 Run: ./scripts/download_models.sh")
        return False


def check_sparse_model():
    """Check sparse embedding model."""
    print("\n3️⃣ Checking Sparse Model...")
    try:
        from fastembed import SparseTextEmbedding
        model = SparseTextEmbedding(
            model_name=settings.sparse_model,
            cache_dir=settings.fastembed_cache_path,
            local_files_only=True,
        )
        # Quick test
        embeddings = list(model.embed(["test"]))
        print(f"   ✅ {settings.sparse_model} loaded")
        print(f"   📐 Non-zero indices: {len(embeddings[0].indices)}")
        return True
    except Exception as e:
        print(f"   ❌ Failed: {e}")
        print(f"   💡 Run: ./scripts/download_models.sh")
        return False


def check_reranker():
    """Check reranker model."""
    print("\n4️⃣ Checking Reranker...")
    try:
        from flashrank import Ranker
        ranker = Ranker(model_name=settings.rerank_model)
        print(f"   ✅ {settings.rerank_model} loaded")
        return True
    except Exception as e:
        print(f"   ❌ Failed: {e}")
        print(f"   💡 Run: ./scripts/download_models.sh")
        return False


def check_confluence():
    """Check Confluence API access."""
    print("\n5️⃣ Checking Confluence API...")
    try:
        from ingestion.confluence_client import ConfluenceClient
        client = ConfluenceClient()
        homepage_id = client.get_space_homepage_id()
        if homepage_id:
            print(f"   ✅ Connected to {settings.confluence_base_url}")
            print(f"   📄 Space: {settings.confluence_space_key}")
            print(f"   🏠 Homepage ID: {homepage_id}")
            return True
        else:
            print(f"   ⚠️ Connected but couldn't fetch homepage")
            return True
    except Exception as e:
        print(f"   ❌ Failed: {e}")
        print(f"   💡 Check CONFLUENCE_BASE_URL and CONFLUENCE_PAT in .env")
        return False


def check_collection():
    """Check if skeleton collection exists and has data."""
    print("\n6️⃣ Checking Skeleton Collection...")
    try:
        from qdrant_client import QdrantClient
        client = QdrantClient(url=settings.qdrant_url)
        
        if client.collection_exists(settings.qdrant_collection):
            info = client.get_collection(settings.qdrant_collection)
            print(f"   ✅ Collection: {settings.qdrant_collection}")
            print(f"   📊 Points: {info.points_count}")
            return info.points_count > 0
        else:
            print(f"   ⚠️ Collection {settings.qdrant_collection} does not exist")
            print(f"   💡 Run: python -m ingestion.run_ingestion")
            return False
    except Exception as e:
        print(f"   ❌ Failed: {e}")
        return False


def main():
    """Run all checks."""
    print("=" * 50)
    print("MCP-based Confluence RAG - Setup Verification")
    print("=" * 50)
    print(f"\n📁 Models cache: {settings.fastembed_cache_path}")
    print(f"🔗 Qdrant URL: {settings.qdrant_url}")
    print(f"📚 Collection: {settings.qdrant_collection}")
    print("")
    
    results = {
        "Qdrant": check_qdrant(),
        "Dense Model": check_dense_model(),
        "Sparse Model": check_sparse_model(),
        "Reranker": check_reranker(),
        "Confluence": check_confluence(),
        "Collection": check_collection(),
    }
    
    print("\n" + "=" * 50)
    print("Summary")
    print("=" * 50)
    
    all_ok = True
    for component, status in results.items():
        icon = "✅" if status else "❌"
        print(f"  {icon} {component}")
        if not status:
            all_ok = False
    
    print("")
    if all_ok:
        print("🎉 All systems go! Ready to use.")
        return 0
    else:
        print("⚠️ Some components need attention. See details above.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
