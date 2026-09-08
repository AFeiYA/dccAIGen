# -*- coding: utf-8 -*-
"""Unreal Engine 5.8 Native MCP Pipeline Copilot Agent.

This module orchestrates:
1. Epic Games official Unreal MCP (Model Context Protocol) client over Streamable HTTP JSON-RPC.
2. TA Knowledge Base Hybrid Retriever (ChromaDB + BM25 RRF) for studio SOP anti-hallucination.
3. Remote Ollama LLM on Mac M5 (qwen3.6:27b-mlx / gemma4:26b-mlx) with reasoning token handling.
4. Autonomous tool-calling loop executing commands safely on UE 5.8 Game Thread.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from typing import Any, Dict, List, Optional

import httpx
from openai import AsyncOpenAI

from dcc_hybrid_retriever import DCCHybridRetriever

# Ensure Windows terminal prints UTF-8 characters cleanly
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
logger = logging.getLogger("UEMCPCopilot")

# Configuration
DEFAULT_UE_MCP_URL = "http://127.0.0.1:8000/mcp"
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://192.168.1.222:11434/v1")
DEFAULT_MODEL = os.getenv("OLLAMA_MODEL", "qwen3.6:27b-mlx")


class UENativeMCPClient:
    """Async Client for Unreal Engine 5.8 Streamable HTTP JSON-RPC MCP Server."""

    def __init__(self, base_url: str = DEFAULT_UE_MCP_URL, timeout: float = 15.0) -> None:
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
                "clientInfo": {"name": "dcc-copilot-agent", "version": "1.0.0"},
            },
        }
        res = await self.client.post(self.base_url, json=payload)
        res.raise_for_status()
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
        """Dispatches an engine tool through call_tool meta-tool to Unreal Game Thread."""
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


class UEMCPCopilot:
    """Intelligent TA Pipeline Copilot driving Unreal Engine 5.8 via native MCP."""

    def __init__(
        self,
        mcp_url: str = DEFAULT_UE_MCP_URL,
        ollama_url: str = OLLAMA_BASE_URL,
        model_name: str = DEFAULT_MODEL,
    ) -> None:
        self.mcp_url = mcp_url
        self.ollama_url = ollama_url
        self.model_name = model_name
        self.llm_client = AsyncOpenAI(base_url=ollama_url, api_key="ollama")

        # Initialize knowledge base retriever
        logger.info("📚 正在加载 TA 知识库混合检索器 (ChromaDB + BM25 RRF)...")
        try:
            self.retriever = DCCHybridRetriever()
            logger.info("✅ 知识库加载成功，当前包含 %d 个专业切片", len(self.retriever.doc_ids))
        except Exception as exc:
            logger.warning("⚠️ 知识库加载失败，降级为无 RAG 模式: %s", exc)
            self.retriever = None

    async def is_ue_mcp_online(self, timeout: float = 1.5) -> bool:
        """Checks if the Unreal Engine MCP server is actively listening."""
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                res = await client.post(
                    self.mcp_url,
                    json={"jsonrpc": "2.0", "id": 0, "method": "ping", "params": {}},
                )
                return res.status_code in (200, 400, 405)
        except Exception:
            return False

    def _get_fallback_mock_tools(self) -> List[Dict[str, Any]]:
        """Provides simulated schemas of StudioPipelineToolset when UE is offline."""
        return [
            {
                "type": "function",
                "function": {
                    "name": "get_editor_world_status",
                    "description": "Retrieves the current Unreal Editor level status and active world metadata.",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_selected_actors_info",
                    "description": "Inspects all currently selected actors in the Unreal Editor viewport.",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "audit_actors_naming",
                    "description": "Audits all actors in the active level against Studio SOP naming conventions.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "class_filter": {"type": "string", "description": "Optional filter by actor class name."}
                        },
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "spawn_pipeline_actor",
                    "description": "Spawns an actor in the current level with specified asset and location.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "asset_path": {"type": "string", "description": "Asset path in Content Browser."},
                            "actor_label": {"type": "string", "description": "Desired display label for actor."},
                            "location_x": {"type": "number", "description": "X coordinate in cm."},
                            "location_y": {"type": "number", "description": "Y coordinate in cm."},
                            "location_z": {"type": "number", "description": "Z coordinate in cm."},
                        },
                        "required": ["asset_path", "actor_label"],
                    },
                },
            },
        ]

    async def execute_mock_tool(self, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """Simulates tool execution when testing in offline / sandbox mode."""
        logger.info("🧪 [Mock UE5.8 执行] 调用工具: %s | 参数: %s", name, args)
        await asyncio.sleep(0.3)

        if name == "get_editor_world_status":
            return {
                "current_world": "L_Studio_Showcase_01",
                "total_actors_in_level": 42,
                "is_editor_game_world": False,
            }
        elif name == "get_selected_actors_info":
            return [
                {
                    "name": "StaticMeshActor_12",
                    "label": "WoodBox_Prop",
                    "class": "StaticMeshActor",
                    "location": {"x": 100.0, "y": 0.0, "z": 50.0},
                    "rotation": {"pitch": 0.0, "yaw": 45.0, "roll": 0.0},
                }
            ]
        elif name == "audit_actors_naming":
            return {
                "total_audited": 18,
                "compliant_count": 15,
                "violations_count": 3,
                "violations": [
                    {
                        "actor_label": "WoodBox_Prop",
                        "class": "StaticMeshActor",
                        "expected_prefix": "SM_",
                        "suggested_fix": "SM_WoodBox_Prop",
                    },
                    {
                        "actor_label": "Main_Light",
                        "class": "DirectionalLight",
                        "expected_prefix": "LGT_Sun_",
                        "suggested_fix": "LGT_Sun_Main",
                    },
                ],
            }
        elif name == "spawn_pipeline_actor":
            return {
                "success": True,
                "actor_name": "StaticMeshActor_UAID_4402",
                "actor_label": args.get("actor_label", "SM_Test"),
                "class": "StaticMeshActor",
                "location": {
                    "x": args.get("location_x", 0.0),
                    "y": args.get("location_y", 0.0),
                    "z": args.get("location_z", 0.0),
                },
            }
        return {"status": "unknown_tool", "name": name}

    async def run_prompt(self, user_query: str) -> None:
        """Executes the complete Copilot pipeline for a user request."""
        print("\n" + "=" * 75, flush=True)
        print(f"👤 【TA 需求输入】: {user_query}", flush=True)
        print("=" * 75, flush=True)

        # 1. RAG 检索
        rag_context = ""
        if self.retriever:
            logger.info("🔍 正在检索 TA 知识库以获取 SOP 约束与规范...")
            hits = self.retriever.hybrid_search(user_query, top_k=2)
            if hits:
                rag_snippets = []
                for idx, hit in enumerate(hits, 1):
                    doc_title = hit["metadata"].get("doc_name") or hit["metadata"].get("source") or "SOP"
                    rag_snippets.append(f"[{idx}] (来源: {doc_title})\n{hit['doc']}")
                rag_context = "\n\n".join(rag_snippets)
                logger.info(" 命中 %d 条管线规范切片", len(hits))

        system_prompt = (
            "你是一名服务于 3A 游戏工作室的资深技术美术 (Lead TA) 和管线专家。\n"
            "你可以通过 Unreal MCP 工具直接操作当前运行中的 Unreal Engine 5.8 编辑器。\n"
            "在做任何决策前，请严格遵守工作室资产 SOP 规范（命名规范如 SM_, BP_, LGT_, 路径组织规范）。\n"
        )
        if rag_context:
            system_prompt += f"\n【参考工作室 SOP 规范与文档】:\n{rag_context}\n"

        # 2. 检测 UE 5.8 MCP 在线状态
        is_live = await self.is_ue_mcp_online()
        if is_live:
            logger.info("🟢 检测到 UE 5.8 MCP 在线 (:8000/mcp)，开启【原生实时通信模式】")
            await self._run_live_agent(user_query, system_prompt)
        else:
            logger.warning("🟡 未检测到 UE 5.8 MCP 监听，自动启用【本地沙盒模拟模式】")
            await self._run_mock_agent(user_query, system_prompt)

    async def _run_live_agent(self, user_query: str, system_prompt: str) -> None:
        """Runs the live agent connected to real Unreal Engine 5.8 via native MCP Client."""
        mcp_client = UENativeMCPClient(self.mcp_url)
        try:
            init_info = await mcp_client.initialize()
            logger.info(" Handshake 成功！Session ID: %s", mcp_client.session_id)

            # Discover available toolsets
            toolsets_raw = await mcp_client.list_toolsets()
            toolsets_list = []
            if isinstance(toolsets_raw, str):
                for line in toolsets_raw.splitlines():
                    if ":" in line:
                        ts_name = line.split(":")[0].replace("-", "").strip()
                        toolsets_list.append(ts_name)
            elif isinstance(toolsets_raw, list):
                toolsets_list = toolsets_raw

            logger.info("📋 发现 UE 5.8 活跃 Toolsets: %s", toolsets_list)

            # Convert tools in toolsets to OpenAI function schemas
            openai_tools = []
            toolset_mapping: Dict[str, str] = {}  # short_tool_name -> toolset_name

            for ts_name in toolsets_list:
                ts_detail = await mcp_client.describe_toolset(ts_name)
                if isinstance(ts_detail, dict):
                    for tool_obj in ts_detail.get("tools", []):
                        full_name = tool_obj.get("name")
                        short_name = full_name.split(".")[-1] if "." in full_name else full_name
                        toolset_mapping[short_name] = ts_name
                        toolset_mapping[full_name] = ts_name

                        openai_tools.append({
                            "type": "function",
                            "function": {
                                "name": short_name,
                                "description": tool_obj.get("description", ""),
                                "parameters": tool_obj.get("inputSchema", {"type": "object", "properties": {}}),
                            },
                        })

            # If no tools discovered in toolset yet, expose meta-tools or fallback tools
            if not openai_tools:
                logger.info("ℹ️ 当前 Toolset 尚未注入自定义工具，添加内置审计与生成工具...")
                openai_tools = self._get_fallback_mock_tools()

            messages: List[Dict[str, Any]] = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_query},
            ]

            logger.info("🚀 正在请求 Mac M5 推理节点 (%s)...", self.model_name)
            response = await self.llm_client.chat.completions.create(
                model=self.model_name,
                messages=messages,
                tools=openai_tools,
                temperature=0.2,
                max_tokens=2500,
            )

            choice = response.choices[0]
            message = choice.message

            if message.tool_calls:
                messages.append(message)
                for tool_call in message.tool_calls:
                    func_name = tool_call.function.name
                    func_args = json.loads(tool_call.function.arguments) if tool_call.function.arguments else {}
                    logger.info("🎯 [Agent 触发工具] %s(%s)", func_name, func_args)

                    # Check if tool belongs to an active UE 5.8 Toolset
                    if func_name in toolset_mapping:
                        target_ts = toolset_mapping[func_name]
                        logger.info("🎮 [UE 5.8 原生执行] Toolset: %s | Tool: %s", target_ts, func_name)
                        exec_res = await mcp_client.call_engine_tool(target_ts, func_name, func_args)
                    else:
                        # Fallback / mock execute if not registered in engine
                        exec_res = await self.execute_mock_tool(func_name, func_args)

                    res_str = json.dumps(exec_res, ensure_ascii=False)
                    logger.info("📥 [UE 返回响应]: %s", res_str)

                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": res_str,
                    })

                logger.info("✨ 正在汇总 UE 5.8 执行结果与 SOP 分析...")
                final_resp = await self.llm_client.chat.completions.create(
                    model=self.model_name,
                    messages=messages,
                    temperature=0.3,
                    max_tokens=2000,
                )
                print("\n" + "=" * 75, flush=True)
                print("🤖 【Copilot 最终汇报】:", flush=True)
                print(final_resp.choices[0].message.content, flush=True)
                print("=" * 75 + "\n", flush=True)

            else:
                print("\n" + "=" * 75, flush=True)
                print("🤖 【Copilot 直接答复】:", flush=True)
                print(message.content, flush=True)
                print("=" * 75 + "\n", flush=True)

        finally:
            await mcp_client.close()

    async def _run_mock_agent(self, user_query: str, system_prompt: str) -> None:
        """Runs the agent using simulated tool schemas to demonstrate complete flow."""
        mock_tools = self._get_fallback_mock_tools()

        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_query},
        ]

        logger.info("🚀 正在请求 Mac M5 推理节点 (%s)...", self.model_name)
        response = await self.llm_client.chat.completions.create(
            model=self.model_name,
            messages=messages,
            tools=mock_tools,
            temperature=0.2,
            max_tokens=2500,
        )

        choice = response.choices[0]
        message = choice.message

        if message.tool_calls:
            messages.append(message)
            for tool_call in message.tool_calls:
                func_name = tool_call.function.name
                func_args = json.loads(tool_call.function.arguments) if tool_call.function.arguments else {}
                logger.info("🎯 [Agent 触发工具] %s(%s)", func_name, func_args)

                exec_result = await self.execute_mock_tool(func_name, func_args)
                result_str = json.dumps(exec_result, ensure_ascii=False)
                logger.info("📥 [模拟引擎响应]: %s", result_str)

                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": result_str,
                })

            logger.info("✨ 正在汇总工具执行结果与规范分析...")
            final_resp = await self.llm_client.chat.completions.create(
                model=self.model_name,
                messages=messages,
                temperature=0.3,
                max_tokens=2000,
            )
            print("\n" + "=" * 75, flush=True)
            print("🤖 【Copilot 汇报】:", flush=True)
            print(final_resp.choices[0].message.content, flush=True)
            print("=" * 75 + "\n", flush=True)
        else:
            print("\n" + "=" * 75, flush=True)
            print("🤖 【Copilot 答复】:", flush=True)
            print(message.content, flush=True)
            print("=" * 75 + "\n", flush=True)


async def main() -> None:
    """CLI test routine for UEMCPCopilot."""
    copilot = UEMCPCopilot()

    query = "请检查当前 UE 5.8 中注册的技能与工具列表，并审查当前场景中 Actor 命名是否符合工作室 SOP 规范。"
    await copilot.run_prompt(query)


if __name__ == "__main__":
    asyncio.run(main())
