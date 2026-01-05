"""
MCP Server - STDIO Transport

MCP server with STDIO transport for Claude Desktop integration.
Reads JSON-RPC from stdin, writes responses to stdout.

Usage:
    python -m mcp.stdio_server

Claude Desktop Configuration (claude_desktop_config.json):
    {
      "mcpServers": {
        "confluence": {
          "command": "python",
          "args": ["-m", "mcp.stdio_server"],
          "cwd": "/path/to/enterprise_confluence_ai"
        }
      }
    }
"""

import asyncio
import json
import logging
import sys
from typing import Any, Dict, List

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from mcp import tools as tool_impl

# Configure logging to stderr (stdout is for MCP protocol)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger(__name__)


# Create MCP server
mcp_server = Server("confluence-navigator")


# ========== Tool Definitions ==========

@mcp_server.list_tools()
async def list_tools() -> List[Tool]:
    """Return list of available tools."""
    return [
        Tool(
            name="search_documentation",
            description="Search Confluence documentation using hybrid search with reranking. Returns page titles, URLs, excerpts, and relevance scores. Does NOT return full content - use read_page for that.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query text",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of results to return (default: 5, max: 20)",
                        "default": 5,
                    },
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="read_page",
            description="Fetch the full, live content of a Confluence page. Content is fetched fresh from Confluence (not cached), converted to Markdown format, and truncated at 12k chars if needed.",
            inputSchema={
                "type": "object",
                "properties": {
                    "page_id": {
                        "type": "string",
                        "description": "The Confluence page ID to fetch",
                    },
                },
                "required": ["page_id"],
            },
        ),
        Tool(
            name="get_child_pages",
            description="List all child pages of a given Confluence page. Use this to navigate the page hierarchy and discover related content.",
            inputSchema={
                "type": "object",
                "properties": {
                    "page_id": {
                        "type": "string",
                        "description": "The parent page ID",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of children to return (default: 50)",
                        "default": 50,
                    },
                },
                "required": ["page_id"],
            },
        ),
        Tool(
            name="get_page_metadata",
            description="Get metadata for a Confluence page without fetching content. Use this for quick page info lookup.",
            inputSchema={
                "type": "object",
                "properties": {
                    "page_id": {
                        "type": "string",
                        "description": "The Confluence page ID",
                    },
                },
                "required": ["page_id"],
            },
        ),
        Tool(
            name="summarize_page",
            description="Generate a grounded summary of a Confluence page. Uses LLM with STRICT rules: only document content is used, no external knowledge. Returns bullet points with citations and grounding score.",
            inputSchema={
                "type": "object",
                "properties": {
                    "page_id": {
                        "type": "string",
                        "description": "The Confluence page ID to summarize",
                    },
                },
                "required": ["page_id"],
            },
        ),
        Tool(
            name="answer_from_page",
            description="Answer a question using ONLY content from a specific page. LLM uses strict grounding rules - no external knowledge. If answer not found, explicitly says so. Returns grounded extraction with citations.",
            inputSchema={
                "type": "object",
                "properties": {
                    "page_id": {
                        "type": "string",
                        "description": "The Confluence page ID",
                    },
                    "question": {
                        "type": "string",
                        "description": "The question to answer from the page content",
                    },
                },
                "required": ["page_id", "question"],
            },
        ),
        Tool(
            name="search_and_summarize",
            description="🎯 MAIN TOOL: Takes a question, searches for relevant pages, fetches live content, produces a grounded summary sourced ONLY from documents. LLM sees only documents, not the question - preventing hallucination.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "User's question or topic (e.g., 'What is a SWIFT message?')",
                    },
                    "max_sources": {
                        "type": "integer",
                        "description": "Maximum documents to synthesize (default: 5)",
                        "default": 5,
                    },
                },
                "required": ["query"],
            },
        ),
    ]


@mcp_server.call_tool()
async def call_tool(name: str, arguments: Dict[str, Any]) -> List[TextContent]:
    """Execute a tool and return results."""
    logger.info(f"Tool call: {name} with args: {arguments}")
    
    try:
        if name == "search_documentation":
            result = tool_impl.search_documentation(
                query=arguments.get("query", ""),
                limit=arguments.get("limit", 5),
            )
        elif name == "read_page":
            result = tool_impl.read_page(
                page_id=arguments.get("page_id", ""),
            )
        elif name == "get_child_pages":
            result = tool_impl.get_child_pages(
                page_id=arguments.get("page_id", ""),
                limit=arguments.get("limit", 50),
            )
        elif name == "get_page_metadata":
            result = tool_impl.get_page_metadata(
                page_id=arguments.get("page_id", ""),
            )
        elif name == "summarize_page":
            result = tool_impl.summarize_page(
                page_id=arguments.get("page_id", ""),
            )
        elif name == "answer_from_page":
            result = tool_impl.answer_from_page(
                page_id=arguments.get("page_id", ""),
                question=arguments.get("question", ""),
            )
        elif name == "search_and_summarize":
            result = tool_impl.search_and_summarize(
                query=arguments.get("query", ""),
                max_sources=arguments.get("max_sources", 5),
            )
        else:
            result = {"error": f"Unknown tool: {name}"}
        
        # Convert result to JSON string
        result_text = json.dumps(result, indent=2, ensure_ascii=False)
        return [TextContent(type="text", text=result_text)]
        
    except Exception as e:
        logger.error(f"Tool {name} failed: {e}")
        error_result = json.dumps({"error": str(e)})
        return [TextContent(type="text", text=error_result)]


async def main():
    """Run the STDIO server."""
    logger.info("Starting MCP STDIO server for Claude Desktop")
    
    async with stdio_server() as (read_stream, write_stream):
        await mcp_server.run(
            read_stream,
            write_stream,
            mcp_server.create_initialization_options(),
        )


if __name__ == "__main__":
    asyncio.run(main())
