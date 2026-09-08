# -*- coding: utf-8 -*-
"""Unified Asynchronous MCP Client for Unreal Engine 5.8.

Implements Epic Games' official Streamable HTTP JSON-RPC 2.0 protocol:
- Automatic session initialization & Mcp-Session-Id header maintenance;
- Tool Search mode discovery (list_toolsets, describe_toolset);
- Safe serial execution on Unreal Engine Game Thread.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from typing import Any, Dict, List, Optional

# Ensure UTF-8 output on Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

import httpx

from dcc_agent.config import settings

logger = logging.getLogger("UENativeMCPClient")


class UEMCPError(Exception):
    """Base exception for UE MCP client errors."""


class UEMCPConnectionError(UEMCPError):
    """Raised when connecting to UE MCP server fails."""


class UEMCPToolCallError(UEMCPError):
    """Raised when an engine tool invocation fails."""


class UENativeMCPClient:
    """Production-grade Async Client for Unreal Engine 5.8 ModelContextProtocol."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> None:
        self.base_url = base_url or settings.ue_mcp_url
        self.timeout = timeout or settings.ue_timeout
        self.session_id: Optional[str] = None
        self._request_id = 0
        self._client: Optional[httpx.AsyncClient] = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    def _next_id(self) -> int:
        self._request_id += 1
        return self._request_id

    async def __aenter__(self) -> UENativeMCPClient:
        await self.connect()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        await self.close()

    async def is_online(self) -> bool:
        """Checks if the UE 5.8 MCP endpoint is responding."""
        try:
            client = self._get_client()
            res = await client.post(
                self.base_url,
                json={"jsonrpc": "2.0", "id": 0, "method": "ping", "params": {}},
            )
            return res.status_code in (200, 400, 405)
        except Exception:
            return False

    async def connect(self) -> str:
        """Initializes connection to UE 5.8 MCP and retrieves Mcp-Session-Id."""
        client = self._get_client()
        payload = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "dcc-agent-core", "version": "0.2.0"},
            },
        }
        try:
            res = await client.post(self.base_url, json=payload)
            res.raise_for_status()
        except httpx.HTTPError as exc:
            raise UEMCPConnectionError(f"Failed to connect to UE 5.8 MCP at {self.base_url}: {exc}") from exc

        self.session_id = res.headers.get("mcp-session-id")
        if not self.session_id:
            raise UEMCPConnectionError("UE MCP server did not return required 'mcp-session-id' header.")

        logger.debug("Successfully connected to UE 5.8 MCP. Session: %s", self.session_id)
        return self.session_id

    async def _post(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Dispatches a JSON-RPC request with the active session header."""
        if not self.session_id:
            await self.connect()

        client = self._get_client()
        headers = {"Mcp-Session-Id": self.session_id or ""}
        payload = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": method,
            "params": params,
        }
        try:
            res = await client.post(self.base_url, json=payload, headers=headers)
            res.raise_for_status()
            data = res.json()
        except Exception as exc:
            raise UEMCPToolCallError(f"JSON-RPC post error for '{method}': {exc}") from exc

        if "error" in data:
            err = data["error"]
            raise UEMCPToolCallError(f"UE MCP returned error code {err.get('code')}: {err.get('message')}")

        return data

    async def list_tools(self) -> List[Dict[str, Any]]:
        """Returns advertised top-level tools (or meta-tools)."""
        data = await self._post("tools/list", {})
        return data.get("result", {}).get("tools", [])

    async def call_meta_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Any:
        """Invokes a meta-tool (list_toolsets, describe_toolset, call_tool)."""
        data = await self._post("tools/call", {"name": tool_name, "arguments": arguments})
        result = data.get("result", {})
        content = result.get("content", [])
        if content and isinstance(content, list):
            text = content[0].get("text", "")
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return text
        return result

    async def list_toolsets(self) -> List[str]:
        """Returns a list of all registered toolsets in the active UE 5.8 instance."""
        raw = await self.call_meta_tool("list_toolsets", {})
        toolset_names = []
        if isinstance(raw, str):
            for line in raw.splitlines():
                if ":" in line:
                    ts_name = line.split(":")[0].replace("-", "").strip()
                    if ts_name:
                        toolset_names.append(ts_name)
        elif isinstance(raw, list):
            toolset_names = raw
        return toolset_names

    async def describe_toolset(self, toolset_name: str) -> Dict[str, Any]:
        """Queries the detailed tool schemas inside a toolset."""
        res = await self.call_meta_tool("describe_toolset", {"toolset_name": toolset_name})
        return res if isinstance(res, dict) else {}

    async def execute_engine_tool(
        self,
        toolset_name: str,
        tool_name: str,
        arguments: Dict[str, Any],
    ) -> Any:
        """Dispatches an engine tool call onto the Unreal Engine Game Thread."""
        logger.info("Dispatching to UE Game Thread: %s.%s(%s)", toolset_name, tool_name, arguments)
        return await self.call_meta_tool(
            "call_tool",
            {
                "toolset_name": toolset_name,
                "tool_name": tool_name,
                "arguments": arguments,
            },
        )

    async def close(self) -> None:
        """Closes the underlying HTTP client session."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None


# CLI Diagnostic Entrypoint
if __name__ == "__main__":
    async def _test():
        print(f"Connecting to {settings.ue_mcp_url}...")
        client = UENativeMCPClient()
        if not await client.is_online():
            print("❌ UE 5.8 MCP is offline.")
            return

        async with client:
            print("✅ Handshake successful. Session:", client.session_id)
            toolsets = await client.list_toolsets()
            print("📦 Discovered Toolsets:", toolsets)
            for ts in toolsets:
                detail = await client.describe_toolset(ts)
                print(f"  ↳ {ts}: {len(detail.get('tools', []))} tools registered.")

    asyncio.run(_test())
