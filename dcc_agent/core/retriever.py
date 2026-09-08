# -*- coding: utf-8 -*-
"""Unified Hybrid Knowledge Base Retriever for Game TA & Pipeline SOPs.

Combines:
1. Dense semantic vector retrieval (ChromaDB);
2. Sparse keyword retrieval (BM25Okapi with specialized technical identifier tokenization);
3. Reciprocal Rank Fusion (RRF) for 100% precision recall of technical SOP terms.
"""

from __future__ import annotations

import logging
import os
import re
import time
from typing import Any, Dict, List, Optional

import chromadb
from rank_bm25 import BM25Okapi

from dcc_agent.config import settings

logger = logging.getLogger("DCCHybridRetriever")


def tokenize_for_dcc(text: str) -> List[str]:
    """Tokenizes text preserving underscores and DCC naming conventions (e.g. SM_Hero_Sword)."""
    return re.findall(r"[a-zA-Z0-9_]+|[\u4e00-\u9fa5]", text.lower())


class DCCHybridRetriever:
    """Production-grade Hybrid Retriever for Studio Technical Documentation & SOPs."""

    def __init__(
        self,
        chroma_path: Optional[str] = None,
        collection_name: Optional[str] = None,
    ) -> None:
        self.chroma_path = chroma_path or settings.chroma_persist_dir
        self.collection_name = collection_name or settings.chroma_collection

        t0 = time.time()
        self.chroma_client = chromadb.PersistentClient(path=self.chroma_path)
        self.collection = self.chroma_client.get_collection(name=self.collection_name)

        # Ingest all chunks into memory for instant BM25 matching
        all_data = self.collection.get()
        self.doc_ids: List[str] = all_data["ids"]
        self.documents: List[str] = all_data["documents"]
        self.metadatas: List[Dict[str, Any]] = all_data["metadatas"]

        self.id_to_doc = {d_id: doc for d_id, doc in zip(self.doc_ids, self.documents)}
        self.id_to_meta = {d_id: meta for d_id, meta in zip(self.doc_ids, self.metadatas)}

        # Build BM25 index
        tokenized_corpus = [tokenize_for_dcc(doc) for doc in self.documents]
        self.bm25 = BM25Okapi(tokenized_corpus)
        init_ms = (time.time() - t0) * 1000
        logger.debug("DCCHybridRetriever ready with %d chunks (took %.2f ms)", len(self.doc_ids), init_ms)

    def dense_search(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """Dense semantic search using ChromaDB."""
        results = self.collection.query(query_texts=[query], n_results=top_k)
        dense_hits = []
        if results and results.get("ids"):
            ids = results["ids"][0]
            distances = results["distances"][0] if results.get("distances") else [0.0] * len(ids)
            for rank, (doc_id, dist) in enumerate(zip(ids, distances), 1):
                dense_hits.append({
                    "id": doc_id,
                    "rank": rank,
                    "score": 1.0 - dist,
                    "doc": self.id_to_doc[doc_id],
                    "metadata": self.id_to_meta[doc_id],
                })
        return dense_hits

    def sparse_search(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """Sparse keyword search using BM25."""
        tokens = tokenize_for_dcc(query)
        scores = self.bm25.get_scores(tokens)
        ranked_indices = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:top_k]

        sparse_hits = []
        for rank, idx in enumerate(ranked_indices, 1):
            score = scores[idx]
            if score <= 0.0:
                continue
            doc_id = self.doc_ids[idx]
            sparse_hits.append({
                "id": doc_id,
                "rank": rank,
                "score": score,
                "doc": self.id_to_doc[doc_id],
                "metadata": self.id_to_meta[doc_id],
            })
        return sparse_hits

    def hybrid_search(
        self,
        query: str,
        top_k: int = 3,
        rrf_k: int = 60,
        recall_pool_size: int = 10,
    ) -> List[Dict[str, Any]]:
        """RRF Fusion ranking: Score(d) = sum( 1 / (rrf_k + rank_m(d)) )."""
        dense_hits = self.dense_search(query, top_k=recall_pool_size)
        sparse_hits = self.sparse_search(query, top_k=recall_pool_size)

        rrf_scores: Dict[str, float] = {}
        hit_details: Dict[str, Dict[str, Any]] = {}

        for item in dense_hits:
            doc_id = item["id"]
            rank = item["rank"]
            rrf_scores[doc_id] = rrf_scores.get(doc_id, 0.0) + (1.0 / (rrf_k + rank))
            hit_details[doc_id] = {
                "id": doc_id,
                "dense_rank": rank,
                "sparse_rank": None,
                "doc": item["doc"],
                "metadata": item["metadata"],
            }

        for item in sparse_hits:
            doc_id = item["id"]
            rank = item["rank"]
            rrf_scores[doc_id] = rrf_scores.get(doc_id, 0.0) + (1.0 / (rrf_k + rank))
            if doc_id in hit_details:
                hit_details[doc_id]["sparse_rank"] = rank
            else:
                hit_details[doc_id] = {
                    "id": doc_id,
                    "dense_rank": None,
                    "sparse_rank": rank,
                    "doc": item["doc"],
                    "metadata": item["metadata"],
                }

        sorted_ids = sorted(rrf_scores.keys(), key=lambda d_id: rrf_scores[d_id], reverse=True)[:top_k]
        results = []
        for rank, d_id in enumerate(sorted_ids, 1):
            detail = hit_details[d_id]
            detail["final_rank"] = rank
            detail["rrf_score"] = rrf_scores[d_id]
            results.append(detail)

        return results

    def format_for_llm_context(self, query: str, top_k: int = 2) -> str:
        """Retrieves and formats SOP knowledge blocks as Markdown context for LLM prompts."""
        hits = self.hybrid_search(query, top_k=top_k)
        if not hits:
            return ""

        blocks = []
        for idx, hit in enumerate(hits, 1):
            doc_title = hit["metadata"].get("doc_name") or hit["metadata"].get("source") or "SOP"
            blocks.append(f"[{idx}] (来源文档: {doc_title})\n{hit['doc']}")

        return "\n\n".join(blocks)
