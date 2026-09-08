# -*- coding: utf-8 -*-
"""Unreal Engine 5.8 Native MCP Connection & Capability Diagnostic Probe.

This script tests the connection to an active Unreal Engine 5.8 Editor instance
running Epic's official ModelContextProtocol plugin, queries available toolsets,
and displays registered engine functions.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from typing import Any, Dict, List, Optional

import httpx

# Ensure UTF-8 output on Windows terminal
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
logger = logging.getLogger("UEMCPProbe")

DEFAULT_UE_MCP_URL = "http://127.0.0.1:8000/mcp"


class UENativeMCPClient:
    """Async Client for Unreal Engine 5.8 Streamable HTTP JSON-RPC MCP Server."""

    def __init__(self, base_url: str = DEFAULT_UE_MCP_URL, timeout: float = 10.0) -> None:
        self.base_url = base_url
        self.timeout = timeout
        self.client = httpx.AsyncClient(timeout=timeout)
        self.session_id: Optional[str] = None
        self._request_id = 0

    def _next_id(self) -> int:
        self._request_id += 1
        return self._request_id

    async def initialize(self) -> Dict[str, Any]:
        """Performs JSON-RPC initialize handshake and captures Mcp-Session-Id."""
        payload = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "dcc-copilot-probe", "version": "1.0.0"},
            },
        }
        res = await self.client.post(self.base_url, json=payload)
        res.raise_for_status()

        # Capture session ID from headers
        self.session_id = res.headers.get("mcp-session-id")
        return res.json()

    async def _post(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Sends a JSON-RPC request with the active session ID."""
        headers = {}
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id

        payload = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": method,
            "params": params,
        }
        res = await self.client.post(self.base_url, json=payload, headers=headers)
        res.raise_for_status()
        return res.json()

    async def list_tools(self) -> List[Dict[str, Any]]:
        """Invokes tools/list on UE MCP."""
        data = await self._post("tools/list", {})
        return data.get("result", {}).get("tools", [])

    async def call_meta_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Any:
        """Calls a meta tool (list_toolsets, describe_toolset, call_tool)."""
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

    async def list_toolsets(self) -> Any:
        """Queries list of registered toolsets."""
        return await self.call_meta_tool("list_toolsets", {})

    async def describe_toolset(self, toolset_name: str) -> Any:
        """Queries schema of tools in a toolset."""
        return await self.call_meta_tool("describe_toolset", {"toolset_name": toolset_name})

    async def call_engine_tool(self, toolset_name: str, tool_name: str, arguments: Dict[str, Any]) -> Any:
        """Dispatches an engine tool through call_tool meta-tool."""
        return await self.call_meta_tool(
            "call_tool",
            {
                "toolset_name": toolset_name,
                "tool_name": tool_name,
                "arguments": arguments,
            },
        )

    async def close(self) -> None:
        await self.client.aclose()


async def run_probe(url: str = DEFAULT_UE_MCP_URL) -> None:
    """Runs complete diagnostic probe against live Unreal Engine 5.8."""
    print("=" * 75)
    print("      UNREAL ENGINE 5.8 NATIVE MCP CAPABILITY PROBE")
    print("=" * 75)
    logger.info("Connecting to UE 5.8 endpoint: %s", url)

    client = UENativeMCPClient(url)
    try:
        # 1. Initialize
        init_res = await client.initialize()
        logger.info("✅ 握手成功！获取 Session ID: %s", client.session_id)
        server_info = init_res.get("result", {}).get("serverInfo", {})
        logger.info("  Server Protocol: %s", init_res.get("result", {}).get("protocolVersion"))

        # 2. List tools
        tools = await client.list_tools()
        logger.info("📋 广播基础 Meta-Tools 数量: %d", len(tools))
        for t in tools:
            logger.info("  - [%s]: %s", t["name"], t.get("description", ""))

        # 3. List Toolsets
        logger.info("\n🔍 正在通过 list_toolsets 查询 UE 5.8 中注册的全部 Toolsets...")
        toolsets = await client.list_toolsets()
        print("\n" + "-" * 75)
        print("【UE 5.8 活跃 Toolsets 清单】:")
        if isinstance(toolsets, list):
            for ts in toolsets:
                print(f"  • {ts}")
        else:
            print(f"  {toolsets}")
        print("-" * 75 + "\n")

        # 4. Describe toolsets if available
        if isinstance(toolsets, list):
            for ts in toolsets:
                # Extract toolset name if formatted as '- ToolsetRegistry.XYZ: description'
                ts_name = ts.split(":")[0].replace("-", "").strip()
                logger.info("📦 正在探索工具包细节: %s", ts_name)
                detail = await client.describe_toolset(ts_name)
                if isinstance(detail, dict):
                    tools_in_set = detail.get("tools", [])
                    logger.info("   包含工具数: %d", len(tools_in_set))
                    for sub_t in tools_in_set:
                        logger.info("     ↳ %s: %s", sub_t.get("name"), sub_t.get("description", "").split("\n")[0])
        elif isinstance(toolsets, str):
            for line in toolsets.splitlines():
                if ":" in line:
                    ts_name = line.split(":")[0].replace("-", "").strip()
                    logger.info("📦 正在探索工具包细节: %s", ts_name)
                    detail = await client.describe_toolset(ts_name)
                    if isinstance(detail, dict):
                        tools_in_set = detail.get("tools", [])
                        logger.info("   包含工具数: %d", len(tools_in_set))
                        for sub_t in tools_in_set:
                            logger.info("     ↳ %s: %s", sub_t.get("name"), sub_t.get("description", "").split("\n")[0])

        print("\n" + "=" * 75)
        print("🎉 UE 5.8 原生 MCP 探测测试 100% 成功！通道已全面打通！")
        print("=" * 75 + "\n")

    except Exception as exc:
        logger.exception("❌ 探测执行异常: %s", exc)
    finally:
        await client.close()


def main() -> None:
    target_url = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_UE_MCP_URL
    asyncio.run(run_probe(target_url))


if __name__ == "__main__":
    main()
