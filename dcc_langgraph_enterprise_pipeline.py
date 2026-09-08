# -*- coding: utf-8 -*-
"""Module 25-26 企业级实战 —— LangGraph 状态持久化、自愈闭环与人机审批 (Checkpointing & Human-in-the-Loop).

本脚本是 Phase 4 的集大成者，融合了：
1. 真实 Mac M5 本地大模型推理 (Token 预算防御与 reasoning 提取)；
2. 自动化异常捕获与反思重写 (Self-Healing Loop)；
3. LangGraph 1.2+ 原生 Checkpointing 机制 (MemorySaver 状态快照)；
4. 游戏工业管线高危操作中断与人机审批 (Human-in-the-Loop with interrupt_before)。
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
from typing import Annotated, Any, Dict, List, Literal, TypedDict

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
logger = logging.getLogger("EnterprisePipeline")

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://192.168.1.222:11434/v1")
DEFAULT_MODEL = os.getenv("OLLAMA_MODEL", "gemma4:12b-mlx")  # 使用 12B 兼顾速度与推理深度


# ==============================================================================
# 1. 状态契约定义 (State Contract)
# ==============================================================================
class StudioPipelineJobState(TypedDict):
    """工作室资产批处理全流程状态。"""

    job_id: str
    user_query: str
    target_dcc: str
    rag_context: str
    proposed_actions: List[str]
    is_high_risk: bool           # 是否属于高危操作 (如批量重命名/删除/覆盖材质)
    human_approved: bool         # 人工 TA 是否审批放行
    generated_code: str
    is_success: bool
    execution_stdout: str
    error_traceback: str
    retry_count: int
    max_retries: int
    reflection_notes: str
    audit_trail: Annotated[List[str], operator.add]


# ==============================================================================
# 2. 全局组件
# ==============================================================================
print("📚 正在加载 TA 知识库与本地大模型客户端...")
retriever = DCCHybridRetriever()
llm_client = OpenAI(base_url=OLLAMA_BASE_URL, api_key="ollama")


def extract_python_code(text: str) -> str:
    """提取 Markdown 代码块或纯代码。"""
    match = re.search(r"```python\s*(.*?)\s*```", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    match_generic = re.search(r"```\s*(.*?)\s*```", text, re.DOTALL)
    if match_generic:
        return match_generic.group(1).strip()
    return text.strip()


def get_llm_code_response(prompt: str, system_prompt: str) -> str:
    """调用大模型并做 Token 预算与 reasoning 兼容提取。"""
    response = llm_client.chat.completions.create(
        model=DEFAULT_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
        max_tokens=2500,
    )
    msg = response.choices[0].message
    content = msg.content or ""
    # 兼容处理：若 content 为空但 reasoning 中含有代码
    if not content and hasattr(msg, "reasoning") and msg.reasoning:
        content = msg.reasoning

    return extract_python_code(content)


# ==============================================================================
# 3. 节点函数定义 (Nodes)
# ==============================================================================
def plan_and_risk_eval_node(state: StudioPipelineJobState) -> Dict[str, Any]:
    """[节点 1: 需求拆解与高危风控评估]

    识别任务中是否包含危险关键词（批量删除、覆盖主材质、全工程批量重命名）。
    """
    query = state["user_query"]
    print(f"\n📋 [Node 1: Plan & Risk Eval] 评估任务风险与规范: '{query}'...")

    # 1. RAG 知识库召回
    hits = retriever.hybrid_search(query, top_k=2)
    snippets = []
    for idx, hit in enumerate(hits, 1):
        doc_title = hit["metadata"].get("doc_name") or hit["metadata"].get("source") or "SOP"
        snippets.append(f"[{idx}] (来源: {doc_title})\n{hit['doc']}")
    rag_text = "\n\n".join(snippets)

    # 2. 高危操作判定逻辑
    high_risk_keywords = ["删除", "覆盖", "重命名全量", "delete", "override", "clean", "清空"]
    is_risk = any(k in query.lower() for k in high_risk_keywords)

    actions = [
        "1. 扫描目标资产及其依赖引用树 (Reference Viewer)",
        "2. 备份当前资产元数据至临时版本控制分支",
        "3. 执行批量资产替换/治理操作",
    ]

    log_entry = f"[Plan] 规划生成完毕，高危标记: {is_risk}，包含 {len(actions)} 项关键操作"
    print(f"  ↳ {log_entry}")

    return {
        "rag_context": rag_text,
        "proposed_actions": actions,
        "is_high_risk": is_risk,
        "audit_trail": [log_entry],
    }


def human_approval_checkpoint_node(state: StudioPipelineJobState) -> Dict[str, Any]:
    """[节点 2: 人工审批挂起节点]

    高危操作将在此处被 LangGraph 的 interrupt_before 机制暂停，等待人工 TA 确认。
    """
    print("\n🛑 [Node 2: Human Approval Checkpoint] 正在进入人工审批挂起通道...")
    if state["human_approved"]:
        log_entry = "[Approval] Lead TA 已经人工审批确认，允许执行高危资产操作"
        print(f"  ↳ ✅ {log_entry}")
    else:
        log_entry = "[Approval] 尚未获得人工审批，任务暂停等待签署"
        print(f"  ↳ ⏳ {log_entry}")

    return {
        "audit_trail": [log_entry],
    }


def code_generation_node(state: StudioPipelineJobState) -> Dict[str, Any]:
    """[节点 3: 代码生成] 请求大模型生成合规的自动化代码。"""
    retry = state["retry_count"]
    print(f"\n💻 [Node 3: Code Generation] 生成执行脚本 (自愈轮次: {retry})...")

    system_prompt = (
        "你是一名游戏工作室资深 Lead TA。\n"
        "编写安全、鲁棒且符合工作室 SOP 的 Python 脚本，用 ```python ``` 代码块输出。\n"
        f"【工作室 SOP 规范】:\n{state['rag_context']}\n"
    )

    if retry == 0:
        prompt = (
            f"需求: {state['user_query']}\n"
            "请编写一个 Python 函数 standardize_assets(asset_list: list[str]) -> dict，\n"
            "负责规范化前缀，并在末尾调用它测试 ['wood_box', 'rock_01', 10086]。"
        )
    else:
        prompt = (
            f"需求: {state['user_query']}\n"
            "⚠️ 上一轮执行崩溃报错了！\n"
            f"【报错堆栈 Traceback】:\n{state['error_traceback']}\n\n"
            f"【反思诊断】:\n{state['reflection_notes']}\n\n"
            "请务必对入参做类型校验，对非字符串或异常数据做防御性过滤，彻底修复 Bug 后输出代码。"
        )

    code = get_llm_code_response(prompt, system_prompt)
    log_entry = f"[CodeGen] 第 {retry} 轮生成代码完毕 (代码长度: {len(code)} 字符)"
    print(f"  ↳ {log_entry}")

    return {
        "generated_code": code,
        "audit_trail": [log_entry],
    }


def execute_and_sandbox_node(state: StudioPipelineJobState) -> Dict[str, Any]:
    """[节点 4: 沙盒/引擎执行] 执行代码，捕获真实 Traceback。"""
    code = state["generated_code"]
    retry = state["retry_count"]
    print(f"\n🎮 [Node 4: Execute & Sandbox] 调度执行脚本 (第 {retry} 轮)...")

    old_stdout = sys.stdout
    old_stderr = sys.stderr
    buf_out = io.StringIO()
    buf_err = io.StringIO()

    try:
        sys.stdout = buf_out
        sys.stderr = buf_err

        # 在第 0 轮故意传入包含整数的非法数据，制造真实类型崩溃以测试自愈能力
        if retry == 0:
            exec_code = code + "\n# 触发生产真实边缘异构数据测试\nstandardize_assets(['box', 99999])\n"
        else:
            exec_code = code

        exec_globals = {"__name__": "__main__"}
        exec(exec_code, exec_globals)

        out = buf_out.getvalue()
        print(f"  ↳ ✅ 执行成功！输出: {out.strip()[:100]}...")
        return {
            "is_success": True,
            "execution_stdout": out,
            "error_traceback": "",
            "audit_trail": [f"[Execute] 第 {retry} 轮执行通过，业务逻辑正常闭环"],
        }

    except Exception as exc:
        tb = traceback.format_exc()
        print(f"  ↳ ❌ 捕获到运行时异常: {type(exc).__name__}: {exc}")
        return {
            "is_success": False,
            "execution_stdout": buf_out.getvalue(),
            "error_traceback": tb,
            "audit_trail": [f"[Execute] 第 {retry} 轮抛出异常: {type(exc).__name__}"],
        }
    finally:
        sys.stdout = old_stdout
        sys.stderr = old_stderr


def reflect_and_repair_node(state: StudioPipelineJobState) -> Dict[str, Any]:
    """[节点 5: 报错反思与修复方案] 分析 Traceback，提出具体补丁策略。"""
    tb = state["error_traceback"]
    new_retry = state["retry_count"] + 1
    print(f"\n🧠 [Node 5: Reflect & Repair] 启动反思自愈机制 (第 {new_retry}/{state['max_retries']} 轮)...")

    diag_prompt = (
        "作为资深 TA，请诊断以下代码运行时崩溃的根本原因：\n\n"
        f"【报错堆栈】:\n{tb}\n\n"
        "请用 1~2 句话指出：\n"
        "1. 哪一行由于什么原因崩溃；\n"
        "2. 下一轮重写时如何做防御性类型过滤（如 isinstance(x, str)）。"
    )

    response = llm_client.chat.completions.create(
        model=DEFAULT_MODEL,
        messages=[{"role": "user", "content": diag_prompt}],
        temperature=0.1,
        max_tokens=500,
    )
    notes = response.choices[0].message.content or "应在处理前使用 isinstance 过滤非字符串资产项。"
    print(f"  ↳ 🧠 诊断结论:\n{notes.strip()}\n")

    return {
        "retry_count": new_retry,
        "reflection_notes": notes,
        "audit_trail": [f"[Reflect] 根因分析完毕，触发第 {new_retry} 次重写闭环"],
    }


def delivery_report_node(state: StudioPipelineJobState) -> Dict[str, Any]:
    """[节点 6: 任务交付报告]"""
    print("\n🎉 [Node 6: Delivery Report] 整个工作流自愈执行通过，生成最终交付单！")
    return {
        "audit_trail": ["[Report] 工作流圆满达成目标"],
    }


def abort_and_alert_node(state: StudioPipelineJobState) -> Dict[str, Any]:
    """[节点 7: 终止并报警]"""
    print("\n🚨 [Node 7: Abort & Alert] 任务已安全中止！")
    return {
        "audit_trail": ["[Alert] 操作被拒绝或超出最大重试次数，安全退出"],
    }


# ==============================================================================
# 4. 条件路由中心 (Routers)
# ==============================================================================
def route_risk_check(state: StudioPipelineJobState) -> Literal["require_approval", "auto_proceed"]:
    """高危路由：高危操作必须走向人工审批，普通读取直接放行。"""
    if state["is_high_risk"] and not state["human_approved"]:
        return "require_approval"
    return "auto_proceed"


def route_approval_result(state: StudioPipelineJobState) -> Literal["proceed_code_gen", "reject_exit"]:
    """审批结果路由：批准则继续生成代码，拒绝则终止退出。"""
    if state["human_approved"]:
        return "proceed_code_gen"
    return "reject_exit"


def route_execution_result(
    state: StudioPipelineJobState,
) -> Literal["success_flow", "retry_flow", "abort_flow"]:
    """执行结果路由：成功即汇报，失败重试，超限报警。"""
    if state["is_success"]:
        return "success_flow"
    if state["retry_count"] < state["max_retries"]:
        return "retry_flow"
    return "abort_flow"


# ==============================================================================
# 5. 图拓扑编排与编译 (Graph Compilation with Checkpointer)
# ==============================================================================
def build_enterprise_pipeline_graph():
    """构建带持久化 Checkpoint 与自愈回路的企业级 LangGraph。"""
    workflow = StateGraph(StudioPipelineJobState)

    # 1. 注册节点
    workflow.add_node("plan", plan_and_risk_eval_node)
    workflow.add_node("human_approval", human_approval_checkpoint_node)
    workflow.add_node("code_gen", code_generation_node)
    workflow.add_node("execute", execute_and_sandbox_node)
    workflow.add_node("reflect", reflect_and_repair_node)
    workflow.add_node("delivery", delivery_report_node)
    workflow.add_node("abort", abort_and_alert_node)

    # 2. 编排边与条件分支
    workflow.add_edge(START, "plan")

    workflow.add_conditional_edges(
        "plan",
        route_risk_check,
        {
            "require_approval": "human_approval",
            "auto_proceed": "code_gen",
        },
    )

    workflow.add_conditional_edges(
        "human_approval",
        route_approval_result,
        {
            "proceed_code_gen": "code_gen",
            "reject_exit": "abort",
        },
    )

    workflow.add_edge("code_gen", "execute")

    # 自愈条件路由回路
    workflow.add_conditional_edges(
        "execute",
        route_execution_result,
        {
            "success_flow": "delivery",
            "retry_flow": "reflect",
            "abort_flow": "abort",
        },
    )

    # 反思节点闭环连回代码生成
    workflow.add_edge("reflect", "code_gen")

    workflow.add_edge("delivery", END)
    workflow.add_edge("abort", END)

    # 3. 启用 Checkpoint 状态存储器
    memory_checkpointer = MemorySaver()

    # 关键设置：通过 interrupt_before 在 human_approval 节点前强制暂停，实现人机协同！
    app = workflow.compile(
        checkpointer=memory_checkpointer,
        interrupt_before=["human_approval"],
    )

    return app


# ==============================================================================
# 6. 实战测试主流程
# ==============================================================================
def main() -> None:
    print("=" * 80)
    print("  LANGGRAPH 1.2+ 企业级游戏管线智能体 (CHECKPOINT & HUMAN-IN-THE-LOOP)")
    print("=" * 80)

    app = build_enterprise_pipeline_graph()

    # 每个作业使用唯一的 thread_id 隔离状态快照
    config = {"configurable": {"thread_id": "TA_JOB_2026_0908_001"}}

    initial_state: StudioPipelineJobState = {
        "job_id": "TA_JOB_001",
        "user_query": "批量删除废弃贴图并强制覆盖未命名前缀的母材质",  # 包含高危关键词触发人机审批
        "target_dcc": "Unreal Engine 5.8",
        "rag_context": "",
        "proposed_actions": [],
        "is_high_risk": False,
        "human_approved": False,
        "generated_code": "",
        "is_success": False,
        "execution_stdout": "",
        "error_traceback": "",
        "retry_count": 0,
        "max_retries": 2,
        "reflection_notes": "",
        "audit_trail": [],
    }

    print("\n▶️ 第一阶段：启动作业，运行至高危审批点...")
    app.invoke(initial_state, config)

    # 获取当前挂起的状态快照
    current_snapshot = app.get_state(config)
    print("\n" + "-" * 70)
    print(f"⏸️ 【系统挂起拦截】当前任务在节点 [{current_snapshot.next}] 处自动暂停！")
    print(f"⚠️ 高危检测状态: is_high_risk = {current_snapshot.values['is_high_risk']}")
    print(f"📋 待审批事项: {current_snapshot.values['proposed_actions']}")
    print("-" * 70)

    # 模拟真实世界中：Lead TA 在 Web 界面或终端中点击确认“审批通过”
    print("\n👤 [Lead TA 人工审批]: 审阅资产依赖无误，输入：【批准执行 (Approved)】！")
    # 通过 update_state 更新状态快照
    app.update_state(config, {"human_approved": True})

    print("\n▶️ 第二阶段：恢复作业运行，进入自动生成与自愈循环...")
    # 传入 None 表示从当前 Checkpoint 快照继续向下执行
    final_output = app.invoke(None, config)

    print("\n" + "=" * 80)
    print("🏁 【作业执行完成报告】:")
    print("📋 全流程不可篡改审计追踪 (Audit Trail):")
    for idx, log in enumerate(final_output["audit_trail"], 1):
        print(f"  {idx}. {log}")

    print("\n🎯 最终执行结果: " + ("【执行成功】" if final_output["is_success"] else "【失败】"))
    print(f"🔁 自愈迭代轮次: {final_output['retry_count']} 轮")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    main()
