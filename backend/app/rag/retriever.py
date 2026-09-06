"""混合检索 + 重排序"""

import os
from typing import Optional
from qdrant_client import QdrantClient
from qdrant_client.models import Filter, FieldCondition, MatchValue
from app.core.config import get_settings
from app.rag.vector_store import embed_texts, get_search_client, vector_lock
from app.rag.lexical import bm25, reciprocal_rank_fusion
from app.core.work import checkpoint

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
    默认使用向量相似度召回；启用配置后增加 BM25 与 RRF 融合。

    返回: [{chunk_id, content, document_id, page_number, score, ...}, ...]
    """
    top_k = top_k or settings.retrieval_top_k
    score_threshold = settings.retrieval_score_threshold if score_threshold is None else score_threshold

    checkpoint()
    # Query 向量化
    query_embeddings = embed_texts([query])
    query_vector = query_embeddings[0]

    # 向量相似度检索 (Qdrant v1.18+ API)
    qdrant_client = get_search_client()
    with vector_lock:
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
    semantic = [
        {
            "chunk_id": hit.payload.get("chunk_id"),
            "qdrant_point_id": hit.id,
            "content": hit.payload.get("content", ""),
            "document_id": hit.payload.get("document_id"),
            "page_number": hit.payload.get("page_number"),
            "page_end": hit.payload.get("page_end"),
            "course_id": hit.payload.get("course_id"),
            "score": round(hit.score, 4),
        }
        for hit in scored_points
    ]
    if not settings.hybrid_retrieval_enabled:
        return semantic
    corpus, offset = [], None
    while True:
        checkpoint()
        with vector_lock:
            points, offset = qdrant_client.scroll(
                collection_name=settings.qdrant_collection,
                scroll_filter=Filter(must=[FieldCondition(key="course_id", match=MatchValue(value=course_id))]),
                limit=256, offset=offset, with_payload=True, with_vectors=False)
        corpus.extend({**p.payload, "qdrant_point_id": p.id} for p in points)
        if offset is None:
            break
    return reciprocal_rank_fusion(semantic, bm25(query, corpus, top_k), top_k=top_k)


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

    if settings.reranker_enabled:
        checkpoint()
        model = _get_reranker()
        if model is not None:
            scores = model.predict([(query, d["content"]) for d in documents])
            ranked = [{**doc, "rerank_score": float(score)} for doc, score in zip(documents, scores)]
            return sorted(ranked, key=lambda d: d["rerank_score"], reverse=True)[:top_k]
    return sorted(documents, key=lambda d: d.get("fusion_score", d.get("score", 0)), reverse=True)[:top_k]


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


def retrieve_follow_up(
    selected_text: str,
    context_paragraph: str,
    course_id: str,
) -> list[dict]:
    """
    追问锚点检索 —— 多 Query 并行 + 合并去重

    针对用户选中的文本，构建 3 个检索角度：
      1. 精准匹配选中文本
      2. 选中文本 + 原文上下文（扩展覆盖）
      3. 选中文本 + "的定义和解释"（概念导向）

    返回 Top-5（比主对话 Top-3 多，追问需要更广覆盖）
    """
    # 构建多角度 Query
    queries = [
        selected_text,
        selected_text + "\n\n" + context_paragraph[:200],
        selected_text + "的定义和解释",
    ]

    # 去重（因为 3 个 query 可能返回相同结果）
    seen = set()
    unique_queries = []
    for q in queries:
        if q not in seen:
            seen.add(q)
            unique_queries.append(q)

    # 并行检索 + 按 chunk_id 合并
    all_results = {}
    for q in unique_queries:
        results = hybrid_search(q, course_id, top_k=10, score_threshold=0.3)
        for r in results:
            cid = r.get("chunk_id", r.get("id"))
            if cid not in all_results or r["score"] > all_results[cid]["score"]:
                all_results[cid] = r

    documents = sorted(all_results.values(), key=lambda d: d.get("fusion_score", d["score"]), reverse=True)
    return documents[:5]


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
    score_threshold = settings.retrieval_score_threshold if score_threshold is None else score_threshold

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

    documents = sorted(all_results.values(), key=lambda d: d.get("fusion_score", d["score"]), reverse=True)

    # 3. 重排序
    documents = rerank(query, documents)

    return documents
