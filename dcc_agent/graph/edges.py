# -*- coding: utf-8 -*-
"""Conditional Edge Routers for DCC Pipeline LangGraph Workflow.

Pure routing functions that inspect current State and return destination keys.
"""

from __future__ import annotations

from typing import Literal
from dcc_agent.graph.state import AgentPipelineState


def route_risk_check(state: AgentPipelineState) -> Literal["gate", "supervisor", "planner"]:
    """Routes to human approval gate if high risk and not yet approved."""
    if state.get("is_high_risk") and not state.get("human_approved"):
        return "gate"
    if state.get("pipeline_mode") == "single":
        return "planner"
    return "supervisor"


def route_gate_approval(state: AgentPipelineState) -> Literal["supervisor", "planner", "abort"]:
    """Routes to supervisor or action planner if approved, or aborts if rejected."""
    if state.get("human_approved"):
        if state.get("pipeline_mode") == "single":
            return "planner"
        return "supervisor"
    return "abort"


def route_execution_status(
    state: AgentPipelineState,
) -> Literal["delivery", "reflect", "abort"]:
    """Routes to delivery if successful, reflects for retry, or aborts when limit reached."""
    if state["is_success"]:
        return "delivery"
    if state["retry_count"] < state["max_retries"]:
        return "reflect"
    return "abort"
