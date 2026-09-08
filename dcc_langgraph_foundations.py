# -*- coding: utf-8 -*-
"""Module 24: LangGraph 基础实战 —— 游戏管线状态图与条件路由 (StateGraph & Conditional Edges).

本脚本演示 LangGraph 1.2+ 的核心工业级开发范式：
1. 状态契约 (State Definition with TypedDict & Reducers).
2. 节点函数 (Node Functions) 与状态增量更新.
3. 固定边 (Fixed Edges) 与动态条件路由 (Conditional Edges).
4. 有向有环图循环自愈结构：执行遇到报错 -> 自动路由至反思节点 -> 修复重试.
"""

from __future__ import annotations

import operator
import sys
from typing import Annotated, Any, Dict, List, Literal, TypedDict

from langgraph.graph import END, START, StateGraph

# 确保 Windows 终端支持 UTF-8 输出
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except AttributeError:
        pass


# ==============================================================================
# 1. 状态契约定义 (State Contract)
# ==============================================================================
class DCCPipelineJobState(TypedDict):
    """游戏管线 Agent 集中式状态契约。

    状态是 LangGraph 的核心血液，流经图中的每一个 Node。
    每个 Node 接收完整的 State，只返回需要增量更新 (Delta) 的字段字典。
    """

    # 原始用户需求
    user_prompt: str
    # 目标 DCC 引擎类型 (UE5 / Maya / Houdini)
    dcc_target: str
    # 规划的资产操作步骤列表
    plan_steps: List[str]
    # 当前生成的自动化 Python 脚本
    current_script: str
    # 执行成功与否
    is_success: bool
    # 捕获到的引擎 Traceback 报错堆栈
    error_traceback: str
    # 当前重试次数
    retry_count: int
    # 允许的最大重试上限
    max_retries: int
    # 审计与执行日志 (使用 operator.add 聚合追加，不覆盖历史)
    audit_logs: Annotated[List[str], operator.add]


# ==============================================================================
# 2. 节点函数定义 (Node Functions)
# ==============================================================================
def plan_node(state: DCCPipelineJobState) -> Dict[str, Any]:
    """[节点 1: 任务规划] 分析 TA 资产需求，拆解为标准操作步骤。"""
    prompt = state["user_prompt"]
    dcc = state["dcc_target"]
    print(f"\n🔵 [Node: Plan] 正在为 {dcc} 规划资产任务: '{prompt}'...")

    # 模拟任务规划
    steps = [
        f"1. 校验 {dcc} 场景运行状态与当前活跃关卡",
        f"2. 检索工作室 SOP，验证资产命名是否符合规范",
        f"3. 实例化目标网格并设置变换坐标",
    ]

    log_entry = f"[Plan] 成功拆解为 {len(steps)} 个管线步骤"
    return {
        "plan_steps": steps,
        "audit_logs": [log_entry],
    }


def code_gen_node(state: DCCPipelineJobState) -> Dict[str, Any]:
    """[节点 2: 代码/工具生成] 生成目标 DCC 的 Python 脚本。

    首次生成时故意注入一个笔误 (如使用了不存在的 API)，用于验证 LangGraph 的自愈闭环能力。
    """
    retry = state["retry_count"]
    dcc = state["dcc_target"]
    print(f"💻 [Node: CodeGen] 正在生成 {dcc} 自动化脚本 (当前重试轮次: {retry})...")

    if retry == 0:
        # 第一次生成：故意带有一个经典笔误 (属性拼写错误：SetActorLocaiton 而非 SetActorLocation)
        buggy_script = (
            "# UE5 Python Script (Round 0)\n"
            "import unreal\n"
            "actor = unreal.EditorLevelLibrary.spawn_actor_from_class(unreal.StaticMeshActor, unreal.Vector(0,0,0))\n"
            "actor.SetActorLocaiton(unreal.Vector(100, 200, 50))  # 故意笔误: Locaiton\n"
        )
        return {
            "current_script": buggy_script,
            "audit_logs": ["[CodeGen] 初始脚本已生成 (包含潜在笔误以触发自愈流程)"],
        }
    else:
        # 自愈修复后的脚本：修复了拼写错误
        fixed_script = (
            "# UE5 Python Script (Self-Healed)\n"
            "import unreal\n"
            "actor = unreal.EditorLevelLibrary.spawn_actor_from_class(unreal.StaticMeshActor, unreal.Vector(0,0,0))\n"
            "actor.set_actor_location(unreal.Vector(100, 200, 50), sweep=False, teleport=True)  # 已修复 API\n"
        )
        return {
            "current_script": fixed_script,
            "audit_logs": [f"[CodeGen] 脚本自愈重写完成 (第 {retry} 次重构)"],
        }


def execute_node(state: DCCPipelineJobState) -> Dict[str, Any]:
    """[节点 3: 引擎执行] 模拟在 DCC (UE 5.8) 内部执行 Python 脚本。"""
    script = state["current_script"]
    print("🎮 [Node: Execute] 正在将代码调度至 Unreal Game Thread 运行...")

    # 模拟执行与报错捕获逻辑
    if "SetActorLocaiton" in script:
        # 模拟引擎抛出 AttributeError
        fake_traceback = (
            "AttributeError: 'StaticMeshActor' object has no attribute 'SetActorLocaiton'. "
            "Did you mean: 'set_actor_location'?"
        )
        print(f"❌ [Execute 异常中断]: {fake_traceback}")
        return {
            "is_success": False,
            "error_traceback": fake_traceback,
            "audit_logs": [f"[Execute] 执行抛出异常: {fake_traceback}"],
        }
    else:
        # 执行成功
        print("✅ [Execute 成功]: 脚本在 Game Thread 上无缝执行通过！")
        return {
            "is_success": True,
            "error_traceback": "",
            "audit_logs": ["[Execute] 关卡 Actor 实例化并重定位成功，Exit Code: 0"],
        }


