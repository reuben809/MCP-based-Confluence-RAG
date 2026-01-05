#!/bin/bash
# ============================================
# MCP-based Confluence RAG - Model Download
# ============================================
# Downloads and caches all required models locally.
# Run this once before first use.

set -e

CACHE_DIR="${FASTEMBED_CACHE_PATH:-./models_cache}"
echo "📥 Downloading models to: $CACHE_DIR"
mkdir -p "$CACHE_DIR"

# Function to check if model exists
check_model() {
    local model_path="$1"
    if [ -d "$model_path" ] && [ "$(ls -A "$model_path" 2>/dev/null)" ]; then
        return 0
    fi
    return 1
}

echo ""
echo "1️⃣ Checking Dense Model: BAAI/bge-small-en-v1.5"
if check_model "$CACHE_DIR/fast-bge-small-en-v1.5"; then
    echo "   ✅ Already cached"
else
    echo "   ⏳ Downloading via FastEmbed..."
    python -c "
from fastembed import TextEmbedding
TextEmbedding(model_name='BAAI/bge-small-en-v1.5', cache_dir='$CACHE_DIR')
print('   ✅ Downloaded')
"
fi

echo ""
echo "2️⃣ Checking Sparse Model: prithivida/Splade_PP_en_v1"
if check_model "$CACHE_DIR/fast-splade_pp_en_v1"; then
    echo "   ✅ Already cached"
else
    echo "   ⏳ Downloading via FastEmbed..."
    python -c "
from fastembed import SparseTextEmbedding
SparseTextEmbedding(model_name='prithivida/Splade_PP_en_v1', cache_dir='$CACHE_DIR')
print('   ✅ Downloaded')
"
fi

echo ""
echo "3️⃣ Checking Reranker: ms-marco-TinyBERT-L-2-v2"
RERANK_DIR="$CACHE_DIR/ms-marco-TinyBERT-L-2-v2"
if check_model "$RERANK_DIR"; then
    echo "   ✅ Already cached"
else
    echo "   ⏳ Downloading from TU Darmstadt..."
    mkdir -p "$RERANK_DIR"
    cd "$RERANK_DIR"
    
    # Download the zip file
    curl -L -o model.zip \
        "https://public.ukp.informatik.tu-darmstadt.de/thakur/BEIR/models/ms-marco-TinyBERT-L-2-v2.zip"
    
    # Extract
    unzip -o model.zip
    rm model.zip
    
    # Move files if nested
    if [ -d "ms-marco-TinyBERT-L-2-v2" ]; then
        mv ms-marco-TinyBERT-L-2-v2/* .
        rmdir ms-marco-TinyBERT-L-2-v2
    fi
    
    cd -
    echo "   ✅ Downloaded"
fi

echo ""
echo "✅ All models ready!"
echo ""
echo "Model cache contents:"
ls -la "$CACHE_DIR"
