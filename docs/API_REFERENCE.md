# API Reference

## MCP Tools

This document describes the seven MCP tools exposed by the MCP-based Confluence RAG.

---

## Overview

### 🎯 Main Tool

| Tool | Purpose | Returns |
|------|---------|---------|
| `search_and_summarize` | **Complete pipeline**: search → fetch → grounded synthesis | Summary with citations and sources |

### Supporting Tools

| Tool | Purpose | Returns |
|------|---------|---------|
| `search_documentation` | Find relevant pages | List of page summaries |
| `read_page` | Get full page content | Page content in Markdown |
| `get_child_pages` | Navigate hierarchy | List of child pages |
| `get_page_metadata` | Quick page info | Page metadata |
| `summarize_page` | Summarize single page | Grounded summary |
| `answer_from_page` | Q&A from single page | Grounded answer |

---

## search_documentation

Search Confluence documentation using hybrid search with reranking.

### Description

Performs a hybrid search combining:
1. **Dense embeddings** for semantic similarity
2. **Sparse embeddings** for keyword matching
3. **RRF fusion** to combine results
4. **Cross-encoder reranking** for final ordering

Returns page summaries, NOT full content. Use `read_page` to get content.

### Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `query` | string | Yes | - | Search query text |
| `limit` | integer | No | 5 | Max results (1-20) |

### Returns

Array of search results:

```json
[
  {
    "page_id": "12345678",
    "title": "Kafka Producer Configuration",
    "url": "https://cwiki.apache.org/confluence/pages/viewpage.action?pageId=12345678",
    "score": 0.94,
    "excerpt": "The Kafka producer is responsible for...",
    "space_key": "KAFKA",
    "labels": ["producer", "configuration"],
    "headers": ["Overview", "Required Settings", "Optional Settings"]
  }
]
```

### Example

```json
{
  "name": "search_documentation",
  "arguments": {
    "query": "kafka producer acknowledgement settings",
    "limit": 5
  }
}
```

### Notes

- Query is case-insensitive
- Both semantic and keyword matches are found
- Empty query returns empty array
- Score ranges from 0.0 to 1.0

---

## 🎯 search_and_summarize

**THE MAIN TOOL** - Complete document-grounded synthesis pipeline.

### Description

Complete pipeline that:
1. Takes a user question
2. Searches for relevant pages
3. Fetches LIVE content from all found pages
4. Combines content into context
5. LLM produces grounded summary (sees ONLY documents, NOT the question)
6. Validates grounding score

**CRITICAL**: The LLM never sees the user's question - only the documents. This prevents hallucination.

### Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `query` | string | Yes | - | User's question or topic |
| `max_sources` | integer | No | 5 | Max documents to synthesize (1-10) |

### Returns

```json
{
  "query": "What is a SWIFT message and its formats?",
  "summary": [
    "[Source: SWIFT Overview] SWIFT is a network for financial messaging...",
    "[Source: Message Types] MT messages use tag-based format...",
    "[Source: ISO 20022] MX messages use XML schema..."
  ],
  "sources": [
    {"page_id": "123", "title": "SWIFT Overview", "url": "..."},
    {"page_id": "456", "title": "Message Types", "url": "..."}
  ],
  "grounding_score": 0.87,
  "is_grounded": true,
  "total_sources": 3,
  "warning": null,
  "error": null
}
```

### Example

```json
{
  "name": "search_and_summarize",
  "arguments": {
    "query": "What is a SWIFT message and its formats?",
    "max_sources": 5
  }
}
```

### Grounding Score

| Score | Interpretation |
|-------|----------------|
| 0.8+ | Excellent - summary fully grounded |
| 0.6-0.8 | Good - mostly grounded |
| 0.5-0.6 | Borderline - review recommended |
| < 0.5 | Warning - possible hallucination |

### Notes

- LLM sees ONLY fetched documents, NOT user's question
- Each bullet point cites its source document
- Grounding validated via token overlap analysis
- "Not found" returned if no relevant pages exist

---

## read_page

Fetch the full, live content of a Confluence page.

### Description

Retrieves the current version of a page directly from Confluence (not cached), converts HTML to Markdown, and applies smart truncation if the content exceeds 12,000 characters.

### Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `page_id` | string | Yes | Confluence page ID |

### Returns

Page content object:

```json
{
  "page_id": "12345678",
  "title": "Kafka Producer Configuration",
  "url": "https://cwiki.apache.org/confluence/pages/viewpage.action?pageId=12345678",
  "content": "# Kafka Producer Configuration\n\nThe producer is...",
  "is_truncated": false,
  "last_updated": "2024-01-05T10:30:00Z",
  "labels": ["producer", "configuration"],
  "error": null
}
```

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

**Page not found:**
```json
{
  "page_id": "99999999",
  "error": "Page not found: 99999999"
}
```

**Connection error:**
```json
{
  "page_id": "12345678",
  "error": "Connection timeout to Confluence API"
}
```

