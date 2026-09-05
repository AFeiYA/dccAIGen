# -*- coding: utf-8 -*-
"""
File: dcc_hybrid_retriever.py
Author: AFeiYA
Date: 2026-09-05
Description: Module 23 生产级实战 —— 游戏管线混合检索器 (Hybrid Retriever)。
             结合 ChromaDB 稠密向量检索 (Dense) + BM25 稀疏关键字检索 (Sparse)，
             运用倒数排名融合算法 (RRF) 实现游戏专有名词与语义意图的 100% 精准召回。
"""

import os
import re
import sys
import time
from typing import Any, Dict, List, Optional
import chromadb
from rank_bm25 import BM25Okapi

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
CHROMA_PERSIST_DIR = os.path.join(BASE_DIR, "chroma_data")
COLLECTION_NAME = "dcc_knowledge_hub"


def tokenize_for_bm25(text: str) -> List[str]:
    """
    专为游戏代码与技术文档定制的分词器：
    提取中英文字符、数字，并保留下划线连接的标识符 (如 TC_Masks, SM_Hero_Sword)。
    """
    # 转换为小写，匹配字母、数字、下划线及中文单字
    tokens = re.findall(r"[a-zA-Z0-9_]+|[\u4e00-\u9fa5]", text.lower())
    return tokens


