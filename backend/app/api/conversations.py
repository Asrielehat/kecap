"""对话历史 API"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.models.db_models import Conversation, Message, FollowUp, gen_uuid

router = APIRouter(prefix="/api/conversations", tags=["对话历史"])


@router.get("/{course_id}")
async def list_conversations(course_id: str, db: AsyncSession = Depends(get_db)):
    """获取某课程下的所有对话列表"""
    result = await db.execute(
        select(Conversation)
        .where(Conversation.course_id == course_id)
        .order_by(Conversation.created_at.desc())
    )
    conversations = result.scalars().all()
    return [
        {
            "id": c.id,
            "course_id": c.course_id,
            "title": c.title,
            "created_at": c.created_at.isoformat() if c.created_at else None,
        }
        for c in conversations
    ]


@router.get("/{conversation_id}/messages")
async def get_messages(conversation_id: str, db: AsyncSession = Depends(get_db)):
    """获取某对话的所有消息"""
    # 验证对话存在
    result = await db.execute(
        select(Conversation).where(Conversation.id == conversation_id)
    )
    conversation = result.scalar_one_or_none()
    if not conversation:
        raise HTTPException(status_code=404, detail="对话不存在")

    # 获取消息
    result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.asc())
    )
    messages = result.scalars().all()

    return {
        "conversation_id": conversation_id,
        "course_id": conversation.course_id,
        "title": conversation.title,
        "messages": [
            {
                "id": m.id,
                "role": m.role,
                "content": m.content,
                "citations": m.citations,
                "confidence": m.confidence,
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in messages
        ],
    }


@router.delete("/{conversation_id}/messages/{message_id}")
async def delete_message(conversation_id: str, message_id: str, db: AsyncSession = Depends(get_db)):
    """删除对话中的单条消息（用户输错 / LLM 答偏时，防止污染后续上下文）

    连带删除挂在该消息上的追问记录（follow_ups.message_id 及 nested 子追问链）。
    """
    conv = await db.execute(select(Conversation).where(Conversation.id == conversation_id))
    if not conv.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="对话不存在")

    msg = await db.execute(
        select(Message).where(Message.id == message_id, Message.conversation_id == conversation_id)
    )
    message = msg.scalar_one_or_none()
    if not message:
        raise HTTPException(status_code=404, detail="消息不存在")

    # 收集并删除挂在被删消息上的整条追问链（message_id 直接挂 + parent_follow_up_id 级联）
    to_delete: set[str] = set()
    batch = [f.id for f in (await db.execute(select(FollowUp).where(FollowUp.message_id == message_id))).scalars().all()]
    while batch:
        to_delete.update(batch)
        batch = [f.id for f in (await db.execute(select(FollowUp).where(FollowUp.parent_follow_up_id.in_(batch)))).scalars().all()]
    if to_delete:
        await db.execute(delete(FollowUp).where(FollowUp.id.in_(to_delete)))

    await db.delete(message)
    await db.commit()
    return {"ok": True, "deleted": message_id}


@router.delete("/{conversation_id}")
async def delete_conversation(conversation_id: str, db: AsyncSession = Depends(get_db)):
    """删除对话及其所有消息"""
    result = await db.execute(
        select(Conversation).where(Conversation.id == conversation_id)
    )
    conversation = result.scalar_one_or_none()
    if not conversation:
        raise HTTPException(status_code=404, detail="对话不存在")

    await db.delete(conversation)
    return {"ok": True, "deleted": conversation_id}
