"""
MCP-based Confluence RAG - Configuration Settings

Centralized Pydantic settings for the MCP-based Confluence RAG system.
All configuration is loaded from environment variables with sensible defaults.

Environment variables can be set in:
1. .env file (base config)
2. .env.local file (local overrides)
3. System environment (highest priority)
"""

from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Central application settings loaded from environment variables."""

    # ========== Confluence API ==========
    confluence_base_url: str = Field(
        default="",
        alias="CONFLUENCE_BASE_URL",
        description="Base URL for Confluence instance (REQUIRED - e.g., https://your-org.atlassian.net/wiki)"
    )
    confluence_space_key: str = Field(
        default="",
        alias="CONFLUENCE_SPACE_KEY",
        description="Confluence space key to index (REQUIRED)"
    )
    confluence_pat: str = Field(
        default="",
        alias="CONFLUENCE_PAT",
        description="Personal Access Token (REQUIRED - or use 'anonymous' for public Confluence)"
    )

    # ========== Qdrant Vector DB ==========
    qdrant_url: str = Field(
        default="http://localhost:6333",
        alias="QDRANT_URL",
        description="Qdrant server URL"
    )
    qdrant_collection: str = Field(
        default="skeleton_vectors",
        alias="QDRANT_COLLECTION",
        description="Qdrant collection name for skeleton vectors"
    )

    # ========== Local Models ==========
    fastembed_cache_path: str = Field(
        default="./models_cache",
        alias="FASTEMBED_CACHE_PATH",
        description="Path to local FastEmbed model cache"
    )
    dense_model: str = Field(
        default="BAAI/bge-small-en-v1.5",
        alias="DENSE_MODEL",
        description="Dense embedding model name"
    )
    sparse_model: str = Field(
        default="prithivida/Splade_PP_en_v1",
        alias="SPARSE_MODEL",
        description="Sparse embedding model name"
    )
    rerank_model: str = Field(
        default="ms-marco-TinyBERT-L-2-v2",
        alias="RERANK_MODEL",
        description="FlashRank reranker model name"
    )

    # ========== LLM (Optional, for chat features) ==========
    llm_base_url: str = Field(
        default="http://localhost:1234/v1",
        alias="LLM_BASE_URL",
        description="OpenAI-compatible LLM server URL"
    )
    llm_model: str = Field(
        default="local-model",
        alias="LLM_MODEL",
        description="LLM model name"
    )

    # ========== MCP Server ==========
    mcp_sse_host: str = Field(
        default="0.0.0.0",
        alias="MCP_SSE_HOST",
        description="Host for MCP SSE server"
    )
    mcp_sse_port: int = Field(
        default=8080,
        alias="MCP_SSE_PORT",
        description="Port for MCP SSE server"
    )

    # ========== Search Parameters ==========
    search_top_k: int = Field(
        default=5,
        alias="SEARCH_TOP_K",
        description="Default number of results to return"
    )
    search_fetch_multiplier: int = Field(
        default=4,
        alias="SEARCH_FETCH_MULTIPLIER",
        description="Multiplier for initial fetch before reranking"
    )
    max_content_chars: int = Field(
        default=12000,
        alias="MAX_CONTENT_CHARS",
        description="Maximum characters for page content"
    )

    # ========== Ingestion Parameters ==========
    ingestion_batch_size: int = Field(
        default=64,
        alias="INGESTION_BATCH_SIZE",
        description="Batch size for embedding generation"
    )
    ingestion_max_pages: int = Field(
        default=2000,
        alias="INGESTION_MAX_PAGES",
        description="Maximum pages to index"
    )

    # ========== Pydantic Config ==========
    model_config = {
        "env_file": [".env", ".env.local"],
        "env_file_encoding": "utf-8",
        "case_sensitive": False,
        "extra": "ignore",
    }

    @property
    def models_cache_path(self) -> Path:
        """Return resolved path to models cache directory."""
        return Path(self.fastembed_cache_path).resolve()

    @field_validator("confluence_base_url")
    @classmethod
    def validate_confluence_url(cls, v: str) -> str:
        """Validate Confluence URL is provided."""
        if not v or not v.strip():
            raise ValueError(
                "CONFLUENCE_BASE_URL is required. "
                "Set it in .env file (e.g., https://your-org.atlassian.net/wiki)"
            )
        # Remove trailing slash for consistency
        return v.rstrip("/")

    @field_validator("confluence_space_key")
    @classmethod
    def validate_space_key(cls, v: str) -> str:
        """Validate Confluence space key is provided."""
        if not v or not v.strip():
            raise ValueError(
                "CONFLUENCE_SPACE_KEY is required. "
                "Set it in .env file (e.g., MYSPACE)"
            )
        return v.strip().upper()

    @field_validator("confluence_pat")
    @classmethod
    def validate_pat(cls, v: str) -> str:
        """Validate PAT is provided (can be 'anonymous' for public Confluence)."""
        if not v or not v.strip():
            raise ValueError(
                "CONFLUENCE_PAT is required. "
                "Use 'anonymous' for public Confluence or provide a Personal Access Token."
            )
        return v.strip()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached Settings instance."""
    return Settings()


# Global settings instance
settings = get_settings()