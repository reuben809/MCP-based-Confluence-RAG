# API Reference

## MCP Tools - Complete Documentation

This document provides complete specifications for all seven MCP (Model Context Protocol) tools exposed by **MCP-based Confluence RAG**. These tools enable AI assistants like Claude and LM Studio models to search, read, navigate, and synthesize information from your Confluence documentation.

---

## Table of Contents

1. [Overview](#overview)
2. [search_documentation](#search_documentation) - Hybrid search
3. [search_and_summarize](#search_and_summarize) - 🎯 Main grounded synthesis tool
4. [read_page](#read_page) - Live content fetch
5. [get_child_pages](#get_child_pages) - Navigate hierarchy
6. [get_page_metadata](#get_page_metadata) - Quick page info
7. [summarize_page](#summarize_page) - Single-page summary
8. [answer_from_page](#answer_from_page) - Q&A from single page
9. [Error Handling](#error-handling)
10. [Rate Limits](#rate-limits)
11. [Performance](#performance)

---

## Overview

### What is MCP?

MCP (Model Context Protocol) is a standard protocol developed by Anthropic that allows AI models to interact with external tools and data sources. When you connect an AI assistant (like Claude or LM Studio) to this server, the AI gains the ability to:

- **Search** your Confluence documentation
- **Read** full page content on demand
- **Navigate** the documentation hierarchy
- **Synthesize** answers from multiple sources with grounding

### How It Works

```
┌──────────────────┐     ┌──────────────────┐     ┌──────────────────┐
│   AI Assistant   │────▶│   MCP Server     │────▶│   Confluence     │
│   (Claude/LLM)   │     │   (This tool)    │     │   (Your docs)    │
└──────────────────┘     └──────────────────┘     └──────────────────┘
        │                         │                       │
        │  1. User asks question  │                       │
        │                         │                       │
        │  2. AI calls tool       │                       │
        │  ────────────────────▶  │                       │
        │                         │  3. Tool fetches data │
        │                         │  ────────────────────▶│
        │                         │                       │
        │                         │  4. Data returned     │
        │                         │◀──────────────────────│
        │  5. Result returned     │                       │
        │  ◀──────────────────────│                       │
        │                         │                       │
        │  6. AI formulates       │                       │
        │     response to user    │                       │
```

### Tool Categories

**🎯 Primary Tool (recommended for most queries)**

| Tool | Purpose | When to Use |
|------|---------|-------------|
| `search_and_summarize` | Complete pipeline: search → fetch → synthesize | When user asks any question about documentation topics |

**🔧 Supporting Tools (for specific needs)**

| Tool | Purpose | When to Use |
|------|---------|-------------|
| `search_documentation` | Find relevant pages | When exploring what pages exist on a topic |
| `read_page` | Get full page content | When you need complete details of a known page |
| `get_child_pages` | Navigate hierarchy | When exploring documentation structure |
| `get_page_metadata` | Quick page info | When you need labels, version, or parent info |
| `summarize_page` | Summary of one page | When you have a specific page ID and want highlights |
| `answer_from_page` | Q&A from one page | When answering from a specific known page |

---

## search_documentation

Search Confluence documentation using advanced hybrid search with reranking.

### Description

This tool performs a sophisticated multi-stage search:

1. **Query Embedding**: Converts your query into dense (semantic) and sparse (keyword) vectors
2. **Hybrid Search**: Runs both vector searches simultaneously against Qdrant
3. **RRF Fusion**: Combines results using Reciprocal Rank Fusion algorithm
4. **Cross-Encoder Reranking**: Uses a TinyBERT model to reorder by relevance

This approach captures both semantic meaning ("machine learning" → "AI", "neural networks") and exact keywords ("Kafka" → "Kafka", not "message queue").

### Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `query` | string | Yes | - | Natural language search query |
| `limit` | integer | No | 5 | Maximum number of results (1-20) |

### Returns

Array of search result objects:

```json
[
  {
    "page_id": "12345678",
    "title": "Kafka Producer Configuration",
    "url": "https://cwiki.apache.org/confluence/pages/viewpage.action?pageId=12345678",
    "score": 0.94,
    "excerpt": "The Kafka producer is responsible for publishing records to topics...",
    "space_key": "KAFKA",
    "labels": ["producer", "configuration", "best-practices"],
    "headers": ["Overview", "Required Settings", "Optional Settings", "Examples"]
  },
  {
    "page_id": "23456789",
    "title": "Producer Best Practices",
    "url": "...",
    "score": 0.87,
    "excerpt": "...",
    "space_key": "KAFKA",
    "labels": ["producer", "best-practices"],
    "headers": ["Introduction", "Batching", "Compression"]
  }
]
```

### Field Descriptions

| Field | Description |
|-------|-------------|
| `page_id` | Unique Confluence page identifier (use this with `read_page`) |
| `title` | Page title |
| `url` | Direct link to view the page in Confluence |
| `score` | Relevance score (0.0 to 1.0, higher is better) |
| `excerpt` | First ~200 characters of page content |
| `space_key` | Confluence space the page belongs to |
| `labels` | Tags applied to the page |
| `headers` | Section headings (H1, H2, H3) found in the page |

### Example

```json
{
  "name": "search_documentation",
  "arguments": {
    "query": "how to configure kafka producer acknowledgement settings",
    "limit": 5
  }
}
```

### Notes

- Query is case-insensitive
- Returns page summaries, NOT full content (use `read_page` for content)
- Empty query returns empty array
- Score above 0.8 indicates high relevance
- Results are already sorted by relevance (best first)

---

## 🎯 search_and_summarize

**THE PRIMARY TOOL** - Complete document-grounded synthesis pipeline.

### Description

This is the main tool that provides end-to-end question answering with strict grounding. It:

1. **Searches** for relevant pages using hybrid search
2. **Fetches** live content from top results (configurable, default 5)
3. **Combines** all content into a single context
4. **Synthesizes** a summary using LLM with strict grounding rules
5. **Validates** the output using token overlap analysis

**CRITICAL ANTI-HALLUCINATION DESIGN**: The LLM **never sees the user's original question** during synthesis. It only sees the combined document content and is asked to summarize it. This prevents the LLM from "helping" by adding information from its training data.

### How It Prevents Hallucination

```
Traditional RAG (risky):
  User Question + Documents → LLM → Answer (may include LLM's "help")

This System (grounded):
  1. User Question → Search → Top Pages
  2. Top Pages → Fetch Live Content → Combined Documents
  3. Combined Documents (NO question!) → LLM → Generic Summary
  4. Summary validated via token overlap with source documents
```

### Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `query` | string | Yes | - | User's question or topic |
| `max_sources` | integer | No | 5 | Maximum documents to synthesize (1-10) |

### Returns

```json
{
  "query": "What is a SWIFT message and what are the different formats?",
  "summary": [
    "[Source: SWIFT Overview] SWIFT (Society for Worldwide Interbank Financial Telecommunication) is a global network enabling financial institutions to send and receive payment messages securely.",
    "[Source: Message Types] There are two main message formats: MT (traditional tag-based messages using ISO 15022) and MX (modern XML-based messages using ISO 20022).",
    "[Source: MT vs MX] MT messages use numeric tags like :20: for transaction reference, while MX messages use structured XML elements for richer data representation."
  ],
  "sources": [
    {
      "page_id": "123456",
      "title": "SWIFT Overview",
      "url": "https://confluence.example.com/pages/viewpage.action?pageId=123456"
    },
    {
      "page_id": "234567",
      "title": "Message Types",
      "url": "https://confluence.example.com/pages/viewpage.action?pageId=234567"
    },
    {
      "page_id": "345678",
      "title": "MT vs MX Comparison",
      "url": "https://confluence.example.com/pages/viewpage.action?pageId=345678"
    }
  ],
  "grounding_score": 0.87,
  "is_grounded": true,
  "total_sources": 3,
  "warning": null,
  "error": null
}
```

### Grounding Score Interpretation

| Score | Interpretation | Action |
|-------|----------------|--------|
| **0.8+** | Excellent - Summary is fully grounded in documents | Trust the result |
| **0.6-0.8** | Good - Mostly grounded with minor paraphrasing | Generally reliable |
| **0.5-0.6** | Borderline - Some content may be interpolated | Manual review suggested |
| **< 0.5** | Warning - Potential hallucination | Do not trust, verify manually |

### Example

```json
{
  "name": "search_and_summarize",
  "arguments": {
    "query": "What is Kafka and how does replication work?",
    "max_sources": 5
  }
}
```

### Special Cases

**No Relevant Documents Found:**
```json
{
  "query": "quantum computing algorithms",
  "summary": [],
  "sources": [],
  "grounding_score": 0.0,
  "is_grounded": true,
  "total_sources": 0,
  "error": "No relevant documents found for this query"
}
```

**LLM Unavailable:**
```json
{
  "query": "What is Kafka?",
  "summary": [],
  "sources": [...],
  "grounding_score": 0.0,
  "is_grounded": false,
  "error": "LLM server unavailable. Check LLM_BASE_URL configuration."
}
```

---

## read_page

Fetch the complete, live content of a Confluence page.

### Description

Retrieves the current version of a page directly from Confluence (never cached), converts the HTML storage format to clean Markdown, and applies intelligent truncation if content exceeds limits.

### Content Processing Pipeline

```
Confluence HTML → Extract Body → Process Tables → Process Code Blocks
    → Convert to Markdown → Smart Truncate (12k chars) → Return
```

### Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `page_id` | string | Yes | Confluence page ID (from search results) |

### Returns

```json
{
  "page_id": "12345678",
  "title": "Kafka Producer Configuration",
  "url": "https://cwiki.apache.org/confluence/pages/viewpage.action?pageId=12345678",
  "content": "# Kafka Producer Configuration\n\nThe producer is responsible for...\n\n## Required Settings\n\n| Property | Default | Description |\n|----------|---------|-------------|\n| bootstrap.servers | - | Kafka broker addresses |\n\n## Code Example\n\n```java\nProperties props = new Properties();\nprops.put(\"bootstrap.servers\", \"localhost:9092\");\n```\n",
  "is_truncated": false,
  "last_updated": "2024-01-05T10:30:00Z",
  "labels": ["producer", "configuration"],
  "error": null
}
```

### Content Formatting

The Markdown output preserves:

- **Headers**: H1-H6 converted to `#` syntax
- **Tables**: Converted to GitHub-flavored Markdown pipe format
- **Code Blocks**: Preserved with language hints when available
- **Lists**: Ordered and unordered lists
- **Links**: Inline Markdown links
- **Bold/Italic**: Standard Markdown formatting

### Truncation Behavior

When content exceeds 12,000 characters:
1. Finds a natural break point (paragraph > sentence > word)
2. Never cuts mid-word or mid-sentence
3. Appends: `\n\n---\n*[Content truncated. View full page at: {url}]*`

### Example

```json
{
  "name": "read_page",
  "arguments": {
    "page_id": "12345678"
  }
}
```

### Error Cases

```json
{
  "page_id": "99999999",
  "title": null,
  "url": null,
  "content": null,
  "error": "Page not found: 99999999"
}
```

---

## get_child_pages

List all direct child pages of a given Confluence page.

### Description

Returns a list of pages that are immediate children in the Confluence page hierarchy. Useful for navigating documentation structure and discovering related content.

### Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `page_id` | string | Yes | - | Parent page ID |
| `limit` | integer | No | 50 | Maximum children to return (1-100) |

### Returns

```json
[
  {
    "page_id": "23456789",
    "title": "Producer Quickstart",
    "url": "https://cwiki.apache.org/confluence/pages/viewpage.action?pageId=23456789"
  },
  {
    "page_id": "34567890",
    "title": "Producer Best Practices",
    "url": "https://cwiki.apache.org/confluence/pages/viewpage.action?pageId=34567890"
  },
  {
    "page_id": "45678901",
    "title": "Producer Troubleshooting",
    "url": "https://cwiki.apache.org/confluence/pages/viewpage.action?pageId=45678901"
  }
]
```

### Example

```json
{
  "name": "get_child_pages",
  "arguments": {
    "page_id": "12345678",
    "limit": 20
  }
}
```

### Notes

- Returns only **direct children**, not grandchildren or deeper descendants
- Order matches the Confluence page tree order
- Empty array returned if page has no children or page doesn't exist

---

## get_page_metadata

Get metadata for a page without fetching the full content.

### Description

A lightweight call that retrieves page information quickly without the overhead of fetching and processing full content. Useful for:
- Checking if a page exists
- Getting labels and version info
- Finding parent page
- Verification before expensive operations

### Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `page_id` | string | Yes | Confluence page ID |

### Returns

```json
{
  "page_id": "12345678",
  "title": "Kafka Producer Configuration",
  "url": "https://cwiki.apache.org/confluence/pages/viewpage.action?pageId=12345678",
  "space_key": "KAFKA",
  "parent_id": "11111111",
  "version": 42,
  "last_updated": "2024-01-05T10:30:00Z",
  "last_updated_by": "john.doe@example.com",
  "labels": ["producer", "configuration", "best-practices"],
  "error": null
}
```

### Example

```json
{
  "name": "get_page_metadata",
  "arguments": {
    "page_id": "12345678"
  }
}
```

### Notes

- **Faster** than `read_page` (no content processing)
- `parent_id` is `null` for top-level pages (space homepages)
- `version` is the revision number (useful for detecting changes)

---

## summarize_page

Generate a grounded summary of a single Confluence page.

### Description

Fetches a page's live content and produces a bullet-point summary using an LLM with strict grounding constraints. The LLM is instructed to:

1. Extract only factual information present in the document
2. Cite the section each fact comes from
3. Never add external knowledge
4. Return "NOT_FOUND" if content is too sparse

### Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `page_id` | string | Yes | Confluence page ID |

### Returns

```json
{
  "page_id": "12345678",
  "title": "SWIFT Message Overview",
  "url": "https://confluence.example.com/pages/viewpage.action?pageId=12345678",
  "summary": [
    "[Overview] SWIFT is the global standard for secure financial messaging between 11,000+ institutions.",
    "[Message Types] Two main formats: MT (legacy, tag-based) and MX (modern, XML-based ISO 20022).",
    "[Security] Uses a multi-layered security model including PKI, hardware security modules, and mandatory dual-control.",
    "[Network] The SWIFTNet network operates 24/7 with guaranteed message delivery and non-repudiation."
  ],
  "grounding_score": 0.91,
  "is_grounded": true,
  "source_sections": ["Overview", "Message Types", "Security", "Network"],
  "warning": null,
  "error": null
}
```

### Example

```json
{
  "name": "summarize_page",
  "arguments": {
    "page_id": "12345678"
  }
}
```

### When to Use

- When you have a specific page ID and want key points
- When the user asks "summarize this page" or "what's on this page"
- For multi-page summaries, use `search_and_summarize` instead

---

## answer_from_page

Answer a specific question using ONLY content from a single page.

### Description

Query-focused extraction from a specific page. Unlike `search_and_summarize`, this tool:

1. Takes both the page ID AND the user's question
2. The LLM sees both the document AND the question
3. Strict prompting ensures answers come only from the document
4. Returns `found_in_document: false` if content doesn't answer the question

### Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `page_id` | string | Yes | Confluence page ID |
| `question` | string | Yes | Specific question to answer |

### Returns

**Answer Found:**
```json
{
  "page_id": "12345678",
  "title": "SWIFT Configuration Guide",
  "url": "https://...",
  "question": "What is the default connection timeout?",
  "answer": [
    "[Configuration Section] The default connection timeout is 30 seconds, configurable via the swift.connection.timeout property."
  ],
  "found_in_document": true,
  "grounding_score": 0.95,
  "is_grounded": true,
  "warning": null,
  "error": null
}
```

**Answer Not Found:**
```json
{
  "page_id": "12345678",
  "title": "SWIFT Configuration Guide",
  "url": "https://...",
  "question": "What is the maximum number of retry attempts?",
  "answer": [
    "The document does not contain information about maximum retry attempts."
  ],
  "found_in_document": false,
  "grounding_score": 1.0,
  "is_grounded": true,
  "warning": null,
  "error": null
}
```

### Example

```json
{
  "name": "answer_from_page",
  "arguments": {
    "page_id": "12345678",
    "question": "What authentication methods are supported?"
  }
}
```

### When to Use

- When you know which specific page has the answer
- When the user references a specific document
- For precise fact extraction from known sources

---

## Error Handling

All tools follow a consistent error handling pattern and never throw exceptions to the caller.

### Error Response Format

Every tool includes an `error` field that is `null` on success:

```json
{
  "...other fields...",
  "error": null
}
```

Or contains a descriptive message on failure:

```json
{
  "...other fields...",
  "error": "Page not found: 12345678"
}
```

### Common Error Types

| Error | Cause | Solution |
|-------|-------|----------|
| `Page not found: {id}` | Invalid or deleted page ID | Verify page exists in Confluence |
| `Connection timeout` | Network issues or Confluence down | Check network, retry later |
| `Rate limited` | Too many API calls | Automatic retry with backoff |
| `Qdrant unavailable` | Vector database not running | Run `docker-compose up -d` |
| `LLM unavailable` | LLM server not responding | Start LM Studio or check `LLM_BASE_URL` |
| `Query is required` | Empty query provided | Provide a non-empty query string |
| `Space not found` | Invalid space key | Verify `CONFLUENCE_SPACE_KEY` |

### Graceful Degradation

Tools are designed to return partial results when possible:

- If 3 of 5 pages fail to fetch, the other 2 are still summarized
- If reranking fails, results from initial search are returned
- If LLM is down, search results are returned without synthesis

---

## Rate Limits

### Confluence API Limits

The system automatically handles Confluence rate limiting:

| Behavior | Description |
|----------|-------------|
| **429 Detection** | Automatic detection of rate limit responses |
| **Retry-After** | Honors the `Retry-After` header when present |
| **Exponential Backoff** | 1s → 2s → 4s → 8s between retries |
| **Max Retries** | 3 attempts before returning error |

### MCP Server Limits

No rate limiting is applied at the MCP server level. The server processes requests as fast as upstream services allow.

### Recommended Usage

For best performance:
- Prefer `search_and_summarize` over multiple `read_page` calls
- Use `get_page_metadata` instead of `read_page` when you only need labels/version
- Batch related questions rather than asking one at a time

---

## Performance

### Typical Response Times

| Tool | P50 (Median) | P95 | P99 |
|------|--------------|-----|-----|
| `search_documentation` | 200ms | 400ms | 600ms |
| `read_page` | 500ms | 1.5s | 3s |
| `get_child_pages` | 300ms | 800ms | 1.5s |
| `get_page_metadata` | 200ms | 500ms | 1s |
| `summarize_page` | 2s | 5s | 8s |
| `answer_from_page` | 2s | 5s | 8s |
| `search_and_summarize` | 5s | 15s | 25s |

### Performance Factors

| Factor | Impact |
|--------|--------|
| Confluence API latency | Major (40-60% of time) |
| Content size | Moderate (larger pages = slower) |
| Number of sources | High (for synthesis tools) |
| LLM response time | High (varies by model) |
| Network quality | Moderate |

### Optimization Tips

1. **Use appropriate max_sources**: Start with 3-5, increase only if needed
2. **Cache results client-side**: If making repeated queries
3. **Use metadata first**: Check if page exists before fetching content
4. **Prefer synthesis**: One `search_and_summarize` beats five `read_page` calls

---

## Changelog

| Version | Date | Changes |
|---------|------|---------|
| 1.0.0 | 2026-01-06 | Initial release with 7 tools |
