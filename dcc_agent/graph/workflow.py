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


def create_pipeline_app(
    checkpointer: Optional[BaseCheckpointSaver] = None,
    interrupt_gate: bool = True,
) -> Any:
    """Builds and compiles the asynchronous DCC Pipeline LangGraph workflow.

    Args:
        checkpointer: Optional custom checkpointer (defaults to MemorySaver).
        interrupt_gate: If True, halts execution at 'gate' node for human TA approval.

    Returns:
        A compiled LangGraph Application instance ready for ainvoke / astream.
    """
    workflow = StateGraph(AgentPipelineState)

    # 1. Register Async Nodes
    workflow.add_node("plan", plan_and_audit_node)
    workflow.add_node("gate", human_approval_gate_node)
    workflow.add_node("planner", action_planner_node)
    workflow.add_node("execute", execute_node)
    workflow.add_node("reflect", reflect_and_patch_node)
    workflow.add_node("delivery", delivery_node)
    workflow.add_node("abort", abort_node)

    # 2. Wire Start & Conditional Edges
    workflow.add_edge(START, "plan")

    workflow.add_conditional_edges(
        "plan",
        route_risk_check,
        {"gate": "gate", "planner": "planner"},
    )

    workflow.add_conditional_edges(
        "gate",
        route_gate_approval,
        {"planner": "planner", "abort": "abort"},
    )

    workflow.add_edge("planner", "execute")

    # 3. Self-Healing Cyclic Edge
    workflow.add_conditional_edges(
        "execute",
        route_execution_status,
        {"delivery": "delivery", "reflect": "reflect", "abort": "abort"},
    )

    workflow.add_edge("reflect", "planner")

    # 4. End Edges
    workflow.add_edge("delivery", END)
    workflow.add_edge("abort", END)

    # 5. Checkpointer & Interrupt Setup
    saver = checkpointer or MemorySaver()
    interrupts = ["gate"] if interrupt_gate else []

    return workflow.compile(
        checkpointer=saver,
        interrupt_before=interrupts,
    )
