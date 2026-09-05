# -*- coding: utf-8 -*-
"""
File: dcc_rag_pipeline.py
Author: AFeiYA
Date: 2026-09-04
Description: Module 21 生产级落地 —— 基于 ChromaDB 向量库 + OpenAI SDK 流式协议 + Mac Ollama 26B
             的游戏管线 RAG 检索增强系统。彻底解决长推理超时与 DCC 私有 API 幻觉。
"""

import os
import sys
import time
from typing import Any, Dict, List, Optional
import chromadb
from openai import OpenAI

# 确保 Windows 终端正确输出 UTF-8 字符
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

# ==============================================================================
# 0. 配置参数
# ==============================================================================
MAC_IP = "192.168.1.222"
OLLAMA_OPENAI_URL = f"http://{MAC_IP}:11434/v1"
# 选用 26B 旗舰模型，支持深度逻辑推导与代码生成
MODEL_NAME = "gemma4:26b-mlx"
CHROMA_PERSIST_DIR = os.path.join(os.path.dirname(__file__), "chroma_data")
COLLECTION_NAME = "dcc_knowledge_hub"


# ==============================================================================
# 1. ChromaDB 向量数据库封装管理 (基于统一知识库 dcc_knowledge_hub)
# ==============================================================================
class DCCKnowledgeBase:
    """管理本地轻量向量数据库 ChromaDB 的初始化与语义检索。"""

    def __init__(self, persist_directory: str = CHROMA_PERSIST_DIR) -> None:
        self.persist_dir = persist_directory
        self.client = chromadb.PersistentClient(path=self.persist_dir)
        try:
            self.collection = self.client.get_collection(name=COLLECTION_NAME)
            print(f"📚 已连接权威知识中枢 [{COLLECTION_NAME}]！当前索引切片数: {self.collection.count()}")
        except Exception:
            print(f"⚠️ 集合 [{COLLECTION_NAME}] 未初始化，自动触发重建管线...")
            from rebuild_knowledge_base import rebuild_knowledge_base
            rebuild_knowledge_base()
            self.collection = self.client.get_collection(name=COLLECTION_NAME)


    def query_relevant_knowledge(self, query: str, top_k: int = 2, category: Optional[str] = None) -> List[Dict[str, Any]]:
        """在向量数据库中进行语义相似度搜索。"""
        where_filter = {"category": category} if category else None

        results = self.collection.query(
            query_texts=[query],
            n_results=top_k,
            where=where_filter
        )

        retrieved_items = []
        if results and results.get("documents"):
            docs = results["documents"][0]
            metas = results["metadatas"][0] if results.get("metadatas") else [{}] * len(docs)
            distances = results["distances"][0] if results.get("distances") else [0.0] * len(docs)
            ids = results["ids"][0] if results.get("ids") else [""] * len(docs)

            for doc_id, doc, meta, dist in zip(ids, docs, metas, distances):
                # 余弦距离转相似度评分 (Cosine Similarity = 1 - Cosine Distance)
                similarity = 1.0 - dist
                retrieved_items.append({
                    "id": doc_id,
                    "content": doc,
                    "metadata": meta,
                    "similarity": similarity
                })

        return retrieved_items


# ==============================================================================
# 3. 基于 OpenAI SDK 的流式 RAG 推理客户端 (支持 Thinking + Code)
# ==============================================================================
class DCCAgentRAGClient:
    """封装与本地 Mac Ollama 通信的流式客户端，杜绝 30s 阻塞超时。"""

    def __init__(self, base_url: str = OLLAMA_OPENAI_URL, model_name: str = MODEL_NAME) -> None:
        self.client = OpenAI(
            base_url=base_url,
            api_key="ollama",  # 本地 Ollama 无需真实 key
            timeout=180.0       # 允许总耗时宽限到 180s，流式读取永不超时
        )
        self.model = model_name

    def stream_generate_code(self, system_instruction: str, user_prompt: str) -> None:
        """流式调用并实时打印模型的思维链 (Thinking) 与交付代码 (Code)。"""
        stream = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": user_prompt}
            ],
            stream=True,
            temperature=0.1,
            max_tokens=1500
        )

        has_printed_think_header = False
        has_printed_code_header = False

        for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta

            # 提取思维链推导 (Gemma / DeepSeek / Qwen 思考协议)
            reasoning = getattr(delta, "reasoning_content", None) or getattr(delta, "reasoning", None) or ""
            if reasoning:
                if not has_printed_think_header:
                    print("\n🧠 [模型深度思考推导 (Thinking Chain)]:")
                    has_printed_think_header = True
                print(reasoning, end="", flush=True)

            # 提取最终交付代码
            content = delta.content or ""
            if content:
                if not has_printed_code_header:
                    print("\n\n⚡ [模型最终交付代码 (Executable Script)]:\n" + "-" * 75)
                    has_printed_code_header = True
                print(content, end="", flush=True)


