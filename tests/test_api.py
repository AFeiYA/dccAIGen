# -*- coding: utf-8 -*-
"""Comprehensive End-to-End Integration Test for DCC Pipeline FastAPI Service.

Tests:
1. FastAPI Service Metadata (GET /)
2. Multi-DCC & AI Health Probe (GET /api/v1/health)
3. Async Job Submission (POST /api/v1/jobs)
4. High-Risk Gate Interception & Approval (POST /api/v1/jobs/{job_id}/approve)
5. SSE Real-Time Event Streaming (GET /api/v1/jobs/{job_id}/stream)
6. Job Status & Audit Trail Query (GET /api/v1/jobs/{job_id})
"""

from __future__ import annotations

import asyncio
import json
import sys
import time

# Ensure UTF-8 output on Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

from pathlib import Path
import httpx
from httpx import ASGITransport

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dcc_agent.api.app import app
from dcc_agent.api.schemas import JobStatus


async def run_integration_tests():
    print("\n" + "=" * 75)
    print("🧪 [DCC FastAPI Integration Test] 开始端到端服务接口集成测试")
    print("=" * 75)

    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8080") as client:

        # ----------------------------------------------------------------------
        # Test 1: Root Metadata
        # ----------------------------------------------------------------------
        print("\n▶️  [Test 1/5] 测试根路径元数据 GET / ...")
        resp = await client.get("/")
        assert resp.status_code == 200, f"Root endpoint returned {resp.status_code}"
        data = resp.json()
        print(f"  ✅ 根路径元数据正常: {data.get('service')} (v{data.get('version')})")
        print(f"  🔗 文档地址: {data.get('docs_url')}")

        # ----------------------------------------------------------------------
        # Test 2: Health Probing
        # ----------------------------------------------------------------------
        print("\n▶️  [Test 2/5] 测试多 DCC 与 AI 集群探活 GET /api/v1/health ...")
        resp = await client.get("/api/v1/health")
        assert resp.status_code == 200, f"Health endpoint returned {resp.status_code}"
        health = resp.json()
        print(f"  ✅ 集群状态: {health.get('status')}")
        print(f"  🎮 UE 5.8 Native MCP 状态: {'在线 ✅' if health.get('ue_mcp') else '离线 ⚠️'} ({health.get('ue_mcp_url')})")
        print(f"  🧠 Mac M5 Ollama 状态: {'在线 ✅' if health.get('ollama') else '离线 ⚠️'} ({health.get('ollama_url')})")
        print(f"  ⚡ 活跃作业数: {health.get('active_jobs')}")

        # ----------------------------------------------------------------------
        # Test 3: High-Risk Job Submission & Gate Interception
        # ----------------------------------------------------------------------
        print("\n▶️  [Test 3/5] 测试高危资产操作提交与安全门禁拦截 POST /api/v1/jobs ...")
        submit_payload = {
            "user_query": "批量重命名并清理场景中未引用的无用资产",
            "target_dcc": "Unreal Engine 5.8",
            "auto_approve": False,
        }
        resp = await client.post("/api/v1/jobs", json=submit_payload)
        assert resp.status_code == 202, f"Submit failed: {resp.status_code} {resp.text}"
        job_info = resp.json()
        job_id = job_info["job_id"]
        print(f"  ✅ 任务提交成功，作业 ID: {job_id}")

        # Wait for gate interception
        print("  ⏳ 等待 LangGraph 规划并触发安全门禁挂起...")
        waited = 0
        gate_reached = False
        while waited < 30:
            await asyncio.sleep(1.0)
            waited += 1
            status_resp = await client.get(f"/api/v1/jobs/{job_id}")
            current = status_resp.json()
            if current["status"] == JobStatus.WAITING_APPROVAL.value:
                gate_reached = True
                print(f"  🛡️  [Gate Intercepted] 任务已如期挂起！状态: {current['status']}")
                print(f"  ⚠️  高危标记: {current['is_high_risk']}")
                for log in current.get("audit_trail", []):
                    print(f"      - {log}")
                break

        assert gate_reached, f"Job did not reach WAITING_APPROVAL within timeout! State: {current}"

        # ----------------------------------------------------------------------
        # Test 4: Lead TA Approval & Workflow Resumption
        # ----------------------------------------------------------------------
        print(f"\n▶️  [Test 4/5] 测试 Lead TA 人机协同审批 POST /api/v1/jobs/{job_id}/approve ...")
        approval_payload = {
            "approved": True,
            "comment": "Lead TA 审核通过：允许在测试沙盒中执行安全批量重命名。",
        }
        resp = await client.post(f"/api/v1/jobs/{job_id}/approve", json=approval_payload)
        assert resp.status_code == 200, f"Approval failed: {resp.status_code} {resp.text}"
        appr_res = resp.json()
        print(f"  ✅ 审批接口响应: {appr_res.get('message')}")

        # Wait for workflow completion
        print("  ⏳ 等待恢复执行与自愈闭环完成...")
        waited = 0
        finished = False
        while waited < 45:
            await asyncio.sleep(1.0)
            waited += 1
            status_resp = await client.get(f"/api/v1/jobs/{job_id}")
            current = status_resp.json()
            if current["status"] in (JobStatus.COMPLETED.value, JobStatus.FAILED.value, JobStatus.ABORTED.value):
                finished = True
                print(f"  🏁 任务终态到达: {current['status']}")
                print(f"  🎯 执行成功: {current['is_success']}")
                print(f"  🔁 经历自愈轮次: {current['retry_count']}")
                print("  📜 完整审计追踪 (Audit Trail):")
                for idx, log in enumerate(current.get("audit_trail", []), 1):
                    print(f"      {idx}. {log}")
                if current.get("execution_result"):
                    print(f"  📦 引擎交付数据: {current['execution_result']}")
                break

        assert finished, f"Job did not reach terminal status in time: {current}"

        # ----------------------------------------------------------------------
        # Test 5: Job List Query
        # ----------------------------------------------------------------------
        print("\n▶️  [Test 5/6] 测试全量作业列表查询 GET /api/v1/jobs ...")
        resp = await client.get("/api/v1/jobs")
        assert resp.status_code == 200
        jobs_data = resp.json()
        print(f"  ✅ 成功获取作业列表，已注册任务总数: {jobs_data['total']}")

        # ----------------------------------------------------------------------
        # Test 6: Server-Sent Events (SSE) Stream Verification
        # ----------------------------------------------------------------------
        print(f"\n▶️  [Test 6/6] 测试 SSE 实时事件流 GET /api/v1/jobs/{job_id}/stream ...")
        sse_events = []
        async with client.stream("GET", f"/api/v1/jobs/{job_id}/stream") as stream_resp:
            assert stream_resp.status_code == 200
            assert "text/event-stream" in stream_resp.headers["content-type"]
            async for line in stream_resp.aiter_lines():
                if line.startswith("data:"):
                    raw_data = line[5:].strip()
                    if raw_data:
                        event_payload = json.loads(raw_data)
                        sse_events.append(event_payload)

        print(f"  ✅ 成功接收并解析 SSE 事件流包数量: {len(sse_events)}")
        for evt in sse_events[:5]:
            print(f"      - [SSE] Event: {evt.get('event')}, Message: {evt.get('message') or evt.get('node')}")
        assert len(sse_events) > 0, "No SSE events received!"

    print("\n" + "=" * 75)
    print("🎉 [DCC FastAPI Integration Test] 所有 5 项核心微服务集成测试全部通过！")
    print("=" * 75 + "\n")


if __name__ == "__main__":
    asyncio.run(run_integration_tests())
