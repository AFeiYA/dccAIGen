# -*- coding: utf-8 -*-
"""
File: check_mac_ollama.py
Author: AFeiYA
Date: 2026-09-04
Description: 远程检测并验证 Mac Ollama 服务连通性、模型列表与推理能力的诊断脚本。
Usage:
    uv run python check_mac_ollama.py [MAC_IP]
    例如: uv run python check_mac_ollama.py 192.168.1.105
"""

# ==============================================================================
# 1. 标准库导入
# ==============================================================================
import argparse
import os
import socket
import sys
import time
from typing import Any, Dict, List, Optional

# ==============================================================================
# 2. 第三方库导入
# ==============================================================================
from dotenv import load_dotenv
import httpx
from openai import OpenAI

# 确保 Windows 终端正确输出 UTF-8 字符
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

# 加载 .env 配置文件 (如果存在)
load_dotenv()


# ==============================================================================
# 3. 核心诊断类
# ==============================================================================
class OllamaDiagnoser:
    """Mac 远程 Ollama 服务全方位诊断器。"""

    def __init__(self, host: str, port: int = 11434, timeout: float = 5.0) -> None:
        self.host = host.strip()
        self.port = port
        self.timeout = timeout
        self.base_url = f"http://{self.host}:{self.port}"
        self.openai_url = f"{self.base_url}/v1"

    def check_tcp_port(self) -> bool:
        """步骤 1: 检查底层 TCP 端口是否可达 (防火墙与网卡监听状态检测)。"""
        print(f"\n[步骤 1/5] 探测 TCP 端口连通性 -> {self.host}:{self.port} ...")
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)
        try:
            sock.connect((self.host, self.port))
            sock.close()
            print(f"[PASS] TCP 端口连通成功！{self.host}:{self.port} 处于监听就绪状态。")
            return True
        except socket.timeout:
            print(f"[FAIL] 连接超时！请检查：")
            print(f"       1. Mac 的防火墙是否拦截了 {self.port} 端口？")
            print(f"       2. Mac 上是否设置了 OLLAMA_HOST=0.0.0.0:11434 (默认 127.0.0.1 会拒收外部连接)？")
            return False
        except ConnectionRefusedError:
            print(f"[FAIL] 连接被拒绝！说明 IP 可达，但 Mac 上 Ollama 服务未启动或未监听在 0.0.0.0。")
            return False
        except Exception as err:
            print(f"[FAIL] 网络连接异常: {err}")
            return False

    def check_http_service(self) -> bool:
        """步骤 2: 检查 Ollama HTTP 服务响应。"""
        print(f"\n[步骤 2/5] 验证 HTTP 根路径响应 -> {self.base_url} ...")
        try:
            with httpx.Client(timeout=self.timeout) as client:
                res = client.get(self.base_url)
                if res.status_code == 200 and "Ollama is running" in res.text:
                    print(f"[PASS] Ollama HTTP 守护进程响应正常 (返回: '{res.text.strip()}')")
                    return True
                else:
                    print(f"[FAIL] 收到非预期响应: 状态码 {res.status_code}, 内容: {res.text}")
                    return False
        except Exception as err:
            print(f"[FAIL] HTTP 握手失败: {err}")
            return False

    def list_installed_models(self) -> List[Dict[str, Any]]:
        """步骤 3: 获取 Mac 上已下载的所有模型列表。"""
        print(f"\n[步骤 3/5] 查询 Mac 磁盘上已安装的大模型列表 (/api/tags) ...")
        try:
            with httpx.Client(timeout=self.timeout) as client:
                res = client.get(f"{self.base_url}/api/tags")
                res.raise_for_status()
                data = res.json()
                models = data.get("models", [])
                
                if not models:
                    print("[WARN] Mac 上暂未下载任何大模型！请在 Mac 终端执行: ollama run qwen2.5-coder:7b")
                    return []
                
                print(f"[PASS] 成功检测到 {len(models)} 个可用模型:")
                for idx, m in enumerate(models, 1):
                    name = m.get("name")
                    size_gb = m.get("size", 0) / (1024 ** 3)
                    digest = m.get("digest", "")[:12]
                    print(f"   [{idx}] 模型名: {name:<25} | 磁盘占用: {size_gb:.2f} GB | ID: {digest}")
                return models
        except Exception as err:
            print(f"[FAIL] 获取模型列表失败: {err}")
            return []

    def check_running_models(self) -> None:
        """步骤 4: 查询当前常驻在 Mac 统一内存/显存中的模型。"""
        print(f"\n[步骤 4/5] 检查 Mac 内存中活跃加载的模型 (/api/ps) ...")
        try:
            with httpx.Client(timeout=self.timeout) as client:
                res = client.get(f"{self.base_url}/api/ps")
                res.raise_for_status()
                data = res.json()
                models = data.get("models", [])
                
                if not models:
                    print("[INFO] 当前没有模型加载在内存中 (Ollama 处于待机空闲状态，调用时会自动秒级加载)。")
                else:
                    print(f"[PASS] 当前有 {len(models)} 个模型正在内存中运行:")
                    for m in models:
                        name = m.get("name")
                        vram_gb = m.get("size_vram", 0) / (1024 ** 3)
                        expires_at = m.get("expires_at", "N/A")
                        print(f"   • {name} | 显存/内存占用: {vram_gb:.2f} GB | 保活至: {expires_at}")
        except Exception as err:
            print(f"[WARN] 获取内存模型状态失败: {err}")

    def test_openai_inference(self, model_name: str) -> bool:
        """步骤 5: 通过 OpenAI 兼容协议向 Mac 发起真实的对话推理测试。"""
        print(f"\n[步骤 5/5] 发起端到端测试对话 (使用模型: '{model_name}') ...")
        prompt = "你好！请用一句话回答：确认你已经成功在 Mac 上运行，并准备好为游戏管线编写 Python 脚本。"
        print(f"• 发送提示词: '{prompt}'")
        
        start_time = time.time()
        try:
            client = OpenAI(base_url=self.openai_url, api_key="ollama")
            response = client.chat.completions.create(
                model=model_name,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=100,
                temperature=0.3,
            )
            elapsed = time.time() - start_time
            reply = response.choices[0].message.content.strip()
            print(f"[PASS] 推理响应成功！(耗时: {elapsed:.2f} 秒)")
            print(f"• 模型回复:\n  「{reply}」")
            return True
        except Exception as err:
            print(f"[FAIL] 推理调用失败: {err}")
            return False


