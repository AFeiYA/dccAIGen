# -*- coding: utf-8 -*-
"""LangGraph Workflow Assembler & Compiler for DCC Pipeline Agent.

Compiles the asynchronous state machine with pluggable checkpointer and
interrupt_before human-in-the-loop protection gates.
"""

from __future__ import annotations

from typing import Any, Optional
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from dcc_agent.graph.edges import (
    route_execution_status,
    route_gate_approval,
    route_risk_check,
)
from dcc_agent.graph.nodes import (
    abort_node,
    action_planner_node,
    delivery_node,
    execute_node,
    human_approval_gate_node,
    plan_and_audit_node,
    reflect_and_patch_node,
)
from dcc_agent.graph.state import AgentPipelineState
from dcc_agent.graph.subagents import (
    asset_ta_subagent_node,
    gameplay_subagent_node,
    supervisor_planning_node,
    supervisor_review_node,
    supervisor_router,
)


def create_pipeline_app(
    checkpointer: Optional[BaseCheckpointSaver] = None,
    interrupt_gate: bool = True,
) -> Any:
    """Builds and compiles the asynchronous DCC Pipeline LangGraph workflow.

    Supports both Single-Agent fast-path and Multi-Agent Supervisor team execution.
    """
    workflow = StateGraph(AgentPipelineState)

    # 1. Register Core & Single-Agent Nodes
    workflow.add_node("plan", plan_and_audit_node)
    workflow.add_node("gate", human_approval_gate_node)
    workflow.add_node("planner", action_planner_node)
    workflow.add_node("execute", execute_node)
    workflow.add_node("reflect", reflect_and_patch_node)

    # 2. Register Multi-Agent Specialized Subagent Nodes
    workflow.add_node("supervisor", supervisor_planning_node)
    workflow.add_node("asset_ta", asset_ta_subagent_node)
    workflow.add_node("gameplay", gameplay_subagent_node)
    workflow.add_node("supervisor_review", supervisor_review_node)

    # 3. Register Terminal Nodes
    workflow.add_node("delivery", delivery_node)
    workflow.add_node("abort", abort_node)

    # 4. Wire Initial & Gate Routing
    workflow.add_edge(START, "plan")

    workflow.add_conditional_edges(
        "plan",
        route_risk_check,
        {"gate": "gate", "supervisor": "supervisor", "planner": "planner"},
    )

    workflow.add_conditional_edges(
        "gate",
        route_gate_approval,
        {"supervisor": "supervisor", "planner": "planner", "abort": "abort"},
    )

    # 5. Wire Single-Agent Cycle
    workflow.add_edge("planner", "execute")
    workflow.add_conditional_edges(
        "execute",
        route_execution_status,
        {"delivery": "delivery", "reflect": "reflect", "abort": "abort"},
    )
    workflow.add_edge("reflect", "planner")

    # 6. Wire Multi-Agent Supervisor Coordination Cycle
    agent_routing_map = {
        "asset_ta": "asset_ta",
        "gameplay": "gameplay",
        "supervisor_review": "supervisor_review",
    }
    workflow.add_conditional_edges("supervisor", supervisor_router, agent_routing_map)
    workflow.add_conditional_edges("asset_ta", supervisor_router, agent_routing_map)
    workflow.add_conditional_edges("gameplay", supervisor_router, agent_routing_map)
    workflow.add_edge("supervisor_review", "delivery")

    # 7. End Edges
    workflow.add_edge("delivery", END)
    workflow.add_edge("abort", END)

    # 8. Checkpointer & Interrupt Setup
    saver = checkpointer or MemorySaver()
    interrupts = ["gate"] if interrupt_gate else []

    return workflow.compile(
        checkpointer=saver,
        interrupt_before=interrupts,
    )
