# -*- coding: utf-8 -*-
"""Supervisor Orchestrator Agent for Multi-Agent Game Pipeline.

Deconstructs high-level user game production requirements into a formal Work
Breakdown Structure (WBS), dispatches specialized subtasks to the Asset TA Agent
and Gameplay Logic Agent, and performs holistic quality review before final delivery.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from dcc_agent.graph.state import AgentPipelineState

logger = logging.getLogger("SupervisorAgent")


async def supervisor_planning_node(state: AgentPipelineState) -> Dict[str, Any]:
    """[Supervisor: WBS Planning] Decomposes natural language requirement into subagent steps."""
    query = state["user_query"].lower()
    logger.info("Supervisor analyzing requirement: '%s'", state["user_query"])

    # Detect whether gameplay interactive logic is required
    gameplay_keywords = [
        "金币", "coin", "拾取", "pickup", "触发", "trigger",
        "蓝图", "blueprint", "玩法", "gameplay", "机关", "hazard", "door", "跳板"
    ]
    needs_gameplay = any(kw in query for kw in gameplay_keywords)

    wbs_plan: List[Dict[str, Any]] = []
    if needs_gameplay:
        wbs_plan = [
            {
                "step": 1,
                "agent": "asset_ta",
                "title": "资产与物理碰撞规范准备",
                "desc": "检查或生成道具基础几何模型、合规材质槽与碰撞体设置",
                "status": "pending",
            },
            {
                "step": 2,
                "agent": "gameplay",
                "title": "玩法逻辑蓝图组装与关卡布设",
                "desc": "生成 UE 5.8 蓝图 DSL 交互图表、编译 Blueprint 并在关卡放置实例",
                "status": "pending",
            },
        ]
        log_plan = "1. [Asset TA] 资产与物理规范准备 -> 2. [Gameplay] 蓝图 DSL 逻辑编译与摆放"
    else:
        wbs_plan = [
            {
                "step": 1,
                "agent": "asset_ta",
                "title": "资产管理与规范治理",
                "desc": "执行项目资产目录扫描、合规检查与工具集调度",
                "status": "pending",
            }
        ]
        log_plan = "1. [Asset TA] 资产管理与规范治理"

    audit_msg = f"[Supervisor] 管线总监拆解需求，制定 WBS 协同计划: {log_plan}"
    return {
        "pipeline_mode": "multi_agent",
        "wbs_plan": wbs_plan,
        "current_wbs_index": 0,
        "active_subagent": wbs_plan[0]["agent"],
        "subagent_results": {},
        "audit_trail": [audit_msg],
    }


def supervisor_router(state: AgentPipelineState) -> str:
    """Routes state machine to the next active subagent or triggers review."""
    idx = state.get("current_wbs_index", 0)
    wbs = state.get("wbs_plan", [])

    if idx < len(wbs):
        next_agent = wbs[idx]["agent"]
        logger.info("Supervisor dispatching step %d to subagent '%s'", idx + 1, next_agent)
        return next_agent

    logger.info("All WBS steps completed. Moving to supervisor review.")
    return "supervisor_review"


async def supervisor_review_node(state: AgentPipelineState) -> Dict[str, Any]:
    """[Supervisor: Review & Synthesis] Reviews deliverables from all subagents."""
    sub_results = state.get("subagent_results", {})
    spawned = state.get("spawned_actors", [])
    dsl = state.get("blueprint_dsl", "")

    all_passed = all(
        res.get("status") == "ok"
        for res in sub_results.values()
    ) if sub_results else True

    summary = {
        "pipeline_verdict": "PASSED" if all_passed else "DEGRADED",
        "completed_steps": len(state.get("wbs_plan", [])),
        "spawned_actors": spawned,
        "blueprint_dsl_generated": bool(dsl),
        "subagent_summary": sub_results,
    }

    log_msg = (
        f"[Supervisor] 全流水线工序验收完成！"
        f"生成 Actor: {spawned or '无新摆放'}, "
        f"蓝图逻辑交付: {'已完成' if dsl else '无需生成'}, "
        f"质量评估: {'合格 ✅' if all_passed else '存在警告 ⚠️'}"
    )

    return {
        "is_success": all_passed,
        "execution_result": summary,
        "audit_trail": [log_msg],
    }
