# -*- coding: utf-8 -*-
"""Command-Line Interface for DCC Pipeline AI Agent.

Provides an enterprise-grade interactive and non-interactive runner for executing
Unreal Engine 5.8 pipeline jobs with self-healing and human approval.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from typing import Optional

from dcc_agent.config import settings
from dcc_agent.graph.state import AgentPipelineState
from dcc_agent.graph.workflow import create_pipeline_app

# Ensure UTF-8 output on Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except AttributeError:
        pass


async def run_pipeline_job(
    user_prompt: str,
    auto_approve: bool = False,
    thread_id: Optional[str] = None,
) -> AgentPipelineState:
    """Executes a complete pipeline job through the compiled LangGraph workflow."""
    job_id = thread_id or f"JOB_{uuid.uuid4().hex[:8].upper()}"
    config = {"configurable": {"thread_id": job_id}}

    print("\n" + "=" * 75)
    print(f"🚀 [DCC Pipeline Agent] 启动作业: {job_id}")
    print(f"👤 需求内容: '{user_prompt}'")
    print(f"🎮 目标引擎: {settings.ue_mcp_url} | 推理算力: {settings.ollama_base_url}")
    print("=" * 75)

    app = create_pipeline_app(interrupt_gate=True)

    initial_state: AgentPipelineState = {
        "job_id": job_id,
        "user_query": user_prompt,
        "target_dcc": "Unreal Engine 5.8",
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
        "pipeline_mode": "multi_agent",
        "active_subagent": "supervisor",
        "wbs_plan": [],
        "current_wbs_index": 0,
        "subagent_results": {},
        "blueprint_dsl": "",
        "spawned_actors": [],
    }

    # Step 1: Run until interrupt or completion
    await app.ainvoke(initial_state, config)

    snapshot = await app.aget_state(config)
    # Check if halted at gate
    if snapshot.next and "gate" in snapshot.next[0]:
        print("\n" + "-" * 70)
        print("⏸️  【安全审计挂起】检测到高危资产变更，工作流已触发自动化拦截！")
        print(f"🛡️  作业ID: {job_id}")
        print(f"⚠️  风险详情: 用户指令包含高危操作，需 Lead TA 授权放行。")
        print("-" * 70)

        if auto_approve:
            print("🤖 检测到 --auto-approve 标志，自动授予执行权限...")
            approved = True
        else:
            try:
                choice = input("\n👉 请 Lead TA 审批：是否授权执行？(y/n) [默认 n]: ").strip().lower()
                approved = choice in ("y", "yes")
            except (EOFError, KeyboardInterrupt):
                approved = False

        if approved:
            print("✅ 审批已通过，正在恢复工作流执行...")
            await app.aupdate_state(config, {"human_approved": True})
            final_state = await app.ainvoke(None, config)
        else:
            print("❌ 审批已拒绝，正在安全中止作业...")
            await app.aupdate_state(config, {"human_approved": False})
            final_state = await app.ainvoke(None, config)
    else:
        final_state = snapshot.values

    # Print Final Summary
    print("\n" + "=" * 75)
    print("🏁 【作业执行全生命周期审计追踪 (Audit Trail)】:")
    for idx, entry in enumerate(final_state.get("audit_trail", []), 1):
        print(f"  {idx}. {entry}")

    print("\n🎯 最终状态: " + ("【执行成功】" if final_state.get("is_success") else "【失败 / 已中止】"))
    print(f"🔁 经历自愈轮次: {final_state.get('retry_count', 0)}")
    if final_state.get("execution_result"):
        print(f"📦 引擎返回数据: {final_state['execution_result']}")
    print("=" * 75 + "\n")

    return final_state


def main() -> None:
    parser = argparse.ArgumentParser(description="DCC Pipeline Agent - Enterprise AI Copilot & Microservice")
    parser.add_argument("--prompt", "-p", type=str, help="Natural language pipeline task prompt")
    parser.add_argument("--auto-approve", "-y", action="store_true", help="Auto-approve high-risk gates")
    parser.add_argument("--thread-id", "-t", type=str, help="Custom job thread id for session persistence")
    parser.add_argument("--server", "-s", action="store_true", help="Start FastAPI REST & SSE microservice")
    parser.add_argument("--host", type=str, default=None, help="Server host binding override")
    parser.add_argument("--port", type=int, default=None, help="Server port override")

    args = parser.parse_args()

    if args.server:
        import uvicorn
        host = args.host or settings.api_host
        port = args.port or settings.api_port
        print("\n" + "=" * 75)
        print(f"🚀 [DCC Pipeline Agent] 启动 FastAPI 微服务网关: http://{host}:{port}")
        print(f"📖 OpenAPI 交互文档 (Swagger UI): http://{host}:{port}/docs")
        print(f"🩺 节点探活状态端点: http://{host}:{port}/api/v1/health")
        print("=" * 75 + "\n")
        uvicorn.run("dcc_agent.api.app:app", host=host, port=port, reload=False, log_level="info")
        return

    prompt = args.prompt
    if not prompt:
        print("\n" + "=" * 70)
        print("  DCC PIPELINE AI AGENT (UNREAL ENGINE 5.8 & GAME TA)")
        print("=" * 70)
        prompt = input("请输入 TA 自动化需求 (直接回车使用默认测试用例): ").strip()
        if not prompt:
            prompt = "清理未合规命名的网格资产，并核对当前工具集列表"

    asyncio.run(run_pipeline_job(prompt, auto_approve=args.auto_approve, thread_id=args.thread_id))


if __name__ == "__main__":
    main()