# ==============================================================================
# 4. 全链路 RAG 调度器
# ==============================================================================
def run_dcc_rag_copilot(user_query: str, kb: DCCKnowledgeBase, agent: DCCAgentRAGClient) -> None:
    """端到端闭环：自然语言 -> ChromaDB 检索 -> 组装上下文 -> 流式大模型生成。"""
    print("\n" + "=" * 75)
    print(f"💬 [TA 用户提问]: 「{user_query}」")
    print("=" * 75)

    # 1. 向量相似度检索 (Retrieval)
    t0 = time.time()
    retrieved_docs = kb.query_relevant_knowledge(user_query, top_k=2)
    retrieval_time = (time.time() - t0) * 1000

    print(f"🔍 [向量检索完成] 耗时: {retrieval_time:.2f}ms | 命中 {len(retrieved_docs)} 条相关知识：")
    context_str = ""
    for idx, item in enumerate(retrieved_docs, 1):
        sim = item["similarity"]
        meta = item["metadata"]
        print(f"   [{idx}] ID: {item['id']} | 相似度: {sim:.4f} | 模块: {meta.get('module')} | 版本: {meta.get('engine_version')}")
        context_str += f"\n--- 参考知识 [{idx}] ({item['id']}) ---\n{item['content']}\n"

    # 2. 增强提示词组装 (Augmentation)
    system_instruction = """你是一名资深游戏管线技术美术 (Lead Unreal Engine Pipeline TA)。
你的职责是依据【参考官方 API 与规范手册】，为用户编写工业级、精准无幻觉的 UE5 Python 自动化脚本。

【铁律规范】：
1. 必须 100% 依据参考上下文中的类和函数编写（如 unreal.AssetImportTask, unreal.AssetToolsHelpers），严禁捏造虚假 API；
2. 严格执行项目命名与路径规约（静态网格体必须以 SM_ 开头，存放于 /Game/Environments/Meshes/ 等）；
3. 编写完整的参数类型注解与工业级错误处理机制。"""

    user_augmented_prompt = f"""【参考官方 API 与规范手册】：
{context_str}

【用户具体需求】：
{user_query}

请为我编写符合上述所有规约的完整 Python 脚本："""

    # 3. 流式生成 (Generation)
    print(f"\n📡 正在流式请求 Mac Ollama ({agent.model}) 推理中枢...")
    start_gen = time.time()
    agent.stream_generate_code(system_instruction, user_augmented_prompt)
    total_time = time.time() - start_gen

    print("\n" + "-" * 75)
    print(f"✅ [端到端流式生成交付完毕] (总耗时: {total_time:.2f} 秒 | 0 超时风险)")
    print("=" * 75)


# ==============================================================================
# 5. 主执行入口
# ==============================================================================
def main() -> None:
    print("🚀 启动 DCC 本地向量知识库 RAG 检索增强系统 (ChromaDB + OpenAI 流式 SDK)")
    kb = DCCKnowledgeBase()
    agent = DCCAgentRAGClient()

    # 测试任务：导入静态网格体并开启 Nanite，同时检验模型是否自动执行前缀纠正
    q1 = "请写一个 UE5 Python 脚本，将外部 'D:/Models/Hero_Sword.fbx' 导入到工程规范目录下，名字就叫 Hero_Sword，开启 Nanite"
    run_dcc_rag_copilot(q1, kb, agent)


if __name__ == "__main__":
    main()
