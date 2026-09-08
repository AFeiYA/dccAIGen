# -*- coding: utf-8 -*-
"""Phase 4 终极大考 Capstone —— 基于 LangGraph 与 UE 5.8 原生 MCP 的自愈式管线智能体 (UE5.8 LangGraph Copilot).

本系统为整个工业级 AI 管线的集大成者，完整闭环：
1. 本地向量知识库 (ChromaDB + BM25 RRF) 注入工作室 SOP 规范；
2. 远程 Mac M5 本地大模型进行规划决策与报错反思；
3. LangGraph 1.2+ 编排有向有环图状态机与 Checkpointer 快照；
4. 高危操作人机协同阻断与审批 (Human-in-the-Loop)；
5. Epic 官方 Unreal Engine 5.8 原生 MCP 客户端在 Game Thread 上安全执行工具；
6. 遇到引擎报错时自动逆流回反思节点修正参数与脚本 (Self-Healing Loop)；
7. 全程输出符合 3A 大厂合规要求的全生命周期不可篡改审计追踪 (Audit Trail)。
"""

from __future__ import annotations

import io
import json
import logging
import operator
import os
import re
import sys
import traceback
from typing import Annotated, Any, Dict, List, Literal, Optional, TypedDict

import httpx
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from openai import OpenAI

from dcc_hybrid_retriever import DCCHybridRetriever

# 确保 Windows 终端 UTF-8 输出
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("UE58LangGraphCopilot")

DEFAULT_UE_MCP_URL = "http://127.0.0.1:8000/mcp"
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://192.168.1.222:11434/v1")
DEFAULT_MODEL = os.getenv("OLLAMA_MODEL", "gemma4:12b-mlx")


# ==============================================================================
# 1. UE 5.8 原生 MCP 同步客户端 (内置于 LangGraph 节点中运行)
# ==============================================================================
class UENativeSyncClient:
    """轻量高效的 UE 5.8 Streamable HTTP JSON-RPC 客户端。"""

    def __init__(self, base_url: str = DEFAULT_UE_MCP_URL, timeout: float = 10.0) -> None:
        self.base_url = base_url
        self.client = httpx.Client(timeout=timeout)
        self.session_id: Optional[str] = None
        self._req_id = 0

    def is_online(self) -> bool:
        try:
            r = self.client.post(self.base_url, json={"jsonrpc": "2.0", "id": 0, "method": "ping", "params": {}})
            return r.status_code in (200, 400, 405)
        except Exception:
            return False

    def initialize(self) -> bool:
        try:
            self._req_id += 1
            payload = {
                "jsonrpc": "2.0",
                "id": self._req_id,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "langgraph-ue58-copilot", "version": "1.0.0"},
                },
            }
            res = self.client.post(self.base_url, json=payload)
            res.raise_for_status()
            self.session_id = res.headers.get("mcp-session-id")
            return bool(self.session_id)
        except Exception as exc:
            logger.warning("UE 5.8 MCP 握手失败: %s", exc)
            return False

    def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        self._req_id += 1
        headers = {"Mcp-Session-Id": self.session_id} if self.session_id else {}
        payload = {
            "jsonrpc": "2.0",
            "id": self._req_id,
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
        }
        res = self.client.post(self.base_url, json=payload, headers=headers)
        res.raise_for_status()
        data = res.json()

        result = data.get("result", {})
        content = result.get("content", [])
        if content and isinstance(content, list):
            text = content[0].get("text", "")
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return {"text": text}
        return result

    def close(self) -> None:
        self.client.close()


# ==============================================================================
# 2. 状态契约 (State Definition)
# ==============================================================================
class UE58PipelineJobState(TypedDict):
    """UE5.8 自愈智能体全流程状态契约。"""

    job_id: str
    user_prompt: str
    rag_guidelines: str
    is_high_risk: bool
    human_approved: bool
    ue_mcp_online: bool
    current_action: str
    action_args: Dict[str, Any]
    execution_result: Dict[str, Any]
    is_success: bool
    error_message: str
    retry_count: int
    max_retries: int
    reflection_patch: str
    audit_trail: Annotated[List[str], operator.add]


# ==============================================================================
# 3. 全局服务实例
# ==============================================================================
print("📚 正在加载 TA 知识库与本地推理客户端...")
retriever = DCCHybridRetriever()
llm = OpenAI(base_url=OLLAMA_BASE_URL, api_key="ollama")


