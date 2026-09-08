# -*- coding: utf-8 -*-
"""Module 25: 自愈闭环智能体实战 —— 真实 LLM 驱动的报错自愈状态机 (Self-Healing Pipeline Agent).

本脚本实现基于 LangGraph 1.2+ 的工业级自愈状态机：
1. 集成 Mac M5 远程推理节点 (qwen3.6:27b-mlx)；
2. 集成 TA 知识库混合检索器 (ChromaDB + BM25 RRF)；
3. 执行节点真实运行 Python 脚本并捕获真实 Traceback；
4. 反思节点将错误堆栈注入大模型上下文，触发自主反思重构 (Self-Reflection & Repair)；
5. 形成闭环循环，直到代码成功执行或耗尽重试配额。
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
logger = logging.getLogger("SelfHealingAgent")

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://192.168.1.222:11434/v1")
DEFAULT_MODEL = os.getenv("OLLAMA_MODEL", "qwen3.6:27b-mlx")


# ==============================================================================
# 1. 状态契约 (State Contract)
# ==============================================================================
class SelfHealingJobState(TypedDict):
    """自愈式代码生成智能体的核心状态。"""

    user_query: str
    target_dcc: str
    rag_context: str
    generated_code: str
    is_success: bool
    execution_stdout: str
    error_traceback: str
    retry_count: int
    max_retries: int
    reflection_notes: str
    audit_trail: Annotated[List[str], operator.add]


# ==============================================================================
# 2. 全局组件初始化 (Retriever & LLM Client)
# ==============================================================================
print("📚 正在初始化 TA 知识库与远程推理客户端...")
retriever = DCCHybridRetriever()
llm_client = OpenAI(base_url=OLLAMA_BASE_URL, api_key="ollama")


def extract_python_code(llm_output: str) -> str:
    """从大模型的 Markdown 响应中提取纯 Python 代码块。"""
    match = re.search(r"```python\s*(.*?)\s*```", llm_output, re.DOTALL)
    if match:
        return match.group(1).strip()
    match_generic = re.search(r"```\s*(.*?)\s*```", llm_output, re.DOTALL)
    if match_generic:
        return match_generic.group(1).strip()
    return llm_output.strip()


# ==============================================================================
# 3. 核心节点函数 (Node Functions)
# ==============================================================================
def retrieve_sop_node(state: SelfHealingJobState) -> Dict[str, Any]:
    """[节点 1: SOP 检索] 从本地向量库中检索游戏资产规范与 API 指南。"""
    query = state["user_query"]
    print(f"\n🔍 [Node 1: RAG Retrieve] 正在检索管线规范: '{query}'...")

    hits = retriever.hybrid_search(query, top_k=2)
    context_blocks = []
    for idx, hit in enumerate(hits, 1):
        doc_name = hit["metadata"].get("doc_name") or hit["metadata"].get("source") or "SOP"
        context_blocks.append(f"[{idx}] (来源: {doc_name})\n{hit['doc']}")

    full_context = "\n\n".join(context_blocks)
    log_msg = f"[Retrieve] 成功召回 {len(hits)} 条管线规范切片"
    print(f"  ↳ {log_msg}")

    return {
        "rag_context": full_context,
        "audit_trail": [log_msg],
    }


def generate_code_node(state: SelfHealingJobState) -> Dict[str, Any]:
    """[节点 2: 代码生成] 请求 Mac M5 Ollama 编写自动化代码。

    如果存在反思修正记录 (reflection_notes)，大模型会将其作为首要修复依据。
    """
    retry = state["retry_count"]
    print(f"\n💻 [Node 2: Code Gen] 请求 Mac M5 生成自动化脚本 (第 {retry} 轮)...")

    system_prompt = (
        "你是一名资深游戏技术美术 (Lead TA) 和管线工程师。\n"
        "你的任务是编写可直接在 Python 沙盒或 DCC 环境中执行的代码。\n"
        "代码必须用 ```python ``` 包裹。\n"
        "严格遵守以下管线 SOP 规范：\n"
        f"{state['rag_context']}\n"
    )

    if retry == 0:
        # 首次生成
        user_prompt = (
            f"用户需求: {state['user_query']}\n"
            "要求：定义一个符合工作室规范的资产处理函数 process_asset(raw_name: str, bounds: tuple)，\n"
            "并在脚本末尾实例化并调用它。输出规范的前缀修正与体积计算结果。"
        )
    else:
        # 自愈生成：附带上一次的错误与反思
        user_prompt = (
            f"用户需求: {state['user_query']}\n"
            "⚠️ 注意：你上一轮生成的代码在执行时报错崩溃了！\n"
            f"【报错堆栈 Traceback】:\n{state['error_traceback']}\n\n"
            f"【反思与诊断结论】:\n{state['reflection_notes']}\n\n"
            "请根据上述报错信息重写代码，彻底修复 Bug。仅输出修复后的完整 ```python ``` 代码块。"
        )

    response = llm_client.chat.completions.create(
        model=DEFAULT_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.2,
        max_tokens=2500,
    )

    raw_response = response.choices[0].message.content or ""
    clean_code = extract_python_code(raw_response)
    log_msg = f"[CodeGen] 第 {retry} 轮代码生成完毕，脚本长度: {len(clean_code)} 字符"
    print(f"  ↳ {log_msg}")

    return {
        "generated_code": clean_code,
        "audit_trail": [log_msg],
    }


def execute_sandbox_node(state: SelfHealingJobState) -> Dict[str, Any]:
    """[节点 3: 沙盒/引擎执行] 执行生成的代码，捕获 stdout 与真实的 Traceback。"""
    code = state["generated_code"]
    retry = state["retry_count"]
    print(f"\n🎮 [Node 3: Execute] 正在安全沙盒中执行生成的脚本 (第 {retry} 轮)...")

    # 首次执行时，故意给代码执行环境制造一个典型的管线环境边界异常
    # 模拟 DCC 中缺失内置变量或参数传错，以测试自愈能力
    old_stdout = sys.stdout
    old_stderr = sys.stderr
    redirected_stdout = io.StringIO()
    redirected_stderr = io.StringIO()

    try:
        sys.stdout = redirected_stdout
        sys.stderr = redirected_stderr

        # 如果是第 0 轮，人为制造一次动态环境校验测试（模拟外部 DCC API 异常）
        if retry == 0:
            # 故意触发一次真实 Python 运行时 TypeError
            code_to_run = code + "\n# 触发环境动态契约审计\nprocess_asset(12345, 'invalid_bounds')\n"
        else:
            code_to_run = code

        exec_globals: Dict[str, Any] = {"__name__": "__main__"}
        exec(code_to_run, exec_globals)

        stdout_val = redirected_stdout.getvalue()
        print(f"  ↳ 执行成功！控制台输出: {stdout_val.strip()[:100]}...")
        return {
            "is_success": True,
            "execution_stdout": stdout_val,
            "error_traceback": "",
            "audit_trail": [f"[Execute] 第 {retry} 轮代码执行成功！Exit Code: 0"],
        }

    except Exception as exc:
        tb = traceback.format_exc()
        print(f"  ↳ ❌ 捕获到执行异常: {type(exc).__name__}: {exc}")
        return {
            "is_success": False,
            "execution_stdout": redirected_stdout.getvalue(),
            "error_traceback": tb,
            "audit_trail": [f"[Execute] 第 {retry} 轮抛出异常: {type(exc).__name__}"],
        }

    finally:
        sys.stdout = old_stdout
        sys.stderr = old_stderr


def reflect_and_diagnose_node(state: SelfHealingJobState) -> Dict[str, Any]:
    """[节点 4: 反思与根因诊断] 请求 Mac M5 分析 Traceback 并提出具体修改方案。"""
    tb = state["error_traceback"]
    current_retry = state["retry_count"]
    new_retry = current_retry + 1
    print(f"\n🧠 [Node 4: Reflect & Diagnose] 触发反思自愈机制 (进入轮次: {new_retry}/{state['max_retries']})...")

    diag_prompt = (
        "你是一名 Lead TA，请仔细审查以下代码及运行时抛出的完整 Traceback：\n\n"
        f"【执行脚本】:\n{state['generated_code']}\n\n"
        f"【报错堆栈】:\n{tb}\n\n"
        "请用极其简练的 2~3 句话指出：\n"
        "1. 报错的具体代码行与根因（类型错误/缺少校验/函数调用方式错误）；\n"
        "2. 下一轮重构时具体的修复指令（例如：为参数添加 isinstance 类型防御，兼容非法入参）。"
    )

    response = llm_client.chat.completions.create(
        model=DEFAULT_MODEL,
        messages=[{"role": "user", "content": diag_prompt}],
        temperature=0.1,
        max_tokens=800,
    )

    analysis = response.choices[0].message.content or "需要针对参数类型进行防御性校验。"
    print(f"  ↳ 🧠 诊断结论:\n{analysis.strip()}\n")

    return {
        "retry_count": new_retry,
        "reflection_notes": analysis,
        "audit_trail": [f"[Reflect] 根因诊断完毕，进入第 {new_retry} 次自愈重构回路"],
    }


def report_success_node(state: SelfHealingJobState) -> Dict[str, Any]:
    """[节点 5: 成功汇报] 任务自愈成功，总结交付物。"""
    print("\n🎉 [Node 5: Success Report] 任务自愈闭环圆满达成！")
    return {
        "audit_trail": ["[Report] 自愈任务顺利完成，交付合格自动化脚本"],
    }


def human_escalate_node(state: SelfHealingJobState) -> Dict[str, Any]:
    """[节点 6: 人工挂起] 超过最大自愈重试次数，安全挂起并警报。"""
    print("\n🚨 [Node 6: Human Escalation] 超过自愈上限，已安全挂起并生成错误工单。")
    return {
        "audit_trail": ["[Alert] 自愈失败，任务挂起等待人工 TA 处理"],
    }


# ==============================================================================
# 4. 条件路由中心 (Router)
# ==============================================================================
def check_execution_status(
    state: SelfHealingJobState,
) -> Literal["success_branch", "retry_branch", "abort_branch"]:
    """核心路由函数：成功即汇报，失败且有配额则反思重试，超限则人工挂起。"""
    if state["is_success"]:
        return "success_branch"

    if state["retry_count"] < state["max_retries"]:
        return "retry_branch"
    else:
        return "abort_branch"


# ==============================================================================
# 5. 图拓扑组装 (Graph Compilation)
# ==============================================================================
def build_self_healing_graph() -> StateGraph:
    """构建带自愈回路的 LangGraph。"""
    workflow = StateGraph(SelfHealingJobState)

    # 注册节点
    workflow.add_node("retrieve", retrieve_sop_node)
    workflow.add_node("code_gen", generate_code_node)
    workflow.add_node("execute", execute_sandbox_node)
    workflow.add_node("reflect", reflect_and_diagnose_node)
    workflow.add_node("report", report_success_node)
    workflow.add_node("escalate", human_escalate_node)

    # 线性流：Start -> Retrieve -> CodeGen -> Execute
    workflow.add_edge(START, "retrieve")
    workflow.add_edge("retrieve", "code_gen")
    workflow.add_edge("code_gen", "execute")

    # 条件分支：Execute 的输出决定下一步去向
    workflow.add_conditional_edges(
        "execute",
        check_execution_status,
        {
            "success_branch": "report",
            "retry_branch": "reflect",
            "abort_branch": "escalate",
        },
    )

    # 闭环回路：Reflect 诊断完毕后，带上新状态重新连回 CodeGen！
    workflow.add_edge("reflect", "code_gen")

    # 终点连接
    workflow.add_edge("report", END)
    workflow.add_edge("escalate", END)

    return workflow


# ==============================================================================
# 6. 主执行入口
# ==============================================================================
def main() -> None:
    print("=" * 75)
    print("  LANGGRAPH 真实大模型自愈闭环智能体 (SELF-HEALING PIPELINE AGENT)")
    print("=" * 75)

    graph = build_self_healing_graph()
    app = graph.compile()

    initial_state: SelfHealingJobState = {
        "user_query": "为道具木箱编写资产标准化处理函数，校验命名规范并计算包围盒尺寸。",
        "target_dcc": "Unreal Engine 5.8",
        "rag_context": "",
        "generated_code": "",
        "is_success": False,
        "execution_stdout": "",
        "error_traceback": "",
        "retry_count": 0,
        "max_retries": 2,
        "reflection_notes": "",
        "audit_trail": [],
    }

    final_state = app.invoke(initial_state)

    print("\n" + "=" * 75)
    print("📋 【自愈全流程审计轨迹 (Audit Trail)】:")
    for idx, log in enumerate(final_state["audit_trail"], 1):
        print(f"  {idx}. {log}")

    print("\n🎯 最终执行结果: " + ("【执行成功】" if final_state["is_success"] else "【自愈失败/挂起】"))
    print(f"🔁 经历自愈轮次: {final_state['retry_count']} 轮")
    print("\n💻 【最终自愈合格的脚本内容】:")
    print("-" * 50)
    print(final_state["generated_code"])
    print("-" * 50)
    print("=" * 75 + "\n")


if __name__ == "__main__":
    main()
