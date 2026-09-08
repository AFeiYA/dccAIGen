# -*- coding: utf-8 -*-
"""FastAPI Application Factory for DCC Pipeline AI Agent.

Configures OpenAPI docs, CORS middleware for DCC Slate WebBrowser / Frontend integration,
lifespan hooks, and mounts the v1 pipeline router.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
import logging
import sys
from typing import AsyncGenerator

# Ensure UTF-8 output on Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from dcc_agent.api.manager import PipelineJobManager
from dcc_agent.api.routes import router as api_v1_router
from dcc_agent.config import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("DCCPipelineAPI")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Lifespan event handler for startup and graceful shutdown."""
    logger.info("Initializing DCC Pipeline AI Agent Microservice...")
    logger.info("Target UE MCP: %s", settings.ue_mcp_url)
    logger.info("Inference Cluster: %s", settings.ollama_base_url)
    # Warm up singleton job manager and LangGraph app
    manager = PipelineJobManager.get_instance()
    logger.info("LangGraph pipeline state machine initialized with checkpointer.")
    yield
    logger.info("DCC Pipeline API service shutting down.")


app = FastAPI(
    title="DCC Pipeline AI Agent Microservice",
    description=(
        "Enterprise-grade REST & SSE microservice for automated game asset pipelines. "
        "Orchestrates Unreal Engine 5.8 Native MCP, Mac M5 Ollama LLM cluster, "
        "LangGraph self-healing state machine, and Lead TA Human-in-the-Loop approvals."
    ),
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# Enable CORS for cross-domain Web UI, React/Vue dashboards, or in-engine Slate WebBrowser
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register API routes
app.include_router(api_v1_router)


@app.get("/", summary="Service Metadata & Quick Links", tags=["Root"])
async def root():
    """Welcome endpoint providing service metadata and OpenAPI links."""
    return {
        "service": "DCC Pipeline AI Agent Microservice",
        "version": "1.0.0",
        "status": "online",
        "docs_url": "/docs",
        "health_check": "/api/v1/health",
        "endpoints": {
            "health": "GET /api/v1/health",
            "submit_job": "POST /api/v1/jobs",
            "list_jobs": "GET /api/v1/jobs",
            "get_job": "GET /api/v1/jobs/{job_id}",
            "approve_gate": "POST /api/v1/jobs/{job_id}/approve",
            "sse_stream": "GET /api/v1/jobs/{job_id}/stream",
        },
    }


def start_server():
    """CLI launcher entrypoint to start uvicorn server."""
    uvicorn.run(
        "dcc_agent.api.app:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=False,
        log_level="info",
    )


if __name__ == "__main__":
    start_server()
