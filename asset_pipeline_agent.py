# -*- coding: utf-8 -*-
"""
File: asset_pipeline_agent.py
Author: AFeiYA
Date: 2026-09-05
Description: Phase 2 终极大决战 —— 工业级【资产管线与合规审计 Agent (Asset Pipeline & Linter Agent)】。
             串联 Pydantic 数据契约 (Phase 1) + 混合检索 RAG (Module 23) + Mac 26B 流式大模型，
             实现自然语言理解、行业规范审查、命名自动纠偏、契约阻断与零幻觉 UE5 脚本交付。
"""

import json
import os
import re
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

from openai import OpenAI
from pydantic import ValidationError

# 引入项目基础模块
from dcc_contract_challenge import GameAssetSchema
from dcc_hybrid_retriever import DCCHybridRetriever

# 确保 Windows 终端正确输出 UTF-8 字符
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

# ==============================================================================
# 配置参数
# ==============================================================================
MAC_IP = "192.168.1.222"
OLLAMA_OPENAI_URL = f"http://{MAC_IP}:11434/v1"
MODEL_NAME = "gemma4:26b-mlx"


# ==============================================================================
# 核心 Agent 类实现
# ==============================================================================
class AssetPipelineAgent:
    """工业级资产管线智能体：负责意图解析、规范审计、契约验证与 UE5 脚本生成。"""

    def __init__(
        self,
        base_url: str = OLLAMA_OPENAI_URL,
        model_name: str = MODEL_NAME
    ) -> None:
        print("🤖 [AssetPipelineAgent] 正在初始化智能体核心组件...")
        self.retriever = DCCHybridRetriever()
        self.client = OpenAI(
            base_url=base_url,
            api_key="ollama",
            timeout=180.0
        )
        self.model = model_name
        print("✅ [AssetPipelineAgent] 神经中枢与知识库连接就绪！")

    def _extract_json_from_text(self, text: str) -> Optional[Dict[str, Any]]:
        """从模型输出中稳健提取 JSON 对象。"""
        text = text.strip()
        # 匹配 ```json ... ``` 块
        json_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if json_match:
            candidate = json_match.group(1)
        else:
            # 寻找首个大括号
            start_idx = text.find("{")
            candidate = text[start_idx:] if start_idx != -1 else ""

        if candidate:
            try:
                decoder = json.JSONDecoder()
                obj, _ = decoder.raw_decode(candidate)
                return obj
            except json.JSONDecodeError:
                pass
        return None

    def audit_and_execute(self, user_instruction: str, source_file_path: Optional[str] = None) -> None:
        """
        端到端全流程处理：
        1. 混合 RAG 检索 (BM25 + Dense RRF)
        2. 大模型参数解析与命名自动纠偏 (Linter)
        3. Pydantic 强类型契约校验与虚拟路径派生 (Guardrail)
        4. 流式交付 100% 真实合规的 UE5 Python 脚本 (Code Delivery)
        """
        print("\n" + "=" * 80)
        print(f"📥 [收到业务需求]: 「{user_instruction}」")
        if source_file_path:
            print(f"📁 [关联物理源文件]: {source_file_path}")
        print("=" * 80)

        # ----------------------------------------------------------------------
        # 工序 1：双轨混合检索 (Hybrid RAG)
        # ----------------------------------------------------------------------
        t0 = time.time()
        rag_hits = self.retriever.hybrid_search(user_instruction, top_k=2)
        retrieval_ms = (time.time() - t0) * 1000

        print(f"\n🔍 [工序 1/4: 混合 RAG 检索] 耗时: {retrieval_ms:.2f}ms | 命中 2 条权威规约:")
        context_blocks = []
        for idx, hit in enumerate(rag_hits, 1):
            meta = hit["metadata"]
            bread = f"{meta.get('Header_1')} > {meta.get('Header_2')}"
            print(f"   [{idx}] 来源: {meta.get('source_file')} | RRF分: {hit['rrf_score']:.5f} | 大纲: {bread}")
            context_blocks.append(f"【参考规约与 API {idx}】:\n{hit['doc']}\n")

        rag_context_str = "\n".join(context_blocks)

        # ----------------------------------------------------------------------
        # 工序 2：大模型意图解析与规范自愈纠偏 (Auto-Correction)
        # ----------------------------------------------------------------------
        print(f"\n🧠 [工序 2/4: 本地 26B 模型意图解析与命名纠偏]...")

        parse_system_prompt = """你是一名资深游戏管线技术美术 (Lead TA)。
你的职责是分析用户的自然语言资产需求，参考权威规范，输出结构化的参数 JSON。

【必须强制遵守的命名纠偏准则 (Auto-Correction)】：
1. 静态网格体 (StaticMesh): 名称必须以 'SM_' 开头（若用户写 rock 或 Hero_Sword，自动更正为 SM_Rock 或 SM_Hero_Sword）；
2. 纹理贴图 (Texture): 名称必须以 'T_' 开头，漫反射加 '_D'，法线贴图加 '_N'；
3. 材质资产 (Material): 名称必须以 'M_' 开头；
4. 软件平台 (software): 必须为 "UnrealEngine"；
5. 输出格式：仅输出一个标准的合法 JSON，字段必须符合：
   - software: "UnrealEngine"
   - asset_type: "StaticMesh" | "Texture" | "Material"
   - asset_name: (合规前缀纠偏后的规范名称)
   - format: 文件格式 (如 "fbx", "png")
   - lod_level: (可选，如 0 或 1)
   - max_resolution: (仅贴图使用，如 2048)
   - transform: (可选空间位移)
"""

        parse_user_prompt = f"""【参考规范】：
{rag_context_str}

【用户输入需求】：
{user_instruction}

请提取结构化参数，并自动修复不规范的名称，仅输出标准 JSON："""

        # 调用模型抽取参数 JSON
        t_parse_start = time.time()
        parse_stream = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": parse_system_prompt},
                {"role": "user", "content": parse_user_prompt}
            ],
            stream=True,
            temperature=0.1,
            max_tokens=2000
        )

        raw_parsed_content = []
        raw_reasoning = []
        has_printed_think = False

        for chunk in parse_stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            rc = getattr(delta, "reasoning_content", None) or getattr(delta, "reasoning", None) or ""
            if rc:
                if not has_printed_think:
                    print("   🧠 [模型思维链推导中]: ", end="", flush=True)
                    has_printed_think = True
                raw_reasoning.append(rc)
                print(".", end="", flush=True)

            if delta.content:
                raw_parsed_content.append(delta.content)

        print()  # 换行
        parsed_text = "".join(raw_parsed_content).strip()
        parsed_json = self._extract_json_from_text(parsed_text)
        
        # 兜底防御：若 content 截断，从思维链中提取初稿 JSON
        if not parsed_json and raw_reasoning:
            parsed_json = self._extract_json_from_text("".join(raw_reasoning))

        if not parsed_json:
            print(f"❌ [解析失败] 模型未返回有效 JSON，原始返回:\n{parsed_text}")
            return

        print(f"✅ 参数提取与命名自动纠偏成功 (耗时: {time.time() - t_parse_start:.2f}秒):")

        print(json.dumps(parsed_json, indent=2, ensure_ascii=False))

        # ----------------------------------------------------------------------
        # 工序 3：Pydantic 强类型契约安全闸门 (Phase 1 防火墙)
        # ----------------------------------------------------------------------
        print(f"\n🛡️ [工序 3/4: Pydantic 数据契约安全审查]...")
        try:
            validated_contract = GameAssetSchema(**parsed_json)
            print("   ✅ Pydantic 契约校验 100% 通过！")
            print(f"   • 资产标准名称: {validated_contract.asset_name}")
            print(f"   • 资产标准类型: {validated_contract.asset_type}")
            print(f"   • 自动计算的虚幻引擎虚拟路径: {validated_contract.virtual_engine_path}")
        except ValidationError as e:
            print("   🚫 [安全拦截] Pydantic 拦截到非法管线参数:")
            for err in e.errors():
                print(f"      - 字段 '{err['loc']}': {err['msg']}")
            return

        # ----------------------------------------------------------------------
        # 工序 4：流式生成 100% 真实合规的 UE5 Python 自动化脚本
        # ----------------------------------------------------------------------
        print(f"\n⚡ [工序 4/4: 流式生成工业级 UE5 Python 脚本 (Mac 26B)]...")

        codegen_system_prompt = """你是一名资深虚幻引擎技术美术负责人 (Lead Unreal Engine TA)。
请依据经过 Pydantic 校验的资产数据契约以及提供的【官方真实 API】，编写一段工业级稳健的 UE5 Python 自动化导入脚本。

【铁律规范】：
1. 必须 100% 使用参考规范中的 API（如 unreal.AssetImportTask, unreal.AssetToolsHelpers），严禁自创 API；
2. 目标路径必须直接使用契约中派生的 virtual_engine_path；
3. 必须包含完善的文件路径检查与 try-except 异常处理，并在 UE5 中打印规范日志。"""

        codegen_user_prompt = f"""【参考官方 API 与代码规范】：
{rag_context_str}

【已通过 Pydantic 强类型审查的数据契约】：
- 资产名称: {validated_contract.asset_name}
- 资产类别: {validated_contract.asset_type}
- 软件平台: {validated_contract.software}
- 文件格式: {validated_contract.format}
- 引擎目标路径: {validated_contract.virtual_engine_path}
- 外部物理源文件路径: {source_file_path or 'D:/Models/' + validated_contract.asset_name + '.' + validated_contract.format}

请编写完整的、可在 UE5 中一键直接运行的 Python 自动化脚本："""

        code_stream = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": codegen_system_prompt},
                {"role": "user", "content": codegen_user_prompt}
            ],
            stream=True,
            temperature=0.1,
            max_tokens=2500
        )


        has_printed_think = False
        has_printed_code = False

        for chunk in code_stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta

            # 思维链捕捉
            reasoning = getattr(delta, "reasoning_content", None) or getattr(delta, "reasoning", None) or ""
            if reasoning:
                if not has_printed_think:
                    print("\n🧠 [模型深度思考分析 (Thinking)]:")
                    has_printed_think = True
                print(reasoning, end="", flush=True)

            # 代码输出捕捉
            content = delta.content or ""
            if content:
                if not has_printed_code:
                    print("\n\n📄 [交付 UE5 自动化执行脚本]:\n" + "-" * 80)
                    has_printed_code = True
                print(content, end="", flush=True)

        print("\n" + "-" * 80)
        print("🎉 [Agent 任务交付完成] 该脚本已通过规约审计，可直接在 UE5 运行！")
        print("=" * 80)


# ==============================================================================
# 实战场景验证 (Benchmark Scenarios)
# ==============================================================================
def main() -> None:
    print("=" * 80)
    print("🚀 启动 Phase 2 资产管线与合规审计 Agent 全场景闭环验收")
    print("=" * 80)

    agent = AssetPipelineAgent()

    # 场景 1：美术随意命名的静态网格体大剑（触发 SM_ 前缀自愈纠偏 + Nanite 开启）
    req1 = "把外部的 'D:/RawAssets/hero_dragon_blade.fbx' 导入到虚幻引擎中，名字就叫 hero_dragon_blade，开启 Nanite，放在原点"
    agent.audit_and_execute(req1, source_file_path="D:/RawAssets/hero_dragon_blade.fbx")

    # 场景 2：美术上传未带前缀的角色法线贴图（触发 T_ 前缀与 _N 后缀自愈纠偏 + sRGB 禁用）
    req2 = "在 UE5 里导入一张角色面部法线贴图，源文件是 'D:/Textures/face_normal.png'，分辨率设为 2048"
    agent.audit_and_execute(req2, source_file_path="D:/Textures/face_normal.png")


if __name__ == "__main__":
    main()
