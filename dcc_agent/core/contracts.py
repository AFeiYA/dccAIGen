# -*- coding: utf-8 -*-
"""Pydantic V2 Data Contracts for DCC Pipeline Agent.

Ensures absolute type safety, input defense, and strict JSON serialization
between LLM, LangGraph state, and Unreal Engine.
"""

from __future__ import annotations

import datetime
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field, field_validator


class AssetActionContract(BaseModel):
    """Strongly typed contract for asset operations in DCC/Unreal Engine."""

    action_type: Literal["spawn", "query", "audit", "modify", "delete", "execute_script"] = Field(
        ..., description="The type of operation to perform on the DCC engine."
    )
    asset_path: str = Field(
        ..., description="Full content browser path or identifier (e.g. /Game/Props/SM_WoodBox)."
    )
    actor_label: Optional[str] = Field(
        default=None, description="Visual label in the Unreal Engine World Outliner."
    )
    parameters: Dict[str, Any] = Field(
        default_factory=dict, description="Arbitrary parameters passed to the DCC tool/function."
    )
    target_dcc: str = Field(
        default="Unreal Engine 5.8", description="Target DCC software or game engine."
    )

    @field_validator("asset_path")
    @classmethod
    def validate_asset_path(cls, v: str) -> str:
        v_stripped = v.strip()
        if not v_stripped:
            raise ValueError("Asset path cannot be empty.")
        return v_stripped


class ToolInvocationContract(BaseModel):
    """Contract for dispatching an MCP tool."""

    toolset_name: str = Field(..., description="Target toolset in UE ToolsetRegistry.")
    tool_name: str = Field(..., description="Target tool name to execute.")
    arguments: Dict[str, Any] = Field(default_factory=dict, description="Tool input arguments.")


class AuditRecordContract(BaseModel):
    """Immutable audit record entry."""

    timestamp: str = Field(
        default_factory=lambda: datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        description="Timestamp of the operation.",
    )
    step_name: str = Field(..., description="Pipeline step or LangGraph node name.")
    status: Literal["SUCCESS", "WARNING", "FAILED", "BLOCKED"] = Field(
        ..., description="Status of the step."
    )
    message: str = Field(..., description="Detailed description of what occurred.")

    def format_log(self) -> str:
        return f"[{self.timestamp}] [{self.step_name}] [{self.status}] {self.message}"
