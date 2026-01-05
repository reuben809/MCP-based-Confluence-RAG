# MCP-based Confluence RAG

> **A production-ready MCP server for AI-assisted Confluence documentation search and grounded synthesis.**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![MCP Protocol](https://img.shields.io/badge/MCP-1.0-green.svg)](https://modelcontextprotocol.io/)

## 🎯 What is This?

**MCP-based Confluence RAG** is an intelligent documentation assistant that enables AI models (like Claude and LM Studio) to search, read, and synthesize information from your Confluence documentation. Unlike traditional RAG systems that store full documents, this uses a **skeleton pattern** - storing only lightweight metadata while fetching fresh content on-demand.

### Key Benefits

| Feature | Description |
|---------|-------------|
| **Zero Staleness** | Content is fetched live from Confluence - always up-to-date |
| **No Hallucination** | Grounded synthesis ensures LLM outputs are strictly from documents |
| **Low Storage** | Only metadata stored in vector DB (~50MB for 1000 pages) |
| **Fast Search** | Hybrid search with 200-300ms latency |
| **Dual Transport** | Works with Claude Desktop (STDIO) and LM Studio (SSE) |

---

## 🏗️ Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                         AI CLIENTS                                   │
├─────────────────────────────────────────────────────────────────────┤
│   Claude Desktop (STDIO)        │        LM Studio (SSE :8080)      │
│   "What is Kafka replication?"  │    "Explain consumer groups"      │
└──────────────┬──────────────────┴────────────────┬──────────────────┘
               │                                   │
               ▼                                   ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      MCP SERVER (7 TOOLS)                           │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│   🎯 search_and_summarize   ─────────────────────────────────────   │
│      │                                                               │
│      │  1. Search: Find relevant pages     ──► HybridSearcher       │
│      │  2. Fetch: Get live content         ──► Confluence API       │
│      │  3. Synthesize: Grounded summary    ──► Local LLM            │
│      │  4. Validate: Check grounding score                          │
│      │                                                               │
│   Supporting Tools:                                                  │
│   • search_documentation    • read_page      • get_child_pages      │
│   • get_page_metadata       • summarize_page • answer_from_page     │
│                                                                      │
└──────────────┬──────────────────────────────────┬───────────────────┘
               │                                   │
               ▼                                   ▼
┌───────────────────────────────┐   ┌────────────────────────────────┐
│      QDRANT VECTOR DB         │   │        CONFLUENCE              │
├───────────────────────────────┤   ├────────────────────────────────┤
│  • Page metadata (skeleton)   │   │  • Full page content (live)    │
│  • Dense embeddings (384d)    │   │  • Labels, versions, children  │
│  • Sparse embeddings (SPLADE) │   │  • REST API with auth          │
│  • ~50MB per 1000 pages       │   │                                │
└───────────────────────────────┘   └────────────────────────────────┘
```

### How Grounded Synthesis Works

The `search_and_summarize` tool uses a **hallucination-prevention pattern**:

1. **User asks**: "What is Kafka replication?"
2. **System searches**: Finds 5 most relevant pages
3. **System fetches**: Gets live content from all 5 pages
4. **LLM sees ONLY the documents** - the user's question is NOT passed to the LLM!
5. **LLM summarizes**: Produces factual bullet points citing sources
6. **System validates**: Calculates grounding score (token overlap)

This prevents the LLM from "helping" with external knowledge that might be wrong.

---

## 🚀 Quick Start

### Prerequisites

- **Python 3.11+** - Required for async features
- **Docker** - For running Qdrant vector database
- **~2GB disk** - For ML models (dense, sparse, reranker)
- **Confluence access** - Public or with PAT token

### Installation

```bash
# 1. Clone the repository
git clone https://github.com/reuben809/MCP-based-Confluence-RAG.git
cd MCP-based-Confluence-RAG

# 2. Create and activate virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment
cp .env.example .env
# Edit .env with your Confluence settings (see Configuration section)

# 5. Download ML models (first time only, ~1.5GB)
chmod +x scripts/download_models.sh
./scripts/download_models.sh
```

### Starting Services

```bash
# 1. Start Qdrant vector database
docker-compose up -d

# 2. Verify setup (optional but recommended)
python scripts/verify_setup.py

# 3. Index your Confluence space
python -m ingestion.run_ingestion

# 4. Start MCP server
python -m mcp.server  # SSE on port 8080
```

### Connect Your AI

**For LM Studio:**
1. Go to Settings → MCP Servers
2. Add: `http://localhost:8080/sse`

**For Claude Desktop:**
Add to `~/Library/Application Support/Claude/claude_desktop_config.json`:
```json
{
  "mcpServers": {
    "confluence": {
      "command": "python",
      "args": ["-m", "mcp.stdio_server"],
      "cwd": "/path/to/MCP-based-Confluence-RAG",
      "env": {
        "CONFLUENCE_BASE_URL": "https://your-confluence.atlassian.net/wiki",
        "CONFLUENCE_SPACE_KEY": "DOCS",
        "CONFLUENCE_PAT": "your-token-here"
      }
    }
  }
}
```

---

## 📖 MCP Tools Reference

### 🎯 Primary Tool: `search_and_summarize`

The main tool that provides end-to-end document-grounded question answering.

```
search_and_summarize(query: str, max_sources: int = 5)
```

**Example:**
```
User: "What is Kafka and how does it handle replication?"

Returns:
{
  "summary": [
    "[Source: Kafka Overview] Apache Kafka is a distributed streaming platform...",
    "[Source: Replication Guide] Kafka replicates partitions across brokers...",
    "[Source: Fault Tolerance] The replication factor determines copies..."
  ],
  "sources": [
    {"title": "Kafka Overview", "url": "..."},
    {"title": "Replication Guide", "url": "..."},
    {"title": "Fault Tolerance", "url": "..."}
  ],
  "grounding_score": 0.87,
  "is_grounded": true
}
```

### Supporting Tools

| Tool | Purpose | Example |
|------|---------|---------|
| `search_documentation(query, limit)` | Find relevant pages | `search_documentation("consumer groups", 5)` |
| `read_page(page_id)` | Get full page content | `read_page("12345678")` |
| `get_child_pages(page_id)` | Navigate hierarchy | `get_child_pages("12345678")` |
| `get_page_metadata(page_id)` | Quick page info | `get_page_metadata("12345678")` |
| `summarize_page(page_id)` | Summary of one page | `summarize_page("12345678")` |
| `answer_from_page(page_id, question)` | Q&A from one page | `answer_from_page("12345678", "what is X?")` |

---

## 🔧 Configuration

### Required Settings

| Variable | Description | Example |
|----------|-------------|---------|
| `CONFLUENCE_BASE_URL` | Your Confluence URL | `https://mycompany.atlassian.net/wiki` |
| `CONFLUENCE_SPACE_KEY` | Space to index | `ENGINEERING`, `DOCS` |
| `CONFLUENCE_PAT` | Personal Access Token | Your token or `anonymous` |

### Optional Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `QDRANT_URL` | `http://localhost:6333` | Qdrant server address |
| `QDRANT_COLLECTION` | `skeleton_vectors` | Collection name |
| `MCP_SSE_PORT` | `8080` | SSE server port |
| `LLM_BASE_URL` | `http://localhost:1234/v1` | LLM server (for synthesis) |
| `LLM_MODEL` | `local-model` | Model name |
| `MAX_CONTENT_CHARS` | `12000` | Max content per page |
| `INGESTION_MAX_PAGES` | `2000` | Max pages to index |

### Getting a Confluence PAT

**For Atlassian Cloud:**
1. Go to https://id.atlassian.com/manage-profile/security/api-tokens
2. Create new API token
3. Use format: `email:token` (base64 encoded) or just the token

**For Public Confluence (like Apache's wiki):**
- Use `CONFLUENCE_PAT=anonymous`

---

## 📁 Project Structure

```
MCP-based-Confluence-RAG/
│
├── config/
│   └── settings.py              # Pydantic settings with validation
│
├── ingestion/                   # Data pipeline
│   ├── confluence_client.py     # REST API wrapper with retry logic
│   ├── skeleton_builder.py      # Builds lightweight page representations
│   ├── embedder.py              # Generates dense + sparse embeddings
│   ├── live_fetcher.py          # On-demand content retrieval
│   └── run_ingestion.py         # Orchestrates the pipeline
│
├── mcp/                         # MCP Protocol implementation
│   ├── tools.py                 # All 7 tool implementations
│   ├── server.py                # SSE transport (HTTP streaming)
│   └── stdio_server.py          # STDIO transport (Claude Desktop)
│
├── utils/                       # Shared utilities
│   ├── search.py                # Hybrid search with reranking
│   ├── summarizer.py            # Single-page grounded summarization
│   ├── synthesizer.py           # Multi-doc grounded synthesis
│   ├── llm_client.py            # OpenAI-compatible LLM wrapper
│   └── html_to_markdown.py      # Confluence HTML converter
│
├── scripts/
│   ├── download_models.sh       # Downloads ML models
│   └── verify_setup.py          # Checks all components
│
├── models_cache/                # Local ML models (~1.5GB)
│   ├── bge-small-en-v1.5/       # Dense embeddings (384d)
│   ├── Splade_PP_en_v1/         # Sparse embeddings
│   └── ms-marco-TinyBERT-L-2/   # Reranker
│
├── docs/
│   ├── ARCHITECTURE.md          # Detailed system design
│   ├── API_REFERENCE.md         # Complete tool documentation
│   └── USER_GUIDE.md            # Step-by-step usage
│
├── .env.example                 # Environment template
├── docker-compose.yml           # Qdrant container
├── requirements.txt             # Python dependencies
└── README.md                    # This file
```

---

## 🧪 Testing

### Quick Tests

```bash
# Test search functionality
python -c "from utils.search import search_documentation; print(search_documentation('kafka producer', 3))"

# Test live content fetching
python -c "from ingestion.live_fetcher import read_page; import json; print(json.dumps(read_page('27846894'), indent=2))"

# Test MCP server health
curl http://localhost:8080/health

# Test full synthesis (requires LLM running)
python -c "from utils.synthesizer import search_and_summarize; print(search_and_summarize('What is Kafka?'))"
```

### Verify All Components

```bash
python scripts/verify_setup.py
```

Expected output:
```
==================================================
MCP-based Confluence RAG - Setup Verification
==================================================

1️⃣ Checking Qdrant...      ✅ Connected
2️⃣ Checking Dense Model... ✅ Loaded (384d)
3️⃣ Checking Sparse Model.. ✅ Loaded
4️⃣ Checking Reranker...    ✅ Loaded
5️⃣ Checking Confluence...  ✅ Connected
6️⃣ Checking Collection...  ✅ 500 pages indexed

🎉 All systems go!
```

---

## 📊 Performance

| Metric | Value |
|--------|-------|
| Search latency | ~200-300ms |
| Content fetch | ~500ms-1s |
| Synthesis (with LLM) | ~3-5s |
| Index size (1k pages) | ~50MB |
| Memory footprint | ~1GB |
| Ingestion rate | ~150 pages/min |

---

## 🔒 Security Considerations

1. **PAT tokens** - Store in environment variables, never commit
2. **Grounding validation** - Prevents LLM from injecting false information
3. **Rate limiting** - Built-in retry with exponential backoff
4. **Content truncation** - 12k char limit prevents context overflow

---

## 📚 Documentation

| Document | Description |
|----------|-------------|
| [Architecture Guide](docs/ARCHITECTURE.md) | System design, data flows, component details |
| [User Guide](docs/USER_GUIDE.md) | Installation, configuration, troubleshooting |
| [API Reference](docs/API_REFERENCE.md) | Complete MCP tool specifications |

---

## 🤝 Contributing

Contributions are welcome! Please:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit changes (`git commit -m 'Add amazing feature'`)
4. Push to branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

---

## 📝 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

## 🙏 Acknowledgments

- [Model Context Protocol](https://modelcontextprotocol.io/) - For the MCP specification
- [FastEmbed](https://github.com/qdrant/fastembed) - For efficient local embeddings
- [FlashRank](https://github.com/PrithivirajDamodaran/FlashRank) - For lightweight reranking
- [Qdrant](https://qdrant.tech/) - For hybrid vector search
