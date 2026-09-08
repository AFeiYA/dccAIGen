# -*- coding: utf-8 -*-
"""Pydantic Request and Response Schemas for DCC Pipeline FastAPI Service.

Defines strongly-typed data transfer contracts for job submission, status querying,
human-in-the-loop approval, and DCC engine health probing.
"""

from __future__ import annotations

from enum import Enum
import time
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class JobStatus(str, Enum):
    """Execution lifecycle status of an automated pipeline job."""
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    ABORTED = "ABORTED"


class JobSubmitRequest(BaseModel):
    """Payload to submit a natural language pipeline automation task."""
    user_query: str = Field(
        ...,
        min_length=1,
        description="Natural language instruction for the pipeline agent.",
        examples=["清理未合规命名的网格资产，并核对当前工具集列表"],
    )
    target_dcc: str = Field(
        default="Unreal Engine 5.8",
        description="Target DCC environment or engine name.",
    )
    auto_approve: bool = Field(
        default=False,
        description="Whether to bypass human-in-the-loop gate for high-risk operations.",
    )
    job_id: Optional[str] = Field(
        default=None,
        description="Optional custom identifier for the job session.",
    )


class JobStatusResponse(BaseModel):
    """Detailed runtime snapshot of a pipeline job."""
    job_id: str
    status: JobStatus
    user_query: str
    target_dcc: str
    is_high_risk: bool = False
    human_approved: Optional[bool] = None
    is_success: bool = False
    retry_count: int = 0
    max_retries: int = 2
    audit_trail: List[str] = Field(default_factory=list)
    execution_result: Dict[str, Any] = Field(default_factory=dict)
    error_message: Optional[str] = None
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)


class JobListResponse(BaseModel):
    """Paginated or listed summary of all registered jobs."""
    total: int
    jobs: List[JobStatusResponse]


class ApprovalRequest(BaseModel):
    """Lead TA authorization payload for high-risk gate execution."""
    approved: bool = Field(
        default=True,
        description="True to authorize high-risk execution, False to abort safely.",
    )
    comment: Optional[str] = Field(
        default=None,
        description="Optional audit remark or note from Lead TA.",
    )


class ApprovalResponse(BaseModel):
    """Result of the gate authorization action."""
    job_id: str
    status: JobStatus
    approved: bool
    message: str


class EngineHealthResponse(BaseModel):
    """Multi-DCC and AI infrastructure connectivity status."""
    status: str = Field(description="'healthy', 'degraded', or 'unhealthy'")
    fastapi: bool = True
    ue_mcp: bool
    ue_mcp_url: str
    ollama: bool
    ollama_url: str
    active_jobs: int
    details: Dict[str, Any] = Field(default_factory=dict)


class StreamEventMessage(BaseModel):
    """Server-Sent Event (SSE) packet structure."""
    event: str
    job_id: str
    timestamp: float = Field(default_factory=time.time)
    data: Dict[str, Any] = Field(default_factory=dict)