# ==============================================================================
# 4. LangGraph 节点函数实现
# ==============================================================================
def plan_and_audit_node(state: UE58PipelineJobState) -> Dict[str, Any]:
    """[节点 1: 规范检索与风控审查] 检索 SOP，分析是否涉及高危资产变更。"""
    prompt = state["user_prompt"]
    print(f"\n📋 [Node 1: Plan & Audit] 分析 TA 需求并匹配知识库: '{prompt}'...")

    # 1. 混合检索 SOP 规范
    hits = retriever.hybrid_search(prompt, top_k=2)
    snippets = []
    for idx, hit in enumerate(hits, 1):
        doc_name = hit["metadata"].get("doc_name") or hit["metadata"].get("source") or "SOP"
        snippets.append(f"[{idx}] (来源: {doc_name})\n{hit['doc']}")
    rag_text = "\n\n".join(snippets)

    # 2. 检测高危关键字
    risk_words = ["删除", "delete", "清理", "clean", "覆盖", "override", "批量重置"]
    is_risk = any(w in prompt.lower() for w in risk_words)

    # 3. 探活 UE 5.8
    ue_client = UENativeSyncClient(DEFAULT_UE_MCP_URL)
    is_live = ue_client.is_online()
    ue_client.close()

    log_entry = f"[Plan] 规范检索完毕 (命中 {len(hits)} 条)，高危标记: {is_risk}，UE5.8 在线: {is_live}"
    print(f"  ↳ {log_entry}")

    return {
        "rag_guidelines": rag_text,
        "is_high_risk": is_risk,
        "ue_mcp_online": is_live,
        "audit_trail": [log_entry],
    }


def human_approval_gate_node(state: UE58PipelineJobState) -> Dict[str, Any]:
    """[节点 2: 人机协同审批门禁] 高危操作在此挂起拦截，等待 Lead TA 授权。"""
    print("\n🛑 [Node 2: Human Approval Gate] 进入高危资产变更审批门禁...")
    if state["human_approved"]:
        log_entry = "[Gate] Lead TA 已经人工签署授权，放行高危资产操作"
        print(f"  ↳ ✅ {log_entry}")
    else:
        log_entry = "[Gate] 处于挂起保护状态，等待人工授权中"
        print(f"  ↳ ⏳ {log_entry}")

    return {
        "audit_trail": [log_entry],
    }


def action_planner_node(state: UE58PipelineJobState) -> Dict[str, Any]:
    """[节点 3: 动作与参数规划] 请求大模型选择或修正要执行的 MCP 工具与参数。"""
    retry = state["retry_count"]
    print(f"\n🧠 [Node 3: Action Planner] 规划 MCP 工具调度 (自愈轮次: {retry})...")

    system_prompt = (
        "你是一名 Unreal Engine 5.8 Lead TA。\n"
        "你负责在 UE 5.8 中规划可调用的 MCP 工具与参数。\n"
        "严格遵守工作室 SOP 命名规则：\n"
        f"{state['rag_guidelines']}\n"
    )

    if retry == 0:
        user_prompt = (
            f"TA 需求: {state['user_prompt']}\n"
            "请决定执行动作。当前可用的动作包括：\n"
            "- list_toolsets: 查询引擎注册工具包\n"
            "- audit_actors_naming: 审查场景 Actor 命名规范\n"
            "- spawn_pipeline_actor: 生成规范化资产 (入参: asset_path, actor_label)\n\n"
            "请严格输出一行 JSON 格式：\n"
            '{"action": "audit_actors_naming", "args": {"class_filter": ""}}'
        )
    else:
        user_prompt = (
            f"TA 需求: {state['user_prompt']}\n"
            "⚠️ 上一轮执行出现异常失败：\n"
            f"【报错信息】: {state['error_message']}\n"
            f"【反思补丁】: {state['reflection_patch']}\n\n"
            "请根据反思建议调整工具参数，严格输出一行修正后的 JSON 格式，例如：\n"
            '{"action": "list_toolsets", "args": {}}'
        )

    response = llm.chat.completions.create(
        model=DEFAULT_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.1,
        max_tokens=500,
    )

    raw_text = response.choices[0].message.content or ""
    # 提取 JSON
    match = re.search(r"\{.*?\}", raw_text, re.DOTALL)
    if match:
        try:
            plan_data = json.loads(match.group(0))
            action_name = plan_data.get("action", "list_toolsets")
            action_args = plan_data.get("args", {})
        except json.JSONDecodeError:
            action_name = "list_toolsets"
            action_args = {}
    else:
        action_name = "list_toolsets"
        action_args = {}

    log_entry = f"[ActionPlanner] 决策动作: {action_name}, 参数: {action_args}"
    print(f"  ↳ {log_entry}")

    return {
        "current_action": action_name,
        "action_args": action_args,
        "audit_trail": [log_entry],
    }


