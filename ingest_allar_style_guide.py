# -*- coding: utf-8 -*-
"""
File: ingest_allar_style_guide.py
Author: AFeiYA
Date: 2026-09-05
Description: 使用 Module 22 的 MarkdownHeaderTextSplitter 将 Michael Allar 的行业顶级
             UE5 资产命名与工程结构规范 (ue5-style-guide) 批量切片并存入本地 ChromaDB 向量库。
"""

import os
import sys
import time
from typing import Any, Dict, List
import chromadb
from langchain_text_splitters import MarkdownHeaderTextSplitter

# 确保 Windows 终端正确输出 UTF-8 字符
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

BASE_DIR = os.path.dirname(__file__)
STYLE_GUIDE_FILE = os.path.join(BASE_DIR, "knowledge_base", "ue5-style-guide", "README.md")
CHROMA_PERSIST_DIR = os.path.join(BASE_DIR, "chroma_data")
COLLECTION_NAME = "ue5_style_guide_knowledge"


def ingest_style_guide() -> None:
    """读取 Allar 规范 Markdown，执行层级切片并 upsert 存入 ChromaDB。"""
    print("=" * 75)
    print("🚀 启动 Allar UE5 规范语料库切片与向量化摄取流程")
    print(f"📄 目标文档: {STYLE_GUIDE_FILE}")
    print("=" * 75)

    if not os.path.exists(STYLE_GUIDE_FILE):
        raise FileNotFoundError(f"未找到规范文件: {STYLE_GUIDE_FILE}")

    with open(STYLE_GUIDE_FILE, "r", encoding="utf-8") as f:
        raw_markdown = f.read()

    print(f"📖 成功读取原始规范！文档总字数: {len(raw_markdown)} 字符")

    # 1. 配置 Module 22 的结构化 Markdown 大纲切片器
    headers_to_split_on = [
        ("#", "Header_1"),
        ("##", "Header_2"),
        ("###", "Header_3"),
    ]

    splitter = MarkdownHeaderTextSplitter(
        headers_to_split_on=headers_to_split_on,
        strip_headers=False  # 保留标题方便大模型完整理解上下文
    )

    t0 = time.time()
    splits = splitter.split_text(raw_markdown)
    split_time = time.time() - t0
    print(f"⚡ 切片完成 (耗时: {split_time:.2f} 秒)！共生成 {len(splits)} 个高质量语义块 (Chunks)。")

    # 2. 准备灌入 ChromaDB 向量数据库
    client = chromadb.PersistentClient(path=CHROMA_PERSIST_DIR)
    collection = client.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"}
    )

    ids = []
    documents = []
    metadatas = []

    for idx, doc in enumerate(splits, 1):
        chunk_id = f"allar_ue5_rule_{idx:04d}"
        ids.append(chunk_id)
        documents.append(doc.page_content)

        # 富集元数据：保留层级面包屑大纲 + 工业标签
        meta = dict(doc.metadata)
        meta["source"] = "Allar_UE5_StyleGuide"
        meta["software"] = "UnrealEngine"
        meta["category"] = "Naming_and_Structure_SOP"
        meta["doc_version"] = "UE5_v2"
        metadatas.append(meta)

    # 3. 批量 Upsert 写入
    print("💾 正在向本地 ChromaDB 批量写入高维向量索引 (已启用余弦距离)...")
    t_upsert = time.time()
    collection.upsert(
        ids=ids,
        documents=documents,
        metadatas=metadatas
    )
    upsert_time = time.time() - t_upsert
    print(f"✅ 向量库写入成功！(耗时: {upsert_time:.2f} 秒，当前集合条目数: {collection.count()})")

    # 4. 执行多场景验证查询
    test_queries = [
        "动画蓝图 (Animation Blueprint) 的前缀应该怎么命名？",
        "材质实例 (Material Instance) 与材质函数 (Material Function) 的前缀是什么？",
        "音频音效资产 (Sound Cue) 的命名规范是什么？",
        "UI 控件控件蓝图 (Widget Blueprint) 的前缀是什么？",
        "贴图通道打包 (Texture Packing) 怎么规范命名？"
    ]

    print("\n" + "=" * 75)
    print("🎯 开始真实场景语义检索测试 (验证向量库知识覆盖度)")
    print("=" * 75)

    for q in test_queries:
        res = collection.query(query_texts=[q], n_results=1)
        if res and res["documents"]:
            hit_doc = res["documents"][0][0]
            hit_meta = res["metadatas"][0][0]
            hit_dist = res["distances"][0][0]
            sim = 1.0 - hit_dist

            print(f"\n🔍 [提问]: {q}")
            print(f"   • 相似度: {sim:.4f} (余弦距离: {hit_dist:.4f})")
            print(f"   • 面包屑: {hit_meta.get('Header_1')} > {hit_meta.get('Header_2')} > {hit_meta.get('Header_3')}")
            # 截取前 150 字预览
            preview = hit_doc.strip()[:180].replace("\n", " ")
            print(f"   • 命中规则: {preview}...")


if __name__ == "__main__":
    ingest_style_guide()
