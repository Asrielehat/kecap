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
                "skill": m.skill,
                "execution_trace": m.execution_trace,
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in messages
        ],
    }


@router.delete("/{conversation_id}")
async def delete_conversation(conversation_id: str, db: AsyncSession = Depends(get_db)):
    """删除对话及其所有消息"""
    result = await db.execute(
        select(Conversation).where(Conversation.id == conversation_id)
    )
    conversation = result.scalar_one_or_none()
    if not conversation:
        raise HTTPException(status_code=404, detail="对话不存在")

    # 手动清理追问记录：FollowUp 表没有定义级联关系，否则会留下孤儿数据
    await db.execute(
        delete(FollowUp).where(FollowUp.conversation_id == conversation_id)
    )
    # 消息通过 Conversation.messages 的 cascade="all, delete-orphan" 自动删除
    await db.delete(conversation)
    await db.flush()
    return {"ok": True, "deleted": conversation_id}


async def _delete_follow_ups_for_message(db: AsyncSession, message_id: str):
    """删除引用某消息的追问记录及其全部嵌套子追问"""
    children = (await db.execute(
        select(FollowUp.id).where(FollowUp.message_id == message_id)
    )).scalars().all()
    ids = list(children)
    while ids:
        await db.execute(delete(FollowUp).where(FollowUp.id.in_(ids)))
        ids = list((await db.execute(
            select(FollowUp.id).where(FollowUp.parent_follow_up_id.in_(ids))
        )).scalars().all())


@router.delete("/messages/{message_id}")
async def delete_message(message_id: str, db: AsyncSession = Depends(get_db)):
    """删除对话中的单条消息（及必要的关联），用于纠正对话上下文。

    - 删除 assistant 消息：只删这条回答（保留提问，方便重新问）
    - 删除 user 消息：连同紧随其后的 assistant 回答一起删（避免留下"没有提问的回答"）
    - 同步清理引用被删消息的追问记录（含嵌套子追问）
    """
    result = await db.execute(select(Message).where(Message.id == message_id))
    msg = result.scalar_one_or_none()
    if not msg:
        raise HTTPException(status_code=404, detail="消息不存在")

    deleted_ids = [msg.id]
    pair_id = None

    if msg.role == "user":
        # 找到紧随其后的 assistant 回答（按与前端一致的 created_at 正序）
        ordered_result = await db.execute(
            select(Message)
            .where(Message.conversation_id == msg.conversation_id)
            .order_by(Message.created_at.asc())
        )
        ordered = list(ordered_result.scalars().all())
        idx = next((i for i, m in enumerate(ordered) if m.id == msg.id), None)
        if idx is not None and idx + 1 < len(ordered) and ordered[idx + 1].role == "assistant":
            pair_id = ordered[idx + 1].id
            deleted_ids.append(pair_id)

    # 清理被删消息相关的追问记录
    for mid in (pair_id, msg.id):
        if mid:
            await _delete_follow_ups_for_message(db, mid)

    if pair_id:
        await db.execute(delete(Message).where(Message.id == pair_id))
    await db.delete(msg)
    await db.flush()
    return {"ok": True, "deleted": deleted_ids}
