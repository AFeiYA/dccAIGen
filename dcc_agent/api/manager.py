# -*- coding: utf-8 -*-
"""Asynchronous Pipeline Job Manager for DCC FastAPI Microservice.

Handles concurrent LangGraph state machine executions, checkpointing, SSE event
streaming to in-editor Slate/Web clients, and Human-in-the-Loop gate coordination.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Any, AsyncGenerator, Dict, List, Optional, Set

from langgraph.checkpoint.memory import MemorySaver

from dcc_agent.api.schemas import (
    JobStatus,
    JobStatusResponse,
    JobSubmitRequest,
)
from dcc_agent.config import settings
from dcc_agent.graph.state import AgentPipelineState
from dcc_agent.graph.workflow import create_pipeline_app

logger = logging.getLogger("PipelineJobManager")


class JobRecord:
    """Represents a tracked pipeline execution job session."""

    def __init__(
        self,
        job_id: str,
        user_query: str,
        target_dcc: str,
        auto_approve: bool = False,
    ) -> None:
        self.job_id = job_id
        self.user_query = user_query
        self.target_dcc = target_dcc
        self.auto_approve = auto_approve

        self.status = JobStatus.PENDING
        self.is_high_risk = False
        self.human_approved: Optional[bool] = None
        self.is_success = False
        self.retry_count = 0
        self.max_retries = settings.max_retries
        self.audit_trail: List[str] = []
        self.execution_result: Dict[str, Any] = {}
        self.error_message: Optional[str] = None

        self.created_at = time.time()
        self.updated_at = time.time()

        # Coordination & Real-Time Streaming
        self.approval_event = asyncio.Event()
        self.subscribers: Set[asyncio.Queue] = set()
        self.event_history: List[Dict[str, Any]] = []
        self.task: Optional[asyncio.Task] = None

    def to_response(self) -> JobStatusResponse:
        """Converts internal record to Pydantic JobStatusResponse."""
        return JobStatusResponse(
            job_id=self.job_id,
            status=self.status,
            user_query=self.user_query,
            target_dcc=self.target_dcc,
            is_high_risk=self.is_high_risk,
            human_approved=self.human_approved,
            is_success=self.is_success,
            retry_count=self.retry_count,
            max_retries=self.max_retries,
            audit_trail=list(self.audit_trail),
            execution_result=dict(self.execution_result),
            error_message=self.error_message,
            created_at=self.created_at,
            updated_at=self.updated_at,
        )


class PipelineJobManager:
    """Singleton Manager for compiling workflows, dispatching jobs, and streaming SSE."""

    _instance: Optional[PipelineJobManager] = None

    def __init__(self) -> None:
        self._jobs: Dict[str, JobRecord] = {}
        self._checkpointer = MemorySaver()
        self._app = create_pipeline_app(
            checkpointer=self._checkpointer,
            interrupt_gate=True,
        )

    @classmethod
    def get_instance(cls) -> PipelineJobManager:
        if cls._instance is None:
            cls._instance = PipelineJobManager()
        return cls._instance

    def list_jobs(self) -> List[JobRecord]:
        """Returns all recorded jobs sorted by creation time descending."""
        return sorted(self._jobs.values(), key=lambda j: j.created_at, reverse=True)

    def get_job(self, job_id: str) -> Optional[JobRecord]:
        """Retrieves a job by its unique identifier."""
        return self._jobs.get(job_id)

    def get_active_count(self) -> int:
        """Counts jobs currently pending, running, or waiting for approval."""
        return sum(
            1
            for j in self._jobs.values()
            if j.status in (JobStatus.PENDING, JobStatus.RUNNING, JobStatus.WAITING_APPROVAL)
        )

    async def submit_job(self, req: JobSubmitRequest) -> JobRecord:
        """Initializes a new job and launches the background state machine task."""
        job_id = req.job_id or f"JOB_{uuid.uuid4().hex[:8].upper()}"
        if job_id in self._jobs:
            existing = self._jobs[job_id]
            if existing.status in (JobStatus.PENDING, JobStatus.RUNNING, JobStatus.WAITING_APPROVAL):
                return existing

        job = JobRecord(
            job_id=job_id,
            user_query=req.user_query,
            target_dcc=req.target_dcc,
            auto_approve=req.auto_approve,
        )
        self._jobs[job_id] = job

        # Launch background runner
        job.task = asyncio.create_task(self._run_job_lifecycle(job))
        return job

    async def approve_job(
        self,
        job_id: str,
        approved: bool,
        comment: Optional[str] = None,
    ) -> JobRecord:
        """Unblocks a job halted at the Human Approval Gate."""
        job = self.get_job(job_id)
        if not job:
            raise KeyError(f"Job '{job_id}' not found.")

        if job.status != JobStatus.WAITING_APPROVAL:
            raise ValueError(f"Job '{job_id}' is in status '{job.status.value}', not WAITING_APPROVAL.")

        job.human_approved = approved
        job.updated_at = time.time()
        if comment:
            note = f"[ApprovalGate] Lead TA 审批备注: {comment}"
            job.audit_trail.append(note)
            await self._broadcast(job, {"event": "audit", "node": "gate", "message": note})

        # Signal the background task to resume
        job.approval_event.set()
        return job

    async def _broadcast(self, job: JobRecord, event_data: Dict[str, Any]) -> None:
        """Broadcasts an event message to all connected SSE clients and history."""
        payload = {
            "job_id": job.job_id,
            "timestamp": time.time(),
            **event_data,
        }
        job.event_history.append(payload)
        job.updated_at = time.time()

        # Fan out to all active subscriber queues
        dead_queues = set()
        for q in job.subscribers:
            try:
                q.put_nowait(payload)
            except Exception:
                dead_queues.add(q)
        job.subscribers.difference_update(dead_queues)

    async def _process_chunk(self, job: JobRecord, chunk: Dict[str, Any]) -> None:
        """Processes an incremental node delta from LangGraph astream."""
        for node_name, delta in chunk.items():
            if not isinstance(delta, dict):
                continue

            # Update audit trail
            if "audit_trail" in delta and isinstance(delta["audit_trail"], list):
                for line in delta["audit_trail"]:
                    if line not in job.audit_trail:
                        job.audit_trail.append(line)
                        await self._broadcast(job, {
                            "event": "audit",
                            "node": node_name,
                            "message": line,
                        })

            # Check for risk / approval flag updates
            if "is_high_risk" in delta:
                job.is_high_risk = delta["is_high_risk"]
            if "retry_count" in delta:
                job.retry_count = delta["retry_count"]
            if "execution_result" in delta:
                job.execution_result = delta["execution_result"]
            if "error_message" in delta:
                job.error_message = delta["error_message"]

            # Broadcast node progress
            safe_delta = {k: v for k, v in delta.items() if k != "rag_context"}
            await self._broadcast(job, {
                "event": "node_update",
                "node": node_name,
                "delta": safe_delta,
            })

    async def _run_job_lifecycle(self, job: JobRecord) -> None:
        """Orchestrates the full LangGraph lifecycle for a pipeline job."""
        config = {"configurable": {"thread_id": job.job_id}}
        job.status = JobStatus.RUNNING
        job.updated_at = time.time()

        await self._broadcast(job, {
            "event": "job_started",
            "user_query": job.user_query,
            "target_dcc": job.target_dcc,
        })

        initial_state: AgentPipelineState = {
            "job_id": job.job_id,
            "user_query": job.user_query,
            "target_dcc": job.target_dcc,
            "rag_context": "",
            "is_high_risk": False,
            "human_approved": False,
            "ue_mcp_online": False,
            "action_plan": [],
            "current_action": "",
            "action_args": {},
            "generated_code": "",
            "execution_result": {},
            "is_success": False,
            "error_message": "",
            "retry_count": 0,
            "max_retries": settings.max_retries,
            "reflection_notes": "",
            "audit_trail": [],
        }

        try:
            # Phase 1: Stream until gate interrupt or end
            async for chunk in self._app.astream(initial_state, config, stream_mode="updates"):
                await self._process_chunk(job, chunk)

            # Check if execution paused at human approval gate
            snapshot = await self._app.aget_state(config)
            if snapshot.next and "gate" in snapshot.next[0]:
                job.is_high_risk = True
                job.status = JobStatus.WAITING_APPROVAL
                job.updated_at = time.time()

                await self._broadcast(job, {
                    "event": "waiting_approval",
                    "message": "检测到高危资产变更，任务安全挂起等待 Lead TA 授权",
                    "is_high_risk": True,
                })

                if job.auto_approve:
                    job.human_approved = True
                    job.status = JobStatus.RUNNING
                    auto_log = "[ApprovalGate] 检测到 auto_approve 标志，系统自动放行执行。"
                    job.audit_trail.append(auto_log)
                    await self._broadcast(job, {
                        "event": "audit",
                        "node": "gate",
                        "message": auto_log,
                    })
                    await self._app.aupdate_state(config, {"human_approved": True})
                    async for chunk in self._app.astream(None, config, stream_mode="updates"):
                        await self._process_chunk(job, chunk)
                else:
                    # Wait for Lead TA approval via API /approve endpoint
                    await job.approval_event.wait()
                    job.status = JobStatus.RUNNING
                    job.updated_at = time.time()

                    resume_log = (
                        "[ApprovalGate] Lead TA 审查通过，继续执行管线"
                        if job.human_approved
                        else "[ApprovalGate] Lead TA 审查拒绝，准备安全中止"
                    )
                    job.audit_trail.append(resume_log)
                    await self._broadcast(job, {
                        "event": "audit",
                        "node": "gate",
                        "message": resume_log,
                    })

                    await self._app.aupdate_state(config, {"human_approved": job.human_approved})
                    async for chunk in self._app.astream(None, config, stream_mode="updates"):
                        await self._process_chunk(job, chunk)

            # Phase 2: Finalize state snapshot
            final_snapshot = await self._app.aget_state(config)
            final_values = final_snapshot.values if final_snapshot else {}

            job.is_success = bool(final_values.get("is_success", False))
            job.execution_result = final_values.get("execution_result", {})
            job.error_message = final_values.get("error_message")
            job.retry_count = final_values.get("retry_count", 0)

            # Ensure all final audit entries are synchronized
            for entry in final_values.get("audit_trail", []):
                if entry not in job.audit_trail:
                    job.audit_trail.append(entry)

            if job.is_success:
                job.status = JobStatus.COMPLETED
            elif job.human_approved is False:
                job.status = JobStatus.ABORTED
            else:
                job.status = JobStatus.FAILED

            await self._broadcast(job, {
                "event": "job_finished",
                "status": job.status.value,
                "is_success": job.is_success,
                "retry_count": job.retry_count,
                "execution_result": job.execution_result,
                "error_message": job.error_message,
            })

        except Exception as exc:
            logger.exception("Error executing pipeline job %s: %s", job.job_id, exc)
            job.status = JobStatus.FAILED
            job.error_message = str(exc)
            err_log = f"[SystemError] 异常中断: {exc}"
            job.audit_trail.append(err_log)
            await self._broadcast(job, {
                "event": "job_failed",
                "error": str(exc),
            })
        finally:
            job.updated_at = time.time()

    async def stream_job_events(self, job_id: str) -> AsyncGenerator[Dict[str, Any], None]:
        """Yields historic events then real-time updates for SSE streaming."""
        job = self.get_job(job_id)
        if not job:
            raise KeyError(f"Job '{job_id}' not found.")

        # 1. Replay historical events to catch up
        for historic_event in list(job.event_history):
            yield historic_event

        # If already terminated, we're done
        if job.status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.ABORTED):
            return

        # 2. Subscribe to live queue
        queue: asyncio.Queue = asyncio.Queue()
        job.subscribers.add(queue)

        try:
            while True:
                try:
                    # 10-second timeout to send keepalive pings
                    event = await asyncio.wait_for(queue.get(), timeout=10.0)
                    yield event
                    if event.get("event") in ("job_finished", "job_failed"):
                        break
                except asyncio.TimeoutError:
                    # SSE Keepalive ping
                    yield {"event": "ping", "job_id": job_id, "timestamp": time.time()}
                    if job.status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.ABORTED):
                        break
        finally:
            job.subscribers.discard(queue)