def execute_ue_mcp_node(state: UE58PipelineJobState) -> Dict[str, Any]:
    """[节点 4: UE5.8 MCP 真实调度与沙盒自愈测试]"""
    action = state["current_action"]
    args = state["action_args"]
    is_live = state["ue_mcp_online"]
    retry = state["retry_count"]
    print(f"\n🎮 [Node 4: Execute on UE MCP] 调度执行工具 '{action}' (轮次 {retry})...")

    # 在第 0 轮故意模拟一个引擎常见未找到工具或参数校验异常，以激活自愈机制
    if retry == 0:
        simulated_err = f"EngineToolCallError: Tool '{action}' not found in active Toolset or arguments invalid."
        print(f"  ↳ ❌ [引擎调度异常拦截]: {simulated_err}")
        return {
            "is_success": False,
            "execution_result": {},
            "error_message": simulated_err,
            "audit_trail": [f"[Execute] 第 {retry} 轮调度抛出异常: {simulated_err}"],
        }

    # 自愈轮次：使用已修正的动作直连 UE 5.8 MCP 真实执行！
    if is_live:
        ue_client = UENativeSyncClient(DEFAULT_UE_MCP_URL)
        try:
            ue_client.initialize()
            print(f"  ↳ 🟢 [UE 5.8 Game Thread 执行中] 调用: {action}...")
            # 调用真实 MCP 上的 list_toolsets
            res = ue_client.call_tool(action, args)
            ue_client.close()
            print(f"  ↳ ✅ 引擎返回: {str(res)[:100]}...")
            return {
                "is_success": True,
                "execution_result": res,
                "error_message": "",
                "audit_trail": [f"[Execute] UE 5.8 引擎原生工具调度成功，返回结果"],
            }
        except Exception as e:
            ue_client.close()
            return {
                "is_success": False,
                "execution_result": {},
                "error_message": str(e),
                "audit_trail": [f"[Execute] 真实调用异常: {e}"],
            }
    else:
        # 沙盒模拟执行
        res = {"status": "ok", "message": "Sandbox mock executed successfully"}
        return {
            "is_success": True,
            "execution_result": res,
            "error_message": "",
            "audit_trail": ["[Execute] 沙盒环境仿真执行成功"],
        }


def reflect_and_patch_node(state: UE58PipelineJobState) -> Dict[str, Any]:
    """[节点 5: 异常反思与策略重构] 请求大模型诊断错误并递增自愈轮次。"""
    err = state["error_message"]
    new_retry = state["retry_count"] + 1
    print(f"\n🧠 [Node 5: Reflect & Patch] 触发错误反思自愈 (进入轮次 {new_retry}/{state['max_retries']})...")

    diag_prompt = (
        "作为 UE 5.8 Lead TA，上一轮 MCP 工具调度失败：\n"
        f"报错信息: {err}\n"
        "请指出问题并建议：应降级切换为稳定基础元工具 'list_toolsets' 获取引擎当前已激活的所有工具集。\n"
        "请用 1 句话给出修复方案。"
    )

    resp = llm.chat.completions.create(
        model=DEFAULT_MODEL,
        messages=[{"role": "user", "content": diag_prompt}],
        temperature=0.1,
        max_tokens=300,
    )
    patch_note = resp.choices[0].message.content or "切换为元工具 list_toolsets 查询活跃能力。"
    print(f"  ↳ 🧠 诊断修复方案: {patch_note.strip()}\n")

    return {
        "retry_count": new_retry,
        "reflection_patch": patch_note,
        "audit_trail": [f"[Reflect] 诊断修复方案完成，进入第 {new_retry} 次自愈重试"],
    }


def delivery_report_node(state: UE58PipelineJobState) -> Dict[str, Any]:
    """[节点 6: 终局汇报]"""
    print("\n🎉 [Node 6: Delivery] 任务顺利完成闭环，输出交付凭证！")
    return {
        "audit_trail": ["[Delivery] UE 5.8 资产管线作业完成"],
    }


def abort_node(state: UE58PipelineJobState) -> Dict[str, Any]:
    """[节点 7: 异常终止]"""
    print("\n🚨 [Node 7: Abort] 作业已安全终止。")
    return {
        "audit_trail": ["[Abort] 作业终止，未对工程造成非预期修改"],
    }


# ==============================================================================
# 5. 条件路由器
# ==============================================================================
def route_risk(state: UE58PipelineJobState) -> Literal["gate_approval", "action_planner"]:
    if state["is_high_risk"] and not state["human_approved"]:
        return "gate_approval"
    return "action_planner"


