"""Pydantic 数据模型 —— API 请求/响应"""

from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional


# ── 文档上传 ──
class DocumentUploadResponse(BaseModel):
    document_id: str
    filename: str
    chunk_count: int
    status: str


# ── 聊天 ──
class ChatRequest(BaseModel):
    course_id: str = Field(..., description="课程 ID，用于限定检索范围")
    question: str = Field(..., min_length=1, max_length=2000)
    conversation_id: Optional[str] = Field(None, description="会话 ID，用于多轮对话")


class Citation(BaseModel):
    """引文溯源"""
    text: str = Field(..., description="引用原文片段")
    document_name: str = Field(..., description="来源文档名")
    page: Optional[int] = Field(None, description="页码（适用于 PDF）")
    chunk_id: str = Field(..., description="数据库中的 chunk ID")
    score: float = Field(..., description="相关性得分")


class ChatResponse(BaseModel):
    answer: str
    citations: list[Citation] = []
    conversation_id: str
    assistant_message_id: str = ""
    confidence: float = Field(..., ge=0, le=1)


# ── 课程 ──
class CourseCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = None


class CourseResponse(BaseModel):
    id: str
    name: str
    description: Optional[str]
    document_count: int
    chunk_count: int
    created_at: datetime
