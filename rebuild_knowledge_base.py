# -*- coding: utf-8 -*-
"""
File: rebuild_knowledge_base.py
Author: AFeiYA
Date: 2026-09-05
Description: 工业级知识库统一重建管线 (Single Source of Truth)。
             清理旧的临时测试集合，统筹扫描 knowledge_base/ 目录下的所有权威 Markdown 文档，
             执行结构化层级切片并构建统一权威的 ChromaDB 向量集合 'dcc_knowledge_hub'。
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

# ==============================================================================
# 配置参数
# ==============================================================================
BASE_DIR = os.path.dirname(__file__)
KB_ROOT_DIR = os.path.join(BASE_DIR, "knowledge_base")
CHROMA_PERSIST_DIR = os.path.join(BASE_DIR, "chroma_data")

# 统一的正式权威知识集合名称
TARGET_COLLECTION_NAME = "dcc_knowledge_hub"

# 需要清理淘汰的历史测试集合列表
OBSOLETE_COLLECTIONS = [
    "ue5_pipeline_knowledge",
    "ue5_chunking_lab",
    "ue5_style_guide_knowledge"
]

# 核心摄取文档清单与元数据分类映射
KNOWLEDGE_TARGETS = [
    {
        "rel_path": os.path.join("studio-pipeline", "01_ue5_python_api_cookbook.md"),
        "category": "API_Cookbook",
        "doc_type": "Official_Python_API",
        "priority": 1
    },
    {
        "rel_path": os.path.join("studio-pipeline", "02_studio_asset_specs_sop.md"),
        "category": "Studio_SOP",
        "doc_type": "Project_Spark_Bible",
        "priority": 1
    },
    {
        "rel_path": os.path.join("ue5-style-guide", "README.md"),
        "category": "Industry_Standard",
        "doc_type": "Allar_UE5_StyleGuide",
        "priority": 2
    }
]


# ==============================================================================
# 核心重建流程
# ==============================================================================
def rebuild_knowledge_base() -> None:
    print("=" * 75)
    print("🏗️ 启动 DCC 知识库统一重建与治理管线 (Rebuild Knowledge Base)")
    print(f"📁 知识库源目录: {KB_ROOT_DIR}")
    print(f"💾 向量库物理路径: {CHROMA_PERSIST_DIR}")
    print(f"🎯 目标统一集合: [{TARGET_COLLECTION_NAME}]")
    print("=" * 75)

    client = chromadb.PersistentClient(path=CHROMA_PERSIST_DIR)

    # 1. 清理历史遗留的测试集合
    print("\n🧹 [第 1 步]：清理淘汰历史测试集合与脏数据...")
    existing_col_names = [c.name for c in client.list_collections()]
    for old_name in OBSOLETE_COLLECTIONS:
        if old_name in existing_col_names:
            print(f"   🗑️ 正在删除旧集合: [{old_name}] ...")
            client.delete_collection(name=old_name)

    # 重新创建或获取目标统一集合
    if TARGET_COLLECTION_NAME in existing_col_names:
        print(f"   🔄 重置现有集合: [{TARGET_COLLECTION_NAME}] ...")
        client.delete_collection(name=TARGET_COLLECTION_NAME)

    collection = client.create_collection(
        name=TARGET_COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"}
    )
    print(f"   ✨ 已创建全新纯净的向量集合: [{TARGET_COLLECTION_NAME}] (余弦相似度度量)")

    # 2. 配置结构化 Markdown 大纲切片器 (Module 22 成果)
    headers_to_split_on = [
        ("#", "Header_1"),
        ("##", "Header_2"),
        ("###", "Header_3"),
    ]
    splitter = MarkdownHeaderTextSplitter(
        headers_to_split_on=headers_to_split_on,
        strip_headers=False
    )

    all_ids: List[str] = []
    all_documents: List[str] = []
    all_metadatas: List[Dict[str, Any]] = []
    total_chars = 0

    # 3. 逐一读取权威 Markdown 并切片富集
    print("\n📖 [第 2 步]：扫描知识库并执行语义大纲切片...")
    chunk_counter = 0

    for target in KNOWLEDGE_TARGETS:
        file_path = os.path.join(KB_ROOT_DIR, target["rel_path"])
        if not os.path.exists(file_path):
            print(f"   ⚠️ 警告：未找到文件 {file_path}，跳过。")
            continue

        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        total_chars += len(content)
        splits = splitter.split_text(content)
        print(f"   📄 解析 [{target['doc_type']}] -> {target['rel_path']} ({len(content)} 字符) => 切出 {len(splits)} 个语义块")

        for s in splits:
            chunk_counter += 1
            chunk_id = f"chunk_{chunk_counter:04d}_{target['doc_type']}"
            all_ids.append(chunk_id)
            all_documents.append(s.page_content)

            # 富集工业级元数据
            meta = dict(s.metadata)
            meta["source_file"] = target["rel_path"].replace("\\", "/")
            meta["category"] = target["category"]
            meta["doc_type"] = target["doc_type"]
            meta["software"] = "UnrealEngine"
            meta["engine_version"] = "5.4"
            all_metadatas.append(meta)

    # 4. 批量写入 ChromaDB
    print(f"\n💾 [第 3 步]：向 ChromaDB 批量写入 {len(all_ids)} 个高维向量切片...")
    t0 = time.time()
    collection.upsert(
        ids=all_ids,
        documents=all_documents,
        metadatas=all_metadatas
    )
    upsert_time = time.time() - t0
    print(f"   ✅ 向量索引构建完成！(耗时: {upsert_time:.2f} 秒，有效语料: {total_chars:,} 字符)")

    # 5. 跨域连通性探测验证
    print("\n" + "=" * 75)
    print("🔍 [第 4 步]：执行跨领域全局检索探测 (验证统一知识中枢)")
    print("=" * 75)

    test_probes = [
        ("【测试 1: 官方 API】", "如何用 Python 自动化为 FBX 网格体开启 Nanite？"),
        ("【测试 2: 项目规范】", "项目里主角模型的三角面预算是多少？ORM 贴图通道怎么打？"),
        ("【测试 3: 行业前缀】", "动画蓝图 (Anim Blueprint) 和 UI 控件蓝图 (Widget) 的规范前缀是什么？")
    ]

    for label, query in test_probes:
        res = collection.query(query_texts=[query], n_results=1)
        if res and res["documents"]:
            hit_doc = res["documents"][0][0]
            hit_meta = res["metadatas"][0][0]
            hit_dist = res["distances"][0][0]
            sim = 1.0 - hit_dist

            print(f"\n{label} 提问: 「{query}」")
            print(f"   • 命中来源: {hit_meta.get('source_file')} ({hit_meta.get('category')})")
            print(f"   • 相似度: {sim:.4f} (余弦距离: {hit_dist:.4f})")
            print(f"   • 大纲路径: {hit_meta.get('Header_1')} > {hit_meta.get('Header_2')} > {hit_meta.get('Header_3')}")
            preview = hit_doc.strip()[:140].replace("\n", " ")
            print(f"   • 命中内容: {preview}...")

    # 打印最终数据库概况
    final_cols = client.list_collections()
    print("\n" + "=" * 75)
    print("📊 重构后 ChromaDB 集合概况:")
    print("=" * 75)
    for c in final_cols:
        print(f"• 集合: [{c.name}] | 切片总数: {c.count()} chunks")
    print("\n🎉 知识库归拢与重构全部圆满成功！")
    print("=" * 75)


if __name__ == "__main__":
    rebuild_knowledge_base()