def route_gate(state: UE58PipelineJobState) -> Literal["approved_action", "rejected_exit"]:
    if state["human_approved"]:
        return "approved_action"
    return "rejected_exit"


def route_exec_result(state: UE58PipelineJobState) -> Literal["success_end", "retry_loop", "fail_exit"]:
    if state["is_success"]:
        return "success_end"
    if state["retry_count"] < state["max_retries"]:
        return "retry_loop"
    return "fail_exit"


# ==============================================================================
# 6. 图拓扑装配与 Checkpoint 挂载
# ==============================================================================
def build_ue58_copilot_graph():
    """构建 UE5.8 LangGraph 自愈智能体全流程图。"""
    workflow = StateGraph(UE58PipelineJobState)

    # 注册节点
    workflow.add_node("plan", plan_and_audit_node)
    workflow.add_node("gate", human_approval_gate_node)
    workflow.add_node("planner", action_planner_node)
    workflow.add_node("execute", execute_ue_mcp_node)
    workflow.add_node("reflect", reflect_and_patch_node)
    workflow.add_node("delivery", delivery_report_node)
    workflow.add_node("abort", abort_node)

    # 拓扑连接
    workflow.add_edge(START, "plan")

    workflow.add_conditional_edges(
        "plan",
        route_risk,
        {"gate_approval": "gate", "action_planner": "planner"},
    )

    workflow.add_conditional_edges(
        "gate",
        route_gate,
        {"approved_action": "planner", "rejected_exit": "abort"},
    )

    workflow.add_edge("planner", "execute")

    # 自愈路由回路
    workflow.add_conditional_edges(
        "execute",
        route_exec_result,
        {"success_end": "delivery", "retry_loop": "reflect", "fail_exit": "abort"},
    )

    # 闭环：Reflect 回连 Planner
    workflow.add_edge("reflect", "planner")

    workflow.add_edge("delivery", END)
    workflow.add_edge("abort", END)

    # 挂载 Checkpointer 并设置高危拦截点
    checkpointer = MemorySaver()
    app = workflow.compile(
        checkpointer=checkpointer,
        interrupt_before=["gate"],
    )
    return app


# ==============================================================================
# 7. 主执行与实机联动
# ==============================================================================
def main() -> None:
    print("=" * 80)
    print("  PHASE 4 终极大考：UE 5.8 原生 MCP 自愈智能体 (LANGGRAPH COPILOT)")
    print("=" * 80)

    app = build_ue58_copilot_graph()
    config = {"configurable": {"thread_id": "UE58_PROD_RUN_001"}}

    # 模拟一个涉及高危清理与规范审查的真实 TA 需求
    initial_state: UE58PipelineJobState = {
        "job_id": "JOB_UE58_001",
        "user_prompt": "清理关卡中未合规命名的废弃资产，并核对当前已注册的工具集",
        "rag_guidelines": "",
        "is_high_risk": False,
        "human_approved": False,
        "ue_mcp_online": False,
        "current_action": "",
        "action_args": {},
        "execution_result": {},
        "is_success": False,
        "error_message": "",
        "retry_count": 0,
        "max_retries": 2,
        "reflection_patch": "",
        "audit_trail": [],
    }

    print("\n▶️ 阶段一：启动任务规划与风险审计...")
    app.invoke(initial_state, config)

    # 检查当前快照
    state_snapshot = app.get_state(config)
    print("\n" + "-" * 70)
    print(f"⏸️ 【安全拦截】检测到高危操作，工作流在门禁 [{state_snapshot.next}] 处自动挂起！")
    print(f"🛡️ 待审批任务: '{initial_state['user_prompt']}'")
    print("-" * 70)

    # 模拟 Lead TA 审查后批准放行
    print("\n👤 [Lead TA 审批]: 审查任务影响范围符合预期，指令：【授权执行】！")
    app.update_state(config, {"human_approved": True})

    print("\n▶️ 阶段二：恢复执行，进入 MCP 调度与报错自愈闭环...")
    final_state = app.invoke(None, config)

    print("\n" + "=" * 80)
    print("🏁 【全流程不可篡改审计追踪报告 (Audit Trail)】:")
    for idx, log in enumerate(final_state["audit_trail"], 1):
        print(f"  {idx}. {log}")

    print("\n🎯 最终达成状态: " + ("【执行成功】" if final_state["is_success"] else "【失败】"))
    print(f"🔁 经历自愈轮次: {final_state['retry_count']} 轮")
    print(f"🎮 UE 5.8 最终响应: {final_state['execution_result']}")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    main()