# ==============================================================================
# 核心混合检索器类 (DCCHybridRetriever)
# ==============================================================================
class DCCHybridRetriever:
    """双轨混合检索器：集成 ChromaDB 向量语义检索与 BM25 精确关键词检索，以 RRF 算法融合。"""

    def __init__(self, chroma_path: str = CHROMA_PERSIST_DIR, collection_name: str = COLLECTION_NAME) -> None:
        self.chroma_client = chromadb.PersistentClient(path=chroma_path)
        self.collection = self.chroma_client.get_collection(name=collection_name)

        # 1. 一次性从 ChromaDB 提取所有已索引切片，用于构建内存级 BM25 稀疏索引
        t0 = time.time()
        all_data = self.collection.get()
        self.doc_ids = all_data["ids"]
        self.documents = all_data["documents"]
        self.metadatas = all_data["metadatas"]

        # 构建文档 ID 到具体内容的快速查找字典
        self.id_to_doc = {doc_id: doc for doc_id, doc in zip(self.doc_ids, self.documents)}
        self.id_to_meta = {doc_id: meta for doc_id, meta in zip(self.doc_ids, self.metadatas)}

        # 2. 对所有切片进行分词并构建 BM25 索引
        tokenized_corpus = [tokenize_for_bm25(doc) for doc in self.documents]
        self.bm25 = BM25Okapi(tokenized_corpus)
        build_time = (time.time() - t0) * 1000
        print(f"📦 [DCCHybridRetriever 就绪] 成功加载 {len(self.doc_ids)} 个切片，BM25 索引构建耗时: {build_time:.2f}ms")

    def dense_search(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """执行稠密向量检索 (Dense Retrieval / 余弦相似度)。"""
        results = self.collection.query(query_texts=[query], n_results=top_k)
        dense_hits = []

        if results and results.get("ids"):
            ids = results["ids"][0]
            distances = results["distances"][0] if results.get("distances") else [0.0] * len(ids)

            for rank, (doc_id, dist) in enumerate(zip(ids, distances), 1):
                similarity = 1.0 - dist
                dense_hits.append({
                    "id": doc_id,
                    "rank": rank,
                    "score": similarity,
                    "type": "Dense_Vector",
                    "doc": self.id_to_doc[doc_id],
                    "metadata": self.id_to_meta[doc_id]
                })

        return dense_hits

    def sparse_search(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """执行稀疏关键词检索 (Sparse Retrieval / BM25 词频与逆文档频率)。"""
        query_tokens = tokenize_for_bm25(query)
        scores = self.bm25.get_scores(query_tokens)

        # 按得分从高到低排序，获取 Top-K
        ranked_indices = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:top_k]
        sparse_hits = []

        for rank, idx in enumerate(ranked_indices, 1):
            score = scores[idx]
            if score <= 0.0:
                continue  # 过滤无任何重合关键词的无意义候选
            doc_id = self.doc_ids[idx]
            sparse_hits.append({
                "id": doc_id,
                "rank": rank,
                "score": score,
                "type": "Sparse_BM25",
                "doc": self.id_to_doc[doc_id],
                "metadata": self.id_to_meta[doc_id]
            })

        return sparse_hits

    def hybrid_search(self, query: str, top_k: int = 3, rrf_k: int = 60, recall_pool_size: int = 10) -> List[Dict[str, Any]]:
        """
        执行混合检索并使用倒数排名融合算法 (RRF) 重排序：
        RRF_Score(d) = sum( 1 / (rrf_k + rank_m(d)) )
        """
        # 1. 分别发起双轨召回 (扩大召回池到 recall_pool_size)
        dense_hits = self.dense_search(query, top_k=recall_pool_size)
        sparse_hits = self.sparse_search(query, top_k=recall_pool_size)

        # 2. 累加计算每个文档的 RRF 融合得分
        rrf_scores: Dict[str, float] = {}
        hit_details: Dict[str, Dict[str, Any]] = {}

        # 累加 Dense 榜单贡献
        for item in dense_hits:
            doc_id = item["id"]
            rank = item["rank"]
            contribution = 1.0 / (rrf_k + rank)
            rrf_scores[doc_id] = rrf_scores.get(doc_id, 0.0) + contribution
            hit_details[doc_id] = {
                "id": doc_id,
                "dense_rank": rank,
                "dense_score": item["score"],
                "sparse_rank": None,
                "sparse_score": 0.0,
                "doc": item["doc"],
                "metadata": item["metadata"]
            }

        # 累加 Sparse 榜单贡献
        for item in sparse_hits:
            doc_id = item["id"]
            rank = item["rank"]
            contribution = 1.0 / (rrf_k + rank)
            rrf_scores[doc_id] = rrf_scores.get(doc_id, 0.0) + contribution
            if doc_id in hit_details:
                hit_details[doc_id]["sparse_rank"] = rank
                hit_details[doc_id]["sparse_score"] = item["score"]
            else:
                hit_details[doc_id] = {
                    "id": doc_id,
                    "dense_rank": None,
                    "dense_score": 0.0,
                    "sparse_rank": rank,
                    "sparse_score": item["score"],
                    "doc": item["doc"],
                    "metadata": item["metadata"]
                }

        # 3. 按 RRF 得分降序排序并截取 Top-K
        sorted_ids = sorted(rrf_scores.keys(), key=lambda d_id: rrf_scores[d_id], reverse=True)[:top_k]

        fused_results = []
        for rank, d_id in enumerate(sorted_ids, 1):
            detail = hit_details[d_id]
            detail["final_rank"] = rank
            detail["rrf_score"] = rrf_scores[d_id]
            fused_results.append(detail)

        return fused_results


# ==============================================================================
# 红蓝对抗测试：Dense vs Sparse vs Hybrid 对比实验室
# ==============================================================================
def run_confrontation_benchmark() -> None:
    print("=" * 80)
    print("⚔️ 启动游戏研发管线检索红蓝对抗基准实测 (Dense vs Sparse vs Hybrid)")
    print("=" * 80)

    retriever = DCCHybridRetriever()

    # 设计三个极具代表性的典型测试用例
    test_cases = [
        {
            "title": "测试场景 1：极度精准的枚举宏定义与专有名词 (代码符号敏感)",
            "query": "TC_Masks 和 TC_Normalmap 的压缩格式规范是什么？",
            "desc": "考察当提问包含罕见 UE5 专用宏 'TC_Masks' 时，两路检索的敏感度。"
        },
        {
            "title": "测试场景 2：特定类名与 API 参数方法 (符号 + 命名敏感)",
            "query": "unreal.AssetImportTask 导入时怎么设置 automated 和 save？",
            "desc": "考察对具体的 Python 类方法与参数名的精准定位能力。"
        },
        {
            "title": "测试场景 3：纯语义意图描述、毫无具体专有名词 (模糊意图敏感)",
            "query": "怎么让远处看不到细节的那些模型更省资源？",
            "desc": "提问完全没有 'LOD' 或 'Nanite' 这几个词，考察语义泛化理解。"
        }
    ]

    for tc in test_cases:
        print("\n" + "=" * 80)
        print(f"🎯 [{tc['title']}]")
        print(f"• 说明: {tc['desc']}")
        print(f"• 提问: 「{tc['query']}」")
        print("-" * 80)

        # 1. 单独测 Dense
        dense_res = retriever.dense_search(tc["query"], top_k=2)
        print("🔹 【纯向量检索 (Dense Only)】Top-2 结果:")
        for r in dense_res:
            meta = r["metadata"]
            bread = f"{meta.get('Header_1')} > {meta.get('Header_2')} > {meta.get('Header_3')}"
            print(f"   [Rank {r['rank']}] 相似度: {r['score']:.4f} | 来源: {meta.get('source_file')} | 大纲: {bread}")

        # 2. 单独测 Sparse (BM25)
        sparse_res = retriever.sparse_search(tc["query"], top_k=2)
        print("\n🔸 【纯关键词检索 (BM25 Only)】Top-2 结果:")
        if sparse_res:
            for r in sparse_res:
                meta = r["metadata"]
                bread = f"{meta.get('Header_1')} > {meta.get('Header_2')} > {meta.get('Header_3')}"
                print(f"   [Rank {r['rank']}] BM25得分: {r['score']:.2f} | 来源: {meta.get('source_file')} | 大纲: {bread}")
        else:
            print("   (BM25 无任何关键词匹配)")

        # 3. 混合融合 Hybrid
        hybrid_res = retriever.hybrid_search(tc["query"], top_k=2)
        print("\n🚀 【混合检索融合 (Hybrid RRF)】Top-2 最终裁定:")
        for r in hybrid_res:
            meta = r["metadata"]
            bread = f"{meta.get('Header_1')} > {meta.get('Header_2')} > {meta.get('Header_3')}"
            print(f"   [冠军 {r['final_rank']}] RRF综合分: {r['rrf_score']:.5f} (Dense名次: {r['dense_rank']}, BM25名次: {r['sparse_rank']})")
            print(f"      • 来源: {meta.get('source_file')}")
            print(f"      • 大纲: {bread}")
            # 打印命中的核心正文片断
            preview = r["doc"].strip()[:140].replace("\n", " ")
            print(f"      • 内容: {preview}...")


if __name__ == "__main__":
    run_confrontation_benchmark()
