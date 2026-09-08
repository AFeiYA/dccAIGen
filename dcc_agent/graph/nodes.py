# -*- coding: utf-8 -*-
"""Asynchronous Node Functions for DCC Pipeline LangGraph Workflow.

All nodes are strictly async, ensuring zero-block I/O and seamless integration
with in-editor Slate widgets, webhooks, or CLI applications.
"""

from __future__ import annotations

import io
import json
import logging
import re
import sys
import traceback
from typing import Any, Dict

from openai import AsyncOpenAI

from dcc_agent.config import settings
from dcc_agent.core.mcp_client import UENativeMCPClient
from dcc_agent.core.retriever import DCCHybridRetriever
from dcc_agent.graph.state import AgentPipelineState

logger = logging.getLogger("PipelineNodes")

# Lazy-loaded singletons for efficiency
_retriever: DCCHybridRetriever | None = None
_llm_client: AsyncOpenAI | None = None


def get_retriever() -> DCCHybridRetriever:
    global _retriever
    if _retriever is None:
        _retriever = DCCHybridRetriever()
    return _retriever


def get_llm_client() -> AsyncOpenAI:
    global _llm_client
    if _llm_client is None:
        _llm_client = AsyncOpenAI(
            base_url=settings.ollama_base_url,
            api_key=settings.ollama_api_key,
        )
    return _llm_client


