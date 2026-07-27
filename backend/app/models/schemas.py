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


class FollowUpRequest(BaseModel):
    """追问请求 —— 上下文隔离，不影响主对话。支持嵌套追问链"""
    selected_text: str = Field(..., min_length=1, max_length=800, description="用户选中的文字")
    context_paragraph: str = Field(..., min_length=1, max_length=2000, description="选中文字所在的段落")
    message_id: Optional[str] = Field(None, description="主对话中被追问的消息 ID（顶层追问）")
    parent_follow_up_id: Optional[str] = Field(None, description="嵌套追问：父追问记录 ID（追问弹窗里的追问）")
    course_id: str = Field(..., description="课程 ID")
    conversation_id: str = Field(..., description="主会话 ID")


class FollowUpResponse(BaseModel):
    id: str
    answer: str
    citations: list[Citation] = []
    message_id: Optional[str] = None
    parent_follow_up_id: Optional[str] = None
