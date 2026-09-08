# -*- coding: utf-8 -*-
"""FastAPI Route Definitions for DCC Pipeline Automation API.

Provides endpoints for health probing, job submission, snapshot queries,
human-in-the-loop gate approvals, and SSE streaming.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import StreamingResponse
import httpx

from dcc_agent.api.manager import PipelineJobManager
from dcc_agent.api.schemas import (
    ApprovalRequest,
    ApprovalResponse,
    EngineHealthResponse,
    JobListResponse,
    JobStatusResponse,
    JobSubmitRequest,
)
from dcc_agent.config import settings
from dcc_agent.core.mcp_client import UENativeMCPClient

logger = logging.getLogger("PipelineRoutes")

router = APIRouter(prefix="/api/v1", tags=["DCC Pipeline Automation"])


async def check_ollama_health() -> bool:
    """Probes the remote Ollama server on Mac M5."""
    try:
        url = f"{settings.ollama_base_url.rstrip('/')}/models"
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(url)
            return resp.status_code == 200
    except Exception:
        return False


@router.get("/health", response_model=EngineHealthResponse, summary="Probe Multi-DCC & AI Cluster Health")
async def get_health() -> EngineHealthResponse:
    """Checks the live connectivity of FastAPI, UE 5.8 MCP, and Mac M5 Ollama."""
    # 1. Probe UE 5.8 Native MCP
    ue_online = False
    try:
        client = UENativeMCPClient()
        ue_online = await client.is_online()
        await client.close()
    except Exception as e:
        logger.warning("UE MCP health probe failed: %s", e)

    # 2. Probe Mac M5 Ollama
    ollama_online = await check_ollama_health()

    # 3. Overall status determination
    if ue_online and ollama_online:
        cluster_status = "healthy"
    elif ue_online or ollama_online:
        cluster_status = "degraded"
    else:
        cluster_status = "unhealthy"

    manager = PipelineJobManager.get_instance()
    active_count = manager.get_active_count()

    return EngineHealthResponse(
        status=cluster_status,
        fastapi=True,
        ue_mcp=ue_online,
        ue_mcp_url=settings.ue_mcp_url,
        ollama=ollama_online,
        ollama_url=settings.ollama_base_url,
        active_jobs=active_count,
        details={
            "default_model": settings.default_model,
            "heavy_model": settings.heavy_model,
            "max_retries": settings.max_retries,
        },
    )


@router.post(
    "/jobs",
    response_model=JobStatusResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Submit Natural Language Pipeline Task",
)
async def submit_job(req: JobSubmitRequest) -> JobStatusResponse:
    """Submits a TA pipeline instruction and begins asynchronous state machine execution."""
    manager = PipelineJobManager.get_instance()
    job = await manager.submit_job(req)
    return job.to_response()


@router.get("/jobs", response_model=JobListResponse, summary="List All Pipeline Jobs")
async def list_jobs() -> JobListResponse:
    """Lists all active and historical pipeline jobs."""
    manager = PipelineJobManager.get_instance()
    jobs = [j.to_response() for j in manager.list_jobs()]
    return JobListResponse(total=len(jobs), jobs=jobs)


@router.get("/jobs/{job_id}", response_model=JobStatusResponse, summary="Query Job Snapshot & Audit Trail")
async def get_job_status(job_id: str) -> JobStatusResponse:
    """Retrieves full runtime snapshot, audit logs, and status for a specific job."""
    manager = PipelineJobManager.get_instance()
    job = manager.get_job(job_id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job '{job_id}' not found.",
        )
    return job.to_response()


@router.post(
    "/jobs/{job_id}/approve",
    response_model=ApprovalResponse,
    summary="Lead TA Authorization Gate for High-Risk Jobs",
)
async def approve_job(job_id: str, req: ApprovalRequest) -> ApprovalResponse:
    """Authorizes or rejects a pipeline job suspended at the Human Approval Gate."""
    manager = PipelineJobManager.get_instance()
    try:
        job = await manager.approve_job(job_id, approved=req.approved, comment=req.comment)
        msg = "Lead TA 已授权放行高危执行" if req.approved else "Lead TA 已拒绝执行，任务安全中止"
        return ApprovalResponse(
            job_id=job.job_id,
            status=job.status,
            approved=req.approved,
            message=msg,
        )
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job '{job_id}' not found.",
        )
    except ValueError as err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(err),
        )


@router.get(
    "/jobs/{job_id}/stream",
    summary="Server-Sent Events (SSE) Real-Time Node Execution Stream",
    response_class=StreamingResponse,
)
async def stream_job(job_id: str):
    """Streams live LangGraph node updates, audit log items, and gate pause notifications via SSE."""
    manager = PipelineJobManager.get_instance()
    job = manager.get_job(job_id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job '{job_id}' not found.",
        )

    async def event_generator():
        try:
            async for event in manager.stream_job_events(job_id):
                payload = json.dumps(event, ensure_ascii=False)
                yield f"data: {payload}\n\n"
        except Exception as exc:
            logger.exception("SSE stream exception for job %s: %s", job_id, exc)
            err_payload = json.dumps({"event": "error", "error": str(exc)}, ensure_ascii=False)
            yield f"data: {err_payload}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "Content-Type": "text/event-stream; charset=utf-8",
        },
    )