def extract_code_block(text: str) -> str:
    """Extracts python code from markdown code fences if present."""
    match = re.search(r"```python\s*(.*?)\s*```", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    match_gen = re.search(r"```\s*(.*?)\s*```", text, re.DOTALL)
    if match_gen:
        return match_gen.group(1).strip()
    return text.strip()


# ==============================================================================
# Async Nodes
# ==============================================================================
async def plan_and_audit_node(state: AgentPipelineState) -> Dict[str, Any]:
    """[Node 1: Plan & Audit] RAG SOP retrieval, risk assessment, and engine health check."""
    query = state["user_query"]
    logger.info("Evaluating task and RAG context: '%s'", query)

    # 1. Hybrid RAG retrieval
    retriever = get_retriever()
    rag_context = retriever.format_for_llm_context(query, top_k=2)

    # 2. Risk check against centralized settings
    is_risk = any(kw in query.lower() for kw in settings.high_risk_keywords)

    # 3. Async UE 5.8 probe
    mcp_client = UENativeMCPClient()
    is_live = await mcp_client.is_online()
    await mcp_client.close()

    log_msg = f"[Plan] SOP 检索完毕，高危标记: {is_risk}，UE 5.8 在线: {is_live}"
    return {
        "rag_context": rag_context,
        "is_high_risk": is_risk,
        "ue_mcp_online": is_live,
        "audit_trail": [log_msg],
    }


async def human_approval_gate_node(state: AgentPipelineState) -> Dict[str, Any]:
    """[Node 2: Human Approval Gate] Halts execution for high-risk operations."""
    if state["human_approved"]:
        log_msg = "[ApprovalGate] Lead TA 人工审查通过，授权执行高危操作"
    else:
        log_msg = "[ApprovalGate] 检测到高危资产变更，任务安全挂起等待人工授权"
    return {"audit_trail": [log_msg]}


async def action_planner_node(state: AgentPipelineState) -> Dict[str, Any]:
    """[Node 3: Action Planner] Decides or repairs tool/code execution using Mac M5 LLM."""
    retry = state["retry_count"]
    llm = get_llm_client()

    system_prompt = (
        "你是一名 3A 游戏工作室的资深技术美术 (Lead TA) 和管线专家。\n"
        "严格遵守以下管线 SOP 规范：\n"
        f"{state['rag_context']}\n"
    )

    if retry == 0:
        user_prompt = (
            f"TA 需求: {state['user_query']}\n"
            "请决定要执行的动作。可选动作：\n"
            "- list_toolsets: 查询引擎注册工具包\n"
            "- audit_actors_naming: 审查关卡 Actor 命名规范\n"
            "- spawn_pipeline_actor: 生成规范化资产\n\n"
            "请严格输出一行 JSON 格式，例如：\n"
            '{"action": "list_toolsets", "args": {}}'
        )
    else:
        user_prompt = (
            f"TA 需求: {state['user_query']}\n"
            "⚠️ 上一轮执行出现异常失败：\n"
            f"【报错信息】: {state['error_message']}\n"
            f"【反思补丁】: {state['reflection_notes']}\n\n"
            "请根据反思建议修正工具与参数，严格输出一行 JSON，例如：\n"
            '{"action": "list_toolsets", "args": {}}'
        )

    response = await llm.chat.completions.create(
        model=settings.default_model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.1,
        max_tokens=600,
    )

    raw_text = response.choices[0].message.content or ""
    # Safe JSON extraction
    match = re.search(r"\{.*?\}", raw_text, re.DOTALL)
    if match:
        try:
            parsed = json.loads(match.group(0))
            action_name = parsed.get("action", "list_toolsets")
            action_args = parsed.get("args", {})
        except json.JSONDecodeError:
            action_name = "list_toolsets"
            action_args = {}
    else:
        action_name = "list_toolsets"
        action_args = {}

    log_msg = f"[Planner] 决策执行动作: {action_name}, 参数: {action_args}"
    return {
        "current_action": action_name,
        "action_args": action_args,
        "audit_trail": [log_msg],
    }


async def execute_node(state: AgentPipelineState) -> Dict[str, Any]:
    """[Node 4: Execute on Engine/Sandbox] Dispatches tool call to UE 5.8 Game Thread."""
    action = state["current_action"]
    args = state["action_args"]
    is_live = state["ue_mcp_online"]
    retry = state["retry_count"]

    # In round 0, simulate tool exception to showcase self-healing if needed
    if retry == 0 and "fail_test" in state["user_query"].lower():
        sim_err = f"EngineToolCallError: Tool '{action}' failed due to missing parameters."
        return {
            "is_success": False,
            "execution_result": {},
            "error_message": sim_err,
            "audit_trail": [f"[Execute] 第 {retry} 轮调度抛出异常: {sim_err}"],
        }

    if is_live:
        client = UENativeMCPClient()
        try:
            async with client:
                res = await client.call_meta_tool(action, args)
                log_msg = f"[Execute] UE 5.8 原生调度 '{action}' 成功，返回数据"
                return {
                    "is_success": True,
                    "execution_result": res if isinstance(res, dict) else {"response": res},
                    "error_message": "",
                    "audit_trail": [log_msg],
                }
        except Exception as exc:
            err_str = str(exc)
            return {
                "is_success": False,
                "execution_result": {},
                "error_message": err_str,
                "audit_trail": [f"[Execute] UE 5.8 调度异常: {err_str}"],
            }
    else:
        # Sandbox execution
        mock_result = {"status": "ok", "action": action, "mock": True}
        return {
            "is_success": True,
            "execution_result": mock_result,
            "error_message": "",
            "audit_trail": [f"[Execute] 沙盒仿真执行 '{action}' 成功"],
        }


async def reflect_and_patch_node(state: AgentPipelineState) -> Dict[str, Any]:
    """[Node 5: Reflect & Patch] LLM diagnoses error traceback and formulates a repair."""
    err = state["error_message"]
    new_retry = state["retry_count"] + 1
    llm = get_llm_client()

    diag_prompt = (
        "作为 UE 5.8 Lead TA，上一轮 MCP 工具调度失败：\n"
        f"报错信息: {err}\n"
        "请诊断原因，并建议：若具体工具缺失，降级为元工具 'list_toolsets' 查询已注册能力。\n"
        "请用极其简炼的 1 句话给出修复方案。"
    )

    resp = await llm.chat.completions.create(
        model=settings.default_model,
        messages=[{"role": "user", "content": diag_prompt}],
        temperature=0.1,
        max_tokens=300,
    )
    patch_note = resp.choices[0].message.content or "切换为元工具 list_toolsets 获取可用能力。"
    log_msg = f"[Reflect] 根因诊断完成，生成补丁并进入第 {new_retry} 次重试"
    return {
        "retry_count": new_retry,
        "reflection_notes": patch_note.strip(),
        "audit_trail": [log_msg],
    }


async def delivery_node(state: AgentPipelineState) -> Dict[str, Any]:
    """[Node 6: Delivery] Summarizes success and outputs completion audit log."""
    return {"audit_trail": ["[Delivery] 作业闭环圆满达成，生成交付报告"]}


async def abort_node(state: AgentPipelineState) -> Dict[str, Any]:
    """[Node 7: Abort] Safe exit when aborted or retries exhausted."""
    return {"audit_trail": ["[Abort] 作业安全中止，工程状态已保护"]}
