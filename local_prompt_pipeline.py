# -*- coding: utf-8 -*-
"""
File: local_prompt_pipeline.py
Author: AFeiYA
Date: 2026-09-04
Description: 结合本地大模型 (Mac Ollama) + 高级 Few-Shot 提示词工程 + Pydantic 数据契约的完整落地闭环。
"""

import json
import re
import sys
import time
from typing import Any, Dict
import httpx

# 导入我们之前编写并严格测试过的 Pydantic 契约模型
from dcc_contract_challenge import GameAssetSchema, ValidationError

# 确保 Windows 终端正确输出 UTF-8 字符
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

MAC_IP = "192.168.1.222"
OLLAMA_URL = f"http://{MAC_IP}:11434/api/generate"
# 使用极速版模型 (71 tokens/秒，响应只需 3~4 秒)
MODEL_NAME = "gemma4:e4b-mlx"


# ==============================================================================
# 1. 构建工业级 Few-Shot + Persona 提示词模板 (Module 16 & 17)
# ==============================================================================
SYSTEM_PROMPT = """你是一名精通游戏研发管线与数据结构的资深技术美术 (Lead Pipeline TA)。
你的职责是将用户的自然语言资产需求，精准转换为符合工作室规范的 JSON 数据。

【工作室核心资产规范】：
1. 静态网格体 (StaticMesh) 名称必须以 "SM_" 开头，不得设置贴图分辨率；
2. 贴图资产 (Texture) 名称必须以 "T_" 开头，必须包含 max_resolution；
3. 材质资产 (Material) 名称必须以 "M_" 开头；
4. 软件平台 (software) 仅支持: "UnrealEngine", "Houdini", "Maya"；
5. 资产类别 (asset_type) 仅支持: "StaticMesh", "Texture", "Material"；
6. 严格只输出合法 JSON 格式，不得包含任何多余文本。
"""

FEW_SHOT_EXAMPLES = """
[示例 1]
用户需求: "在虚幻5里导入一个岩石模型，格式为 fbx，细分设为 1，放在原点"
输出: {"software": "UnrealEngine", "asset_type": "StaticMesh", "asset_name": "SM_Rock_Default", "format": "fbx", "lod_level": 1, "transform": {"translation": {"x": 0.0, "y": 0.0, "z": 0.0}, "scale": {"x": 1.0, "y": 1.0, "z": 1.0}}}

[示例 2]
用户需求: "在虚幻引擎中导入一张角色面部漫反射贴图，格式 png，分辨率为 2048"
输出: {"software": "UnrealEngine", "asset_type": "Texture", "asset_name": "T_Character_Face_D", "format": "png", "max_resolution": 2048}
"""


def extract_json_string(raw_text: str) -> str:
    """使用标准 JSONDecoder 健壮提取首个完整 JSON 对象，免疫多余尾随文本。"""
    raw_text = raw_text.strip()
    start_idx = raw_text.find("{")
    if start_idx != -1:
        try:
            decoder = json.JSONDecoder()
            obj, _ = decoder.raw_decode(raw_text[start_idx:])
            return json.dumps(obj)
        except json.JSONDecodeError:
            pass
    return raw_text


def query_local_llm(user_instruction: str) -> Dict[str, Any]:
    """通过本地 Ollama 模型执行 Few-Shot 提示词推理并获取 JSON。"""
    full_prompt = f"{SYSTEM_PROMPT}\n{FEW_SHOT_EXAMPLES}\n[正式任务]\n用户需求: \"{user_instruction}\"\n输出:\n"

    payload = {
        "model": MODEL_NAME,
        "prompt": full_prompt,
        "stream": False,
        "options": {
            "temperature": 0.2,
            "num_predict": 800,  # 为深度思考模型 (Reasoning Model) 预留足够的思维链与回答空间
        },
    }

    print(f"• 正在向 Mac Ollama ({MODEL_NAME}) 发送请求...")
    start_time = time.time()

    timeout_cfg = httpx.Timeout(180.0, connect=30.0)
    with httpx.Client(timeout=timeout_cfg) as client:
        res = client.post(OLLAMA_URL, json=payload)
        res.raise_for_status()
        data = res.json()

    elapsed = time.time() - start_time
    thinking_text = data.get("thinking", "").strip()
    raw_response = data.get("response", "").strip()
    
    if thinking_text:
        print(f"🧠 [模型思维链推导 (Thinking)]:\n{thinking_text[:200]}...\n")
    print(f"• 本地大模型推理完成！(耗时: {elapsed:.2f} 秒)")
    print(f"• 模型最终交付:\n{raw_response}\n")

    # 如果 response 为空但 thinking 包含结果，或者从 response 中提取 JSON
    text_to_parse = raw_response if raw_response else thinking_text
    clean_json_str = extract_json_string(text_to_parse)
    return json.loads(clean_json_str)


# ==============================================================================
# 2. 全链路贯通测试 (End-to-End Pipeline)
# ==============================================================================
def main() -> None:
    print("=" * 70)
    print("🚀 启动 [本地 26B 模型] + [Few-Shot 提示词工程] + [Pydantic 契约] 全链路测试")
    print("=" * 70)

    test_requests = [
        "请在虚幻引擎中创建一个名为 hero_blade 的武器大剑模型，格式 fbx，细分设为 2 级，放在高度 z=120 的位置",
        "在 Houdini 中新建一个岩石地面地形，名字就叫 Ground_Rock，格式用 usd"
    ]

    for idx, req in enumerate(test_requests, 1):
        print(f"\n" + "=" * 70)
        print(f"🎯 [测试任务 {idx}] 用户输入自然语言:")
        print(f"   「{req}」")
        print("=" * 70)

        try:
            # 1. 经过本地大模型提取数据
            parsed_json = query_local_llm(req)

            # 2. 注入 Pydantic 进行强类型与跨字段业务规范校验
            print("🛡️ 将大模型输出灌入 Pydantic 校验器...")
            validated_model = GameAssetSchema(**parsed_json)

            print("✅ 恭喜！Pydantic 校验 100% 完美通过！")
            print(f"• 解析后资产名称 (规范化后): {validated_model.asset_name}")
            print(f"• 自动计算的引擎虚拟路径: {validated_model.virtual_engine_path}")
            print(f"• 空间位移坐标: ({validated_model.transform.translation.x}, {validated_model.transform.translation.y}, {validated_model.transform.translation.z})")
            print(f"• 最终下发给 DCC 执行的规范化 JSON:\n{validated_model.model_dump_json(indent=2)}")

        except ValidationError as val_err:
            print("❌ Pydantic 拦截到模型生成的非法数据:")
            for e in val_err.errors():
                print(f"   >>> 字段 '{e.get('loc')}': {e.get('msg')}")
        except Exception as err:
            print(f"❌ 流程发生异常: {err}")

    print("\n" + "=" * 70)
    print("🎉 提示词工程 + 本地模型结构化提取全流程打通！")
    print("=" * 70)


if __name__ == "__main__":
    main()
