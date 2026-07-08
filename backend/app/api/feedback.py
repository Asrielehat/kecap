"""消息反馈 + 学情统计 API"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.models.db_models import Message, Conversation

router = APIRouter(prefix="/api/feedback", tags=["学习反馈"])


@router.post("/{message_id}")
async def set_feedback(
    message_id: str,
    feedback: str = "understood",
    db: AsyncSession = Depends(get_db),
):
    """对 AI 回复标记反馈"""
    if feedback not in ("understood", "confused", "reset"):
        raise HTTPException(status_code=400, detail="feedback 只能是 understood / confused / reset")

    result = await db.execute(
        select(Message).where(Message.id == message_id)
    )
    msg = result.scalar_one_or_none()
    if not msg:
        raise HTTPException(status_code=404, detail="消息不存在")

    msg.feedback = None if feedback == "reset" else feedback
    await db.flush()
    return {"ok": True, "message_id": message_id, "feedback": msg.feedback}


@router.get("/stats/{course_id}")
async def get_learning_stats(
    course_id: str,
    db: AsyncSession = Depends(get_db),
):
    """获取某课程的学情统计"""
    result = await db.execute(
        select(Message)
        .join(Conversation, Message.conversation_id == Conversation.id)
        .where(
            Conversation.course_id == course_id,
            Message.role == "assistant",
            Message.feedback.isnot(None),
        )
    )
    messages = result.scalars().all()

    understood = [m for m in messages if m.feedback == "understood"]
    confused = [m for m in messages if m.feedback == "confused"]

    async def get_topic(conv_id: str) -> str:
        conv_result = await db.execute(
            select(Conversation).where(Conversation.id == conv_id)
        )
        conv = conv_result.scalar_one_or_none()
        return conv.title if conv else "未知主题"

    items = []
    for m in confused:
        items.append({
            "message_id": m.id,
            "question": await get_topic(m.conversation_id),
            "feedback": "confused",
            "created_at": m.created_at.isoformat() if m.created_at else None,
        })

    for m in understood[-5:]:
        items.append({
            "message_id": m.id,
            "question": await get_topic(m.conversation_id),
            "feedback": "understood",
            "created_at": m.created_at.isoformat() if m.created_at else None,
        })

    return {
        "course_id": course_id,
        "total_feedback": len(messages),
        "understood_count": len(understood),
        "confused_count": len(confused),
        "items": sorted(items, key=lambda x: x["created_at"] or "", reverse=True),
    }
