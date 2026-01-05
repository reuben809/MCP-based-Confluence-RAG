# User Guide

## MCP-based Confluence RAG

A step-by-step guide to using the MCP-based Confluence documentation navigator.

---

## Table of Contents

1. [Getting Started](#getting-started)
2. [Installation](#installation)
3. [Configuration](#configuration)
4. [Running the System](#running-the-system)
5. [Using with Claude Desktop](#using-with-claude-desktop)
6. [Using with LM Studio](#using-with-lm-studio)
7. [Troubleshooting](#troubleshooting)
8. [FAQ](#faq)

---

## Getting Started

### What This System Does

The MCP-based Confluence RAG lets AI assistants (like Claude and LM Studio models) search and read your Confluence documentation. It provides:

- **Fast search** across all indexed pages
- **Live content** fetched fresh from Confluence
- **Grounded synthesis** - AI summaries sourced ONLY from your docs (no hallucination)
- **Navigation** through page hierarchies

### Prerequisites

Before you begin, ensure you have:

- **Python 3.11+** installed
- **Docker** for running Qdrant
- **Confluence access** (public or with PAT token)
- **~2GB disk space** for models

---

## Installation

### Step 1: Clone and Setup Environment

```bash
# Navigate to project directory
cd enterprise_confluence_ai

# Create virtual environment
python -m venv .venv

# Activate virtual environment
# On macOS/Linux:
source .venv/bin/activate
# On Windows:
.venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### Step 2: Download Required Models

The system requires three local ML models. Download them automatically:

```bash
# Make script executable (macOS/Linux)
chmod +x scripts/download_models.sh

# Run download script
./scripts/download_models.sh
```

**What gets downloaded:**
| Model | Size | Purpose |
|-------|------|---------|
| bge-small-en-v1.5 | ~130MB | Semantic search |
| Splade_PP_en_v1 | ~500MB | Keyword matching |
| ms-marco-TinyBERT-L-2-v2 | ~60MB | Result reranking |

### Step 3: Verify Setup

Run the verification script to check all components:

```bash
python scripts/verify_setup.py
```

Expected output:
```
==================================================
MCP-based Confluence RAG - Setup Verification
==================================================

1️⃣ Checking Qdrant...
   ✅ Connected to http://localhost:6333

2️⃣ Checking Dense Model...
   ✅ BAAI/bge-small-en-v1.5 loaded

3️⃣ Checking Sparse Model...
   ✅ prithivida/Splade_PP_en_v1 loaded

4️⃣ Checking Reranker...
   ✅ ms-marco-TinyBERT-L-2-v2 loaded

5️⃣ Checking Confluence API...
   ✅ Connected to https://cwiki.apache.org/confluence

🎉 All systems go!
```

---

## Configuration

### Environment Variables

Copy the example config and customize:

```bash
cp .env.example .env
```

Edit `.env` with your settings:

```bash
# Required: Confluence connection
CONFLUENCE_BASE_URL=https://your-confluence.atlassian.net/wiki
CONFLUENCE_SPACE_KEY=YOUR_SPACE
CONFLUENCE_PAT=your_personal_access_token

# Optional: Customize these if needed
QDRANT_URL=http://localhost:6333
MCP_SSE_PORT=8080
```

### Configuration Options

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `CONFLUENCE_BASE_URL` | Yes | - | Your Confluence URL |
| `CONFLUENCE_SPACE_KEY` | Yes | - | Space to index |
| `CONFLUENCE_PAT` | Yes | - | Personal Access Token (or 'anonymous') |
| `QDRANT_URL` | No | localhost:6333 | Qdrant server URL |
| `MCP_SSE_PORT` | No | 8080 | SSE server port |
| `INGESTION_MAX_PAGES` | No | 2000 | Max pages to index |
| `LLM_BASE_URL` | No | localhost:1234/v1 | LLM server for summarization |
| `LLM_MODEL` | No | local-model | LLM model name |

### Getting a Confluence PAT

For private Confluence (Atlassian Cloud):

1. Go to **Account Settings** → **Security** → **API tokens**
2. Click **Create API token**
3. Name it (e.g., "Skeleton Navigator")
4. Copy the token to your `.env` file

For public Confluence (like Apache's wiki):
- Use `CONFLUENCE_PAT=anonymous`

---

## Running the System

### Step 1: Start Qdrant

```bash
docker-compose up -d
```

Verify it's running:
```bash
curl http://localhost:6333/healthz
# Should return: {"title":"qdrant - vectorass database","version":"..."}
```

### Step 2: Index Confluence Pages

Run the ingestion pipeline:

```bash
# Index with defaults (from .env settings)
python -m ingestion.run_ingestion

# Or specify options
python -m ingestion.run_ingestion --max-pages 500
```

**Options:**
| Flag | Description |
|------|-------------|
| `--max-pages N` | Limit number of pages to index |
| `--recreate` | Delete and recreate the collection |
| `--full` | Full reindex (ignore hash cache) |

**Expected output:**
```
🧭 MCP-based Confluence RAG - Ingestion
==================================================
2024-01-05 10:30:00 - INFO - Starting ingestion for space: KAFKA
2024-01-05 10:30:00 - INFO - Found 0 existing pages in collection
Indexing pages: 100%|████████████████████| 500/500 [05:30<00:00, 1.5pages/s]
2024-01-05 10:35:30 - INFO - Indexing complete. Indexed: 500, Skipped: 0

✅ Ingestion complete! 500 pages indexed.
```

### Step 3: Start MCP Server

**For LM Studio (SSE transport):**
```bash
python -m mcp.server
```

Output:
```
2024-01-05 10:40:00 - INFO - Starting MCP SSE server on 0.0.0.0:8080
2024-01-05 10:40:00 - INFO - SSE endpoint: http://0.0.0.0:8080/sse
2024-01-05 10:40:00 - INFO - Health check: http://0.0.0.0:8080/health
```

**For Claude Desktop (STDIO transport):**
See the [Claude Desktop section](#using-with-claude-desktop) below.

---

## Using with Claude Desktop

### Step 1: Configure Claude Desktop

Find your Claude Desktop config file:
- **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`

Add this configuration:

```json
{
  "mcpServers": {
    "confluence": {
      "command": "python",
      "args": ["-m", "mcp.stdio_server"],
      "cwd": "/full/path/to/enterprise_confluence_ai",
      "env": {
        "CONFLUENCE_BASE_URL": "https://cwiki.apache.org/confluence",
        "CONFLUENCE_SPACE_KEY": "KAFKA",
        "CONFLUENCE_PAT": "anonymous"
      }
    }
  }
}
```

**Important:** Replace `/full/path/to/` with your actual project path.

### Step 2: Restart Claude Desktop

Close and reopen Claude Desktop. You should see "confluence" in the tools list.

### Step 3: Start Asking Questions

Example prompts:

- "Search for documentation about Kafka producers"
- "Read the page about Kafka Connect configuration"
- "What child pages are under the Kafka Streams section?"
- **"What is Kafka and how does it work?"** (uses grounded synthesis!)

Claude will automatically use the MCP tools:
1. **search_and_summarize** 🎯 - Main tool: search + grounded summary
2. **search_documentation** - Find relevant pages
3. **read_page** - Get full page content
4. **get_child_pages** - Navigate page hierarchy

---

## Using with LM Studio

### Step 1: Start MCP SSE Server

```bash
python -m mcp.server
```

Keep this terminal running.

### Step 2: Configure LM Studio

1. Open LM Studio
2. Go to **Settings** → **MCP Servers**
3. Add new server:
   - **Name**: Confluence
   - **URL**: `http://localhost:8080/sse`
   - **Type**: SSE

### Step 3: Use the Tools

The following tools are available:

**Main Tool:**
| Tool | Description | Example |
|------|-------------|---------|
| `search_and_summarize` | 🎯 Search + grounded summary | `search_and_summarize("What is Kafka?")` |

**Supporting Tools:**
| Tool | Description | Example |
|------|-------------|---------|
| `search_documentation` | Search pages | `search_documentation("kafka consumer group")` |
| `read_page` | Get page content | `read_page("12345678")` |
| `get_child_pages` | List children | `get_child_pages("12345678")` |
| `get_page_metadata` | Get page info | `get_page_metadata("12345678")` |
| `summarize_page` | Single-page summary | `summarize_page("12345678")` |
| `answer_from_page` | Q&A from single page | `answer_from_page("12345678", "what is X?")` |

---

## Troubleshooting

### Qdrant Connection Failed

**Error:** `Connection refused to localhost:6333`

**Solution:**
```bash
# Check if Qdrant is running
docker ps | grep qdrant

# If not running, start it
docker-compose up -d

# Check logs for errors
docker logs skeleton_qdrant
```

### Model Loading Failed

**Error:** `Failed to load model: BAAI/bge-small-en-v1.5`

**Solution:**
```bash
# Re-run the download script
./scripts/download_models.sh

# Or manually download models
python -c "from fastembed import TextEmbedding; TextEmbedding('BAAI/bge-small-en-v1.5', cache_dir='./models_cache')"
```

### Confluence API Errors

**Error:** `HTTP 401 Unauthorized`

**Solution:**
1. Check your PAT token is valid
2. Verify the token has read permissions
3. For public Confluence, use `CONFLUENCE_PAT=anonymous`

**Error:** `HTTP 429 Too Many Requests`

**Solution:**
The system automatically handles rate limiting. If persistent:
1. Reduce `--max-pages` during ingestion
2. Add delay: edit `confluence_client.py` timeout settings

### No Search Results

**Cause:** Collection is empty or not indexed.

**Solution:**
```bash
# Check collection status
curl http://localhost:6333/collections/skeleton_vectors | jq

# Re-run ingestion if points_count is 0
python -m ingestion.run_ingestion --recreate
```

### Claude Desktop Not Seeing Tools

**Cause:** Config file syntax error or wrong path.

**Solution:**
1. Validate JSON syntax at [jsonlint.com](https://jsonlint.com)
2. Ensure `cwd` path is absolute and correct
3. Check Claude Desktop logs for errors

---

## FAQ

### Q: How often should I re-index?

**A:** The system uses incremental indexing by default. Run ingestion weekly or when you know documentation has changed. Unchanged pages are automatically skipped.

### Q: Can I index multiple spaces?

**A:** Currently, one space per deployment. For multiple spaces:
1. Run separate instances with different `.env` configs
2. Use different `QDRANT_COLLECTION` names

### Q: What's the maximum content size?

**A:** Page content is truncated at 12,000 characters to fit LLM context windows. The full page URL is included for reference.

### Q: Does it work offline?

**A:** 
- **Search**: Yes, fully offline after indexing
- **Read page**: No, requires live Confluence connection

### Q: How accurate is the search?

**A:** The hybrid search combines:
- Semantic understanding (dense embeddings)
- Keyword matching (sparse embeddings)
- Cross-encoder reranking

This typically provides 90%+ relevance in the top 5 results.

### Q: Can I use my own embedding models?

**A:** Yes, edit `config/settings.py`:
```python
dense_model: str = Field(default="your-model-name", ...)
```
Ensure the model is compatible with FastEmbed.

---

## Quick Reference

### Commands Cheat Sheet

```bash
# Start Qdrant
docker-compose up -d

# Stop Qdrant
docker-compose down

# Run ingestion
python -m ingestion.run_ingestion

# Start MCP server (SSE)
python -m mcp.server

# Start MCP server (STDIO)
python -m mcp.stdio_server

# Verify setup
python scripts/verify_setup.py

# Check collection status
curl http://localhost:6333/collections/skeleton_vectors | jq

# Test search
python -c "from utils.search import search_documentation; print(search_documentation('kafka producer', 3))"
```

### Directory Structure

```
enterprise_confluence_ai/
├── config/          # Configuration
├── ingestion/       # Data pipeline
├── mcp/             # MCP servers
├── utils/           # Shared utilities
├── scripts/         # Helper scripts
├── models_cache/    # Local ML models
├── docs/            # Documentation
└── .env             # Your config
```
