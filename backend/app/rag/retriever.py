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

    策略（v2）：动态阈值，而非固定数量
      1. 先归一化所有分数到 0~1 区间（兼容向量分数和 Cross-encoder 分数）
      2. 取第一名归一化分数为基准
      3. 归一化分数 ≥ 基准 × 50% 的全部保留
      4. 保底最少 3 条，上限 8 条
    """
    if not documents:
        return []

    min_count = top_k or settings.rerank_top_k  # 最少保留条数

    reranker = _get_reranker()
    if reranker:
        # Cross-encoder 精排
        pairs = [(query, d["content"][:512]) for d in documents]
        scores = reranker.predict(pairs)
        for d, score in zip(documents, scores):
            d["rerank_score"] = float(score)
        documents.sort(key=lambda d: d.get("rerank_score", 0), reverse=True)
    else:
        # 降级：按向量相似度排序
        documents.sort(key=lambda d: d.get("score", 0), reverse=True)

    # ── 提取有效分数并归一化到 0~1 ──
    raw_scores = [
        d.get("rerank_score") or d.get("score", 0)
        for d in documents
    ]
    min_s, max_s = min(raw_scores), max(raw_scores)
    if max_s > min_s:
        for d in documents:
            raw = d.get("rerank_score") or d.get("score", 0)
            d["_norm_score"] = (raw - min_s) / (max_s - min_s)
    else:
        # 所有分数一样，都归一化到 1.0
        for d in documents:
            d["_norm_score"] = 1.0

    print(f"[Reranker] 文档数={len(documents)} 分数范围={min_s:.4f}~{max_s:.4f} "
          f"reranker={'on' if reranker else 'off'}", flush=True)
    for i, d in enumerate(documents[:8]):
        print(f"  [{i+1}] norm={d['_norm_score']:.3f} raw={d.get('rerank_score') or d.get('score'):.4f} "
              f"src={d.get('document_name','?')[:30]}", flush=True)

    # ── 动态阈值截断（基于归一化分数）──
    threshold = documents[0]["_norm_score"] * 0.5

    selected = []
    for d in documents:
        if d["_norm_score"] >= threshold:
            selected.append(d)
        else:
            break

    if len(selected) < min_count:
        selected = documents[:min_count]
    if len(selected) > 8:
        selected = selected[:8]

    # 清理临时字段
    for d in documents:
        d.pop("_norm_score", None)

    print(f"[Reranker] 阈值={threshold:.3f} 选中={len(selected)}条", flush=True)
    return selected


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

    documents = sorted(all_results.values(), key=lambda d: d["score"], reverse=True)
    return documents[:5]


def retrieve_with_rerank(
    query: str,
    course_id: str,
    top_k: int = None,
    score_threshold: float = None,
    mode: str = "query",
) -> list[dict]:
    """
    完整检索链路：Query 扩展 → 混合检索 → 合并去重 → 重排序（动态阈值）

    mode="learning": 更低阈值、更多召回（5-8条）
    mode="query":   标准设置（3-8条动态）
    """
    preset = settings.rag_mode_presets.get(mode, settings.rag_mode_presets["query"])
    top_k = top_k or preset["retrieval_top_k"]
    score_threshold = score_threshold or preset["score_threshold"]

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

    # 3. 重排序（传入 mode 以使用对应的 rerank_min）
    documents = rerank(query, documents, top_k=preset["rerank_min"])

    return documents


def retrieve_for_plan(search_queries: list[str], course_id: str, mode: str = "query") -> list[dict]:
    """智能体计划检索 —— 按 planner 给出的多个关键词检索

    每个 query 调 hybrid_search，按 chunk_id 合并去重（保留高分），
    合并后 rerank() 一次 + 动态阈值（复用 retrieve_with_rerank 的预设参数）。
    """
    preset = settings.rag_mode_presets.get(mode, settings.rag_mode_presets["query"])
    top_k = preset["retrieval_top_k"]
    score_threshold = preset["score_threshold"]

    all_results = {}
    for q in search_queries:
        results = hybrid_search(q, course_id, top_k=top_k, score_threshold=score_threshold)
        for r in results:
            cid = r.get("chunk_id")
            if cid and (cid not in all_results or r["score"] > all_results[cid]["score"]):
                all_results[cid] = r

    documents = sorted(all_results.values(), key=lambda d: d["score"], reverse=True)
    if not documents:
        return []
    return rerank(search_queries[0], documents, top_k=preset["rerank_min"])
