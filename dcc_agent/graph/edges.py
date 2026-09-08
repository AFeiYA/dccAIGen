# -*- coding: utf-8 -*-
"""Conditional Edge Routers for DCC Pipeline LangGraph Workflow.

Pure routing functions that inspect current State and return destination keys.
"""

from __future__ import annotations

from typing import Literal
from dcc_agent.graph.state import AgentPipelineState


def route_risk_check(state: AgentPipelineState) -> Literal["gate", "planner"]:
    """Routes to human approval gate if high risk and not yet approved."""
    if state["is_high_risk"] and not state["human_approved"]:
        return "gate"
    return "planner"


def route_gate_approval(state: AgentPipelineState) -> Literal["planner", "abort"]:
    """Routes to action planner if approved, or aborts if rejected."""
    if state["human_approved"]:
        return "planner"
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
