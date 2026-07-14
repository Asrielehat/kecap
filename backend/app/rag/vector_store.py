"""向量数据库操作 —— Qdrant

本地开发：文件模式（免 Docker）
Docker 部署：连接 Qdrant 容器
"""

import uuid
from pathlib import Path
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    VectorParams,
    PointStruct,
    Filter,
    FieldCondition,
    MatchValue,
)
from openai import OpenAI
from app.core.config import get_settings

settings = get_settings()

# ── 延迟初始化（避免模块导入时抢 Qdrant 文件锁）──
_qdrant_client = None
_embedding_client = None


def _get_qdrant() -> QdrantClient:
    global _qdrant_client
    if _qdrant_client is None:
        if settings.qdrant_url:
            # Docker 模式：连接 Qdrant 容器
            _qdrant_client = QdrantClient(url=settings.qdrant_url)
        else:
            # 本地模式：文件存储
            Path(settings.qdrant_path).mkdir(parents=True, exist_ok=True)
            _qdrant_client = QdrantClient(path=settings.qdrant_path)
    return _qdrant_client


def _get_embedding_client() -> OpenAI:
    global _embedding_client
    if _embedding_client is None:
        _embedding_client = OpenAI(
            api_key=settings.embedding_api_key,
            base_url=settings.embedding_base_url,
        )
    return _embedding_client


def ensure_collection():
    """确保向量集合存在，不存在则创建"""
    client = _get_qdrant()
    collections = client.get_collections()
    names = [c.name for c in collections.collections]
    if settings.qdrant_collection not in names:
        client.create_collection(
            collection_name=settings.qdrant_collection,
            vectors_config=VectorParams(
                size=settings.embedding_dim,
                distance=Distance.COSINE,
            ),
        )
        print(f"[VectorStore] 创建集合: {settings.qdrant_collection}")


def embed_texts(texts: list[str]) -> list[list[float]]:
    """批量文本向量化 —— 调用硅基流动 BGE-M3"""
    client = _get_embedding_client()
    resp = client.embeddings.create(
        model=settings.embedding_model,
        input=texts,
    )
    return [d.embedding for d in resp.data]


def get_search_client() -> QdrantClient:
    """获取 Qdrant 客户端（供 retriever 使用）"""
    return _get_qdrant()


def upsert_chunks(chunks: list[dict], course_id: str, document_id: str) -> int:
    """将分块文本向量化并存入 Qdrant"""
    client = _get_qdrant()
    ensure_collection()

    texts = [chunk["content"] for chunk in chunks]
    embeddings = embed_texts(texts)

    points = []
    for chunk, embedding in zip(chunks, embeddings):
        point_id = str(uuid.uuid4())
        chunk["qdrant_point_id"] = point_id
        points.append(PointStruct(
            id=point_id,
            vector=embedding,
            payload={
                "course_id": course_id,
                "document_id": document_id,
                "chunk_id": chunk["id"],
                "content": chunk["content"],
                "chunk_index": chunk["chunk_index"],
                "page_number": chunk.get("page_number"),
            },
        ))

    client.upsert(
        collection_name=settings.qdrant_collection,
        points=points,
    )
    return len(points)


def delete_document_vectors(document_id: str):
    """删除指定文档的所有向量"""
    client = _get_qdrant()
    client.delete(
        collection_name=settings.qdrant_collection,
        points_selector=Filter(
            must=[FieldCondition(key="document_id", match=MatchValue(value=document_id))]
        ),
    )
