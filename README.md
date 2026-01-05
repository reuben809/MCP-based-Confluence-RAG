# MCP-based Confluence RAG

MCP-based Confluence RAG system with live content fetching and hybrid search.

## 🎯 Overview

A lightweight Confluence documentation navigator that:
- **Stores only metadata** in vector DB (skeleton pattern)
- **Fetches content live** from Confluence (zero staleness)
- **Hybrid search** with dense + sparse embeddings and reranking
- **Grounded synthesis** - LLM summaries sourced ONLY from documents
- **MCP protocol** for Claude Desktop and LM Studio integration

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    MCP CLIENTS                              │
├─────────────────────────────────────────────────────────────┤
│  Claude Desktop (STDIO)    │    LM Studio (SSE :8080)      │
└──────────────┬─────────────┴───────────────┬────────────────┘
               │                             │
               ▼                             ▼
┌─────────────────────────────────────────────────────────────┐
│                    MCP TOOLS (7)                            │
├─────────────────────────────────────────────────────────────┤
│  🎯 search_and_summarize (MAIN) │ search_documentation       │
│  read_page │ get_child_pages │ get_page_metadata           │
│  summarize_page │ answer_from_page                          │
└──────────────┬─────────────────────────────┬────────────────┘
               │                             │
               ▼                             ▼
┌──────────────────────────┐   ┌──────────────────────────────┐
│    HYBRID SEARCH         │   │     LIVE FETCHER             │
├──────────────────────────┤   ├──────────────────────────────┤
│  Dense: bge-small-en     │   │  Confluence REST API         │
│  Sparse: Splade          │   │  HTML → Markdown             │
│  Rerank: TinyBERT        │   │  Smart truncation (12k)      │
│  Fusion: RRF             │   │                              │
└──────────────┬───────────┘   └──────────────┬───────────────┘
               │                              │
               ▼                              ▼
┌──────────────────────────┐   ┌──────────────────────────────┐
│    QDRANT                │   │     CONFLUENCE               │
│    (skeleton vectors)    │   │     (live content)           │
└──────────────────────────┘   └──────────────────────────────┘
```

## 🚀 Quick Start

### 1. Prerequisites

- Python 3.11+
- Docker (for Qdrant)
- Local models cached (or internet for first download)

### 2. Setup

```bash
# Clone and enter directory
cd enterprise_confluence_ai

# Create virtual environment
python -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Copy and configure environment
cp .env.example .env
# Edit .env with your Confluence settings

# Download models (first time only)
chmod +x scripts/download_models.sh
./scripts/download_models.sh
```

### 3. Start Qdrant

```bash
docker-compose up -d
```

### 4. Index Confluence Pages

```bash
# Index with defaults (Apache Kafka Confluence)
python -m ingestion.run_ingestion

# Or with custom settings
python -m ingestion.run_ingestion --max-pages 500 --recreate
```

### 5. Verify Setup

```bash
python scripts/verify_setup.py
```

### 6. Run MCP Server

**For LM Studio (SSE):**
```bash
python -m mcp.server
# Server runs on http://localhost:8080/sse
```

**For Claude Desktop (STDIO):**
Add to `claude_desktop_config.json`:
```json
{
  "mcpServers": {
    "confluence": {
      "command": "python",
      "args": ["-m", "mcp.stdio_server"],
      "cwd": "/path/to/enterprise_confluence_ai"
    }
  }
}
```

## 📖 MCP Tools

### 🎯 Main Tool

| Tool | Description |
|------|-------------|
| `search_and_summarize` | **MAIN TOOL** - Takes a question, searches docs, fetches live content, produces grounded summary. LLM sees ONLY documents (no hallucination). |

### Supporting Tools

| Tool | Description |
|------|-------------|
| `search_documentation` | Hybrid search with reranking. Returns page summaries, not content. |
| `read_page` | Fetch live page content in Markdown format. |
| `get_child_pages` | List child pages of a given page. |
| `get_page_metadata` | Get page info without content. |
| `summarize_page` | Grounded summary of a single page. |
| `answer_from_page` | Answer question from a specific page only. |

## 🔧 Configuration

All settings via environment variables:

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `CONFLUENCE_BASE_URL` | **Yes** | - | Confluence instance URL |
| `CONFLUENCE_SPACE_KEY` | **Yes** | - | Space to index |
| `CONFLUENCE_PAT` | **Yes** | - | Personal Access Token (or 'anonymous') |
| `QDRANT_URL` | No | localhost:6333 | Qdrant server |
| `MCP_SSE_PORT` | No | 8080 | SSE server port |

## 📁 Project Structure

```
enterprise_confluence_ai/
├── config/settings.py        # Centralized config
├── ingestion/
│   ├── confluence_client.py  # REST API wrapper
│   ├── skeleton_builder.py   # Skeleton generation
│   ├── embedder.py           # Hybrid embeddings
│   ├── live_fetcher.py       # On-demand content
│   └── run_ingestion.py      # Pipeline orchestrator
├── mcp/
│   ├── tools.py              # Tool implementations
│   ├── server.py             # SSE transport
│   └── stdio_server.py       # STDIO transport
├── utils/
│   ├── search.py             # Hybrid search + rerank
│   └── html_to_markdown.py   # Content conversion
├── models_cache/             # Local models
├── scripts/
│   ├── download_models.sh    # Model downloader
│   └── verify_setup.py       # Setup checker
└── docker-compose.yml        # Qdrant container
```

## 🧪 Testing

```bash
# Test search
python -c "from utils.search import search_documentation; print(search_documentation('kafka producer', 3))"

# Test live fetch
python -c "from ingestion.live_fetcher import read_page; print(read_page('27846894'))"

# Test MCP SSE endpoint
curl http://localhost:8080/health
```

## 📚 Documentation

Detailed documentation is available in the `docs/` folder:

| Document | Description |
|----------|-------------|
| [Architecture](docs/ARCHITECTURE.md) | High-level & low-level design, data pipelines |
| [User Guide](docs/USER_GUIDE.md) | Installation, configuration, troubleshooting |
| [API Reference](docs/API_REFERENCE.md) | MCP tool specifications |

## 📝 License

MIT
