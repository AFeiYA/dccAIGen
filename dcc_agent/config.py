# -*- coding: utf-8 -*-
"""Centralized Configuration Module for DCC Pipeline Agent.

Uses Pydantic and python-dotenv to provide environment-driven, strongly typed
configuration with safe defaults for local private dual-machine game studio setups.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import List

from dotenv import load_dotenv
from pydantic import BaseModel, Field

# Automatically load .env if present in workspace root
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


class PipelineSettings(BaseModel):
    """Global configuration settings for the DCC Pipeline Agent."""

    # Unreal Engine 5.8 Native MCP Settings
    ue_mcp_url: str = Field(
        default_factory=lambda: os.getenv("UE_MCP_URL", "http://127.0.0.1:8000/mcp"),
        description="Streamable HTTP JSON-RPC endpoint for Unreal Engine 5.8 ModelContextProtocol.",
    )
    ue_timeout: float = Field(
        default_factory=lambda: float(os.getenv("UE_TIMEOUT", "15.0")),
        description="HTTP request timeout in seconds for UE MCP commands.",
    )

    # Remote Ollama LLM Settings (Mac M5 Private Inference Node)
    ollama_base_url: str = Field(
        default_factory=lambda: os.getenv("OLLAMA_BASE_URL", "http://192.168.1.222:11434/v1"),
        description="OpenAI-compatible base URL for remote Ollama server on Mac M5.",
    )
    ollama_api_key: str = Field(
        default_factory=lambda: os.getenv("OLLAMA_API_KEY", "ollama"),
        description="API Key for Ollama proxy.",
    )
    default_model: str = Field(
        default_factory=lambda: os.getenv("OLLAMA_MODEL", "gemma4:12b-mlx"),
        description="Default fast LLM model for planning and reflection.",
    )
    heavy_model: str = Field(
        default_factory=lambda: os.getenv("OLLAMA_HEAVY_MODEL", "qwen3.6:27b-mlx"),
        description="High-capacity reasoning model for complex code generation.",
    )

    # RAG Vector Store & ChromaDB Settings
    chroma_persist_dir: str = Field(
        default_factory=lambda: os.getenv("CHROMA_PERSIST_DIR", str(BASE_DIR / "chroma_data")),
        description="Local directory for persistent ChromaDB storage.",
    )
    chroma_collection: str = Field(
        default_factory=lambda: os.getenv("CHROMA_COLLECTION", "dcc_knowledge_hub"),
        description="Target collection name in ChromaDB.",
    )

    # Agent Resilience & Risk Control
    max_retries: int = Field(
        default_factory=lambda: int(os.getenv("MAX_RETRIES", "2")),
        description="Maximum self-healing retry attempts before human escalation.",
    )
    high_risk_keywords: List[str] = Field(
        default=[
            "删除", "delete", "清理", "clean", "覆盖", "override",
            "批量重命名", "batch_rename", "清空", "purge", "drop",
        ],
        description="Keywords that automatically trigger human-in-the-loop approval gate.",
    )


# Export singleton instance
settings = PipelineSettings()
