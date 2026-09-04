# -*- coding: utf-8 -*-
"""
File: benchmark_speed.py
Author: AFeiYA
Date: 2026-09-04
Description: 对比测试 Mac 上 e4b-mlx (8.1B) 与 26b-mlx (15.5GB) 的实际推理速度与吞吐量。
"""

import sys
import time
import httpx

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

MAC_URL = "http://192.168.1.222:11434/api/generate"
MODELS_TO_TEST = [
    ("gemma4:e4b-mlx", "8.1B (小模型/轻量版)"),
    ("gemma4:26b-mlx", "26B (大模型/高智商版)")
]

PROMPT = "请用 Python 写一个函数，遍历当前选中的资产，如果不是以 'SM_' 开头则自动加上前缀并打印。写出简短代码。"

def test_model(model_name: str, label: str) -> None:
    print("\n" + "=" * 70)
    print(f"⚡ 开始测试: {model_name} -> {label}")
    print("=" * 70)
    
    payload = {
        "model": model_name,
        "prompt": PROMPT,
        "stream": False,
        "options": {
            "temperature": 0.3,
            "num_predict": 120
        }
    }
    
    start_wall = time.time()
    try:
        with httpx.Client(timeout=60.0) as client:
            res = client.post(MAC_URL, json=payload)
            res.raise_for_status()
            data = res.json()
            
        wall_time = time.time() - start_wall
        response_text = data.get("response", "").strip()
        eval_count = data.get("eval_count", 0)  # 生成 token 数
        eval_duration = data.get("eval_duration", 1) / 1e9  # 生成耗时 (秒)
        prompt_eval_duration = data.get("prompt_eval_duration", 0) / 1e9  # 提示词编码耗时
        
        tok_per_sec = eval_count / eval_duration if eval_duration > 0 else 0
        
        print(f"[代码生成预览]:\n{response_text[:180]}...\n")
        print("[硬件实测硬指标 (来自 Mac M5 Metal 统计)]:")
        print(f"• 提示词预处理耗时: {prompt_eval_duration:.3f} 秒")
        print(f"• 生成 Token 总数: {eval_count} tokens")
        print(f"• 纯生成耗时: {eval_duration:.3f} 秒 (总耗时: {wall_time:.2f} 秒)")
        print(f"• 🚀 实际生成速度: {tok_per_sec:.2f} tokens/秒")
        
    except Exception as e:
        print(f"[ERROR] 测试失败: {e}")

def main():
    print("🚀 连接 Mac Ollama: http://192.168.1.222:11434")
    for model_name, label in MODELS_TO_TEST:
        test_model(model_name, label)
    print("\n" + "=" * 70)
    print("🎉 真实硬件性能基准对比测试完成！")
    print("=" * 70)

if __name__ == "__main__":
    main()