def reflect_and_fix_node(state: DCCPipelineJobState) -> Dict[str, Any]:
    """[节点 4: 反思与自愈] 结合报错 Traceback 分析根因，递增重试计数器。"""
    err = state["error_traceback"]
    current_retry = state["retry_count"]
    new_retry = current_retry + 1
    print(f"\n🧠 [Node: Reflect & Fix] 捕获到引擎报错，开始诊断自愈 (轮次 {new_retry}/{state['max_retries']})...")
    print(f"   ↳ 报错分析: 发现拼写笔误 'SetActorLocaiton'，建议修正为官方蛇形命名 'set_actor_location'")

    return {
        "retry_count": new_retry,
        "audit_logs": [f"[Reflect] 根因分析完成，准备触发第 {new_retry} 次重试回路"],
    }


def report_success_node(state: DCCPipelineJobState) -> Dict[str, Any]:
    """[节点 5: 成功汇报] 任务圆满完成，输出全流程审计摘要。"""
    print("\n🎉 [Node: Report] 任务执行圆满成功！正在生成交付日志...")
    return {
        "audit_logs": ["[Report] TA 资产自动化管线任务圆满达成闭环"],
    }


def human_escalate_node(state: DCCPipelineJobState) -> Dict[str, Any]:
    """[节点 6: 人工介入降级] 重试耗尽仍未解决，挂起任务并向 TA 发出警报。"""
    print("\n🚨 [Node: Human Escalation] 达到最大重试上限，自动挂起任务并通知 Lead TA 介入！")
    return {
        "audit_logs": ["[Alert] 自动化自愈超限，触发人机协同介入机制"],
    }


# ==============================================================================
# 3. 条件路由函数 (Conditional Edge Router)
# ==============================================================================
def route_execution_result(
    state: DCCPipelineJobState,
) -> Literal["success_flow", "retry_flow", "abort_flow"]:
    """条件路由决策中心：根据执行结果与重试计数决定下一个目标节点。"""
    if state["is_success"]:
        return "success_flow"

    # 如果失败，判断是否还可以重试
    if state["retry_count"] < state["max_retries"]:
        return "retry_flow"
    else:
        return "abort_flow"


# ==============================================================================
# 4. 构建 LangGraph 状态图 (StateGraph Compilation)
# ==============================================================================
def build_dcc_pipeline_graph() -> StateGraph:
    """编排并构建完整的 DCC 自愈状态图。"""
    workflow = StateGraph(DCCPipelineJobState)

    # 1. 注册所有节点
    workflow.add_node("plan", plan_node)
    workflow.add_node("code_gen", code_gen_node)
    workflow.add_node("execute", execute_node)
    workflow.add_node("reflect_and_fix", reflect_and_fix_node)
    workflow.add_node("report_success", report_success_node)
    workflow.add_node("human_escalate", human_escalate_node)

    # 2. 编排固定边 (Fixed Edges)
    workflow.add_edge(START, "plan")
    workflow.add_edge("plan", "code_gen")
    workflow.add_edge("code_gen", "execute")

    # 3. 编排条件边 (Conditional Edge with Self-Healing Loop)
    workflow.add_conditional_edges(
        "execute",
        route_execution_result,
        {
            "success_flow": "report_success",
            "retry_flow": "reflect_and_fix",
            "abort_flow": "human_escalate",
        },
    )

    # 4. 编排反思自愈后的回路：reflect_and_fix 连回 code_gen 重新生成代码
    workflow.add_edge("reflect_and_fix", "code_gen")

    # 5. 终点连接
    workflow.add_edge("report_success", END)
    workflow.add_edge("human_escalate", END)

    return workflow


# ==============================================================================
# 5. 测试与运行
# ==============================================================================
def main() -> None:
    print("=" * 75)
    print("  LANGGRAPH 1.2+ 游戏管线自愈状态机实战 (DCC SELF-HEALING GRAPH)")
    print("=" * 75)

    # 编译状态图
    workflow = build_dcc_pipeline_graph()
    app = workflow.compile()

    # 初始化状态
    initial_state: DCCPipelineJobState = {
        "user_prompt": "在场景原点生成一个道具木箱 SM_WoodBox，并移动到坐标 (100, 200, 50)",
        "dcc_target": "Unreal Engine 5.8",
        "plan_steps": [],
        "current_script": "",
        "is_success": False,
        "error_traceback": "",
        "retry_count": 0,
        "max_retries": 2,
        "audit_logs": [],
    }

    print("\n🚀 启动 LangGraph 状态图流转...")
    final_state = app.invoke(initial_state)

    # 打印最终审计追踪报告
    print("\n" + "=" * 75)
    print("📋 【全流程审计日志追踪 (Audit Trail)】:")
    for idx, log in enumerate(final_state["audit_logs"], 1):
        print(f"  {idx}. {log}")

    print("\n🎯 最终执行状态: " + ("【成功】" if final_state["is_success"] else "【失败/人工挂起】"))
    print(f"🔁 总自愈修复循环轮次: {final_state['retry_count']}")
    print("=" * 75 + "\n")


if __name__ == "__main__":
    main()
