"""Pydantic 数据模型 —— API 请求/响应"""

from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional
from enum import Enum


# ── 聊天模式 ──
class ChatMode(str, Enum):
    LEARNING = "learning"   # 学习模式：更细切分、更多参考、更详尽回答
    QUERY = "query"         # 询问模式：标准 RAG 答疑


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
    mode: ChatMode = Field(ChatMode.QUERY, description="聊天模式：learning=学习模式 query=询问模式")


class Citation(BaseModel):
    """引文溯源"""
    text: str = Field(..., description="引用原文片段（预览）")
    full_text: Optional[str] = Field(None, description="引用所在 chunk 的完整原文（前端点击查看）")
    document_name: str = Field(..., description="来源文档名")
    page: Optional[int] = Field(None, description="页码（适用于 PDF）")
    chunk_id: str = Field(..., description="数据库中的 chunk ID")
    score: float = Field(..., description="相关性得分")


class PlanStep(BaseModel):
    """智能体执行轨迹中的一步"""
    tool: str = Field(..., description="plan / retrieve / skill / generate")
    label: str = Field(..., description="步骤标题（含 emoji）")
    detail: str = Field(..., description="步骤说明")


class ExecutionTrace(BaseModel):
    """智能体执行轨迹 —— AI 的规划与执行过程（前端展示 + 存库）"""
    intent: str = Field(..., description="意图分类")
    search_queries: list[str] = []
    skill: Optional[str] = None
    clarification: Optional[str] = None
    strategy: str = ""
    steps: list[PlanStep] = []


class ChatResponse(BaseModel):
    answer: str
    citations: list[Citation] = []
    conversation_id: str
    assistant_message_id: str = ""
    user_message_id: Optional[str] = Field(None, description="本次提问在数据库中的消息 ID")
    confidence: float = Field(..., ge=0, le=1)
    skill: Optional[str] = Field(None, description="AI 本次回答使用的内置 skill 名称")
    execution_trace: Optional[ExecutionTrace] = Field(None, description="智能体执行轨迹（AI 的规划与执行过程）")


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