### Notes

- Content is always fetched live (zero staleness)
- HTML tables are converted to Markdown pipe format
- Code blocks preserve language hints
- Truncation never cuts mid-sentence

---

## get_child_pages

List all child pages of a given Confluence page.

### Description

Returns a list of direct child pages for navigation. Use this to explore the page hierarchy and discover related content.

### Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `page_id` | string | Yes | - | Parent page ID |
| `limit` | integer | No | 50 | Max children (1-100) |

### Returns

Array of child page summaries:

```json
[
  {
    "page_id": "23456789",
    "title": "Producer Quickstart",
    "url": "https://..."
  },
  {
    "page_id": "34567890",
    "title": "Producer Best Practices",
    "url": "https://..."
  }
]
```

### Example

```json
{
  "name": "get_child_pages",
  "arguments": {
    "page_id": "12345678",
    "limit": 10
  }
}
```

### Notes

- Only returns direct children, not grandchildren
- Empty array if no children or page not found
- Order matches Confluence page tree order

---

## get_page_metadata

Get metadata for a page without fetching full content.

### Description

Retrieves page information quickly without the overhead of fetching and processing the full content. Useful for checking page details before deciding to read it.

### Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `page_id` | string | Yes | Confluence page ID |

### Returns

Page metadata object:

```json
{
  "page_id": "12345678",
  "title": "Kafka Producer Configuration",
  "url": "https://cwiki.apache.org/confluence/pages/viewpage.action?pageId=12345678",
  "space_key": "KAFKA",
  "parent_id": "11111111",
  "version": 42,
  "last_updated": "2024-01-05T10:30:00Z",
  "labels": ["producer", "configuration"]
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

- Faster than `read_page` (no content processing)
- `parent_id` is null for top-level pages
- `version` is the revision number

---

## summarize_page

Generate a grounded summary of a single Confluence page.

### Description

Fetches page content live and produces a summary using LLM with strict grounding rules. The LLM sees ONLY the document content, no external knowledge is allowed.

### Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `page_id` | string | Yes | Confluence page ID |

### Returns

```json
{
  "page_id": "12345678",
  "title": "SWIFT Message Overview",
  "url": "https://...",
  "summary": [
    "[Overview] SWIFT enables secure financial messaging...",
    "[Standards] Uses ISO 15022 and ISO 20022 formats..."
  ],
  "grounding_score": 0.91,
  "is_grounded": true,
  "source_sections": ["Overview", "Standards"],
  "warning": null,
  "error": null
}
```

### Notes

- For single-page summaries only
- Use `search_and_summarize` for multi-document synthesis

---

## answer_from_page

Answer a question using ONLY content from a specific page.

### Description

Query-focused extraction from a single page. The LLM receives both the question AND the document, but strict prompting ensures answers come only from the document.

### Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `page_id` | string | Yes | Confluence page ID |
| `question` | string | Yes | Question to answer |

### Returns

```json
{
  "page_id": "12345678",
  "title": "SWIFT Configuration",
  "url": "https://...",
  "question": "What is the default timeout?",
  "answer": [
    "[Configuration] The default timeout is 30 seconds"
  ],
  "found_in_document": true,
  "grounding_score": 0.95,
  "is_grounded": true,
  "warning": null,
  "error": null
}
```

### Not Found Example

```json
{
  "question": "What is the maximum retries?",
  "answer": ["The document does not contain information about this question."],
  "found_in_document": false,
  "grounding_score": 1.0,
  "is_grounded": true
}
```

---

## Error Handling

All tools handle errors gracefully and return structured error responses:

### Common Error Format

```json
{
  "error": "Error description here"
}
```

### Error Types

| Error | Cause | Solution |
|-------|-------|----------|
| Page not found | Invalid page_id | Verify page exists in Confluence |
| Connection timeout | Network/API issues | Check Confluence availability |
| Rate limited | Too many requests | Wait and retry (auto-handled) |
| Qdrant unavailable | Vector DB down | Check `docker-compose up -d` |
| LLM unavailable | LLM server not running | Start LM Studio or configure LLM_BASE_URL |

---

## Rate Limits

The system respects Confluence rate limits:

- **429 responses**: Automatic exponential backoff
- **Retry-After header**: Honored when present
- **Default timeout**: 40 seconds per request

No rate limiting on the MCP server side.

---

## Performance

Typical response times:

| Tool | P50 | P95 |
|------|-----|-----|
| search_documentation | 200ms | 400ms |
| read_page | 500ms | 1500ms |
| get_child_pages | 300ms | 800ms |
| get_page_metadata | 200ms | 500ms |
| summarize_page | 2s | 5s |
| answer_from_page | 2s | 5s |
| search_and_summarize | 5s | 15s |

Factors affecting performance:
- Confluence API latency
- Content size
- Number of sources (for search_and_summarize)
- LLM response time
