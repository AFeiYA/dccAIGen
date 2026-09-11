# -*- coding: utf-8 -*-
"""Unified LangGraph State Contract for Game Pipeline Agent.

Defines the centralized state flowing across all nodes in the state machine,
with append-only reducers for immutable audit logging.
"""

from __future__ import annotations

import operator
from typing import Annotated, Any, Dict, List, TypedDict


class AgentPipelineState(TypedDict):
    """Centralized state dictionary for the DCC Pipeline Agent."""

    # 1. Job Metadata
    job_id: str
    user_query: str
    target_dcc: str

    # 2. Knowledge & Risk Assessment
    rag_context: str
    is_high_risk: bool
    human_approved: bool
    ue_mcp_online: bool

    # 3. Planning & Code Generation
    action_plan: List[str]
    current_action: str
    action_args: Dict[str, Any]
    generated_code: str

    # 4. Execution & Verification
    execution_result: Dict[str, Any]
    is_success: bool
    error_message: str

    # 5. Self-Healing Loop
    retry_count: int
    max_retries: int
    reflection_notes: str

    # 6. Immutable Audit Trail (Append-Only)
    audit_trail: Annotated[List[str], operator.add]

    # 7. Multi-Agent Coordination & WBS
    pipeline_mode: str
    active_subagent: str
    wbs_plan: List[Dict[str, Any]]
    current_wbs_index: int
    subagent_results: Dict[str, Any]
    blueprint_dsl: str
    spawned_actors: List[str]