# ==============================================================================
# 4. 执行入口
# ==============================================================================
def main() -> None:
    parser = argparse.ArgumentParser(description="Mac 远程 Ollama 服务连通性诊断工具")
    parser.add_argument(
        "ip",
        nargs="?",
        default=os.getenv("MAC_OLLAMA_IP", ""),
        help="Mac 电脑的局域网 IP 地址 (例如: 192.168.1.105)",
    )
    args = parser.parse_args()

    mac_ip = args.ip.strip()
    if not mac_ip:
        print("=" * 70)
        print("请输入你的 Mac 局域网 IP 地址 (可直接在 Mac 终端运行 ipconfig getifaddr en0 获得)")
        print("=" * 70)
        mac_ip = input("请输入 Mac 的 IP (例如 192.168.1.105): ").strip()

    if not mac_ip:
        print("[ERROR] 未提供有效的 IP 地址，诊断终止。")
        sys.exit(1)

    print("=" * 70)
    print(f"🚀 开始对 Mac Ollama 服务进行全链路诊断: http://{mac_ip}:11434")
    print("=" * 70)

    diagnoser = OllamaDiagnoser(host=mac_ip)

    # 1. 端口测试
    if not diagnoser.check_tcp_port():
        print("\n[SUMMARY] 底层连接未建立，请优先解决 Mac 端网络/防火墙配置！")
        sys.exit(1)

    # 2. HTTP 测试
    if not diagnoser.check_http_service():
        sys.exit(1)

    # 3. 列出模型
    installed_models = diagnoser.list_installed_models()

    # 4. 检查内存
    diagnoser.check_running_models()

    # 5. 推理测试 (自动挑选已安装的模型，优先选 qwen2.5-coder)
    if installed_models:
        candidate_model = installed_models[0]["name"]
        for m in installed_models:
            if "qwen2.5-coder" in m["name"]:
                candidate_model = m["name"]
                break
        
        diagnoser.test_openai_inference(model_name=candidate_model)
    else:
        print("\n[TIP] 提示：请在 Mac 上至少拉取一个模型后重新运行本脚本！")

    print("\n" + "=" * 70)
    print("🎉 诊断全部完成！如果上面步骤均显示 [PASS]，说明 Windows 与 Mac 双机 AI 拓扑已完美贯通！")
    print("=" * 70)


if __name__ == "__main__":
    main()
