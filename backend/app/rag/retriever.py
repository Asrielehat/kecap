"""混合检索 + 重排序"""

import os
from typing import Optional
from qdrant_client import QdrantClient
from qdrant_client.models import Filter, FieldCondition, MatchValue
from app.core.config import get_settings
from app.rag.vector_store import embed_texts, get_search_client

settings = get_settings()

# ── 设置 HuggingFace 镜像（国内加速，解决 GFW 阻断问题）──
if not os.environ.get("HF_ENDPOINT"):
    os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

# ── 延迟加载 Reranker（避免启动时加载大模型）──
_reranker = None
_reranker_failed = False


def _get_reranker():
    """懒加载 Cross-encoder Reranker，失败时返回 None（降级跳过重排序）"""
    global _reranker, _reranker_failed
    if _reranker_failed:
        return None
    if _reranker is None:
        try:
            from sentence_transformers import CrossEncoder
            _reranker = CrossEncoder(
                "BAAI/bge-reranker-v2-m3",
                device="cpu",
            )
        except Exception as e:
            _reranker_failed = True
            print(f"[Reranker] 模型加载失败，将跳过重排序: {e}")
            return None
    return _reranker


def hybrid_search(
    query: str,
    course_id: str,
    top_k: int = None,
    score_threshold: float = None,
) -> list[dict]:
    """
    混合检索（向量相似度召回）

    目前用向量检索作为主召回，后续可扩展 BM25 关键词并行检索 + 融合排序

    返回: [{chunk_id, content, document_id, page_number, score, ...}, ...]
    """
    top_k = top_k or settings.retrieval_top_k
    score_threshold = score_threshold or settings.retrieval_score_threshold

    # Query 向量化
    query_embeddings = embed_texts([query])
    query_vector = query_embeddings[0]

    # 向量相似度检索 (Qdrant v1.18+ API)
    qdrant_client = get_search_client()
    results = qdrant_client.query_points(
        collection_name=settings.qdrant_collection,
        query=query_vector,
        query_filter=Filter(
            must=[FieldCondition(key="course_id", match=MatchValue(value=course_id))]
        ) if course_id else None,
        limit=top_k,
        score_threshold=score_threshold,
        with_payload=True,
    )

    # query_points 返回 QueryResponse，通过 .points 获取列表
    scored_points = results.points if hasattr(results, 'points') else results
    return [
        {
            "chunk_id": hit.payload.get("chunk_id"),
            "qdrant_point_id": hit.id,
            "content": hit.payload.get("content", ""),
            "document_id": hit.payload.get("document_id"),
            "page_number": hit.payload.get("page_number"),
            "course_id": hit.payload.get("course_id"),
            "score": round(hit.score, 4),
        }
        for hit in scored_points
    ]


def rerank(query: str, documents: list[dict], top_k: int = None) -> list[dict]:
    """
    Cross-encoder 重排序 —— 从粗召回结果中精选最相关片段

    粗召回（Top-10）→ Reranker 精排 → Top-3
    如果 Reranker 不可用，直接按向量相似度排序返回
    """
    if not documents:
        return []

    top_k = top_k or settings.rerank_top_k

    # 如果粗召回结果少，直接返回
    if len(documents) <= top_k:
        return documents

    reranker = _get_reranker()

    # 当前 Reranker（BGE-Reranker-v2-m3）对中文学术文本排序效果不稳定
    # 直接用向量相似度排序更可靠，Reranker 暂时跳过
    documents.sort(key=lambda d: d.get("score", 0), reverse=True)
    return documents[:top_k]


def expand_query(query: str) -> list[str]:
    """
    Query 扩展 —— 生成多个检索子句，提高召回率

    简单策略：用标点切分做多角度检索
    进阶策略：用 LLM 改写生成 3 个变体（可后续优化）
    """
    # 基础：原始 query 必检索
    queries = [query]
    # 如果 query 包含标点，拆分子句
    import re
    parts = re.split(r'[，。！？；：、\n]', query)
    for part in parts:
        part = part.strip()
        if len(part) > 3 and part != query:
            queries.append(part)
    return queries[:3]  # 最多 3 个检索子句


def retrieve_with_rerank(
    query: str,
    course_id: str,
    top_k: int = None,
    score_threshold: float = None,
) -> list[dict]:
    """
    完整检索链路：Query 扩展 → 混合检索 → 合并去重 → 重排序
    """
    top_k = top_k or settings.retrieval_top_k
    score_threshold = score_threshold or settings.retrieval_score_threshold

    # 1. Query 扩展
    queries = expand_query(query)

    # 2. 每个子句独立检索
    all_results = {}
    for q in queries:
        results = hybrid_search(q, course_id, top_k=top_k, score_threshold=score_threshold)
        for r in results:
            # 用 chunk_id 去重，保留得分更高的
            cid = r["chunk_id"]
            if cid not in all_results or r["score"] > all_results[cid]["score"]:
                all_results[cid] = r

    documents = sorted(all_results.values(), key=lambda d: d["score"], reverse=True)

    # 3. 重排序
    documents = rerank(query, documents)

    return documents
