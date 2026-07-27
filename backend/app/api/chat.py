"""对话 API —— RAG 答疑接口"""

import json
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.models.db_models import Conversation, Message, Document, FollowUp, gen_uuid
from app.models.schemas import ChatRequest, ChatResponse, Citation, FollowUpRequest, FollowUpResponse
from app.rag.retriever import retrieve_with_rerank, retrieve_follow_up
from app.rag.generator import generate_answer, generate_answer_stream, generate_follow_up

router = APIRouter(prefix="/api/chat", tags=["智能答疑"])


@router.post("/ask", response_model=ChatResponse)
async def ask(request: ChatRequest, db: AsyncSession = Depends(get_db)):
    """
    RAG 答疑 —— 完整检索链路

    1. Query 扩展 + 混合检索
    2. Cross-encoder 重排序
    3. LLM 基于检索片段生成答案（含溯源引用）
    4. 保存对话记录
    """

    # ── 获取或创建会话 ──
    if request.conversation_id:
        result = await db.execute(
            select(Conversation).where(Conversation.id == request.conversation_id)
        )
        conversation = result.scalar_one_or_none()
        if not conversation:
            raise HTTPException(status_code=404, detail="会话不存在")
    else:
        conversation = Conversation(
            id=gen_uuid(),
            course_id=request.course_id,
            title=request.question[:50] + ("..." if len(request.question) > 50 else ""),
        )
        db.add(conversation)
        await db.flush()

    # ── 获取历史消息（最近 5 轮）──
    history_result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conversation.id)
        .order_by(Message.created_at.desc())
        .limit(10)
    )
    history_messages = history_result.scalars().all()[::-1]  # 倒序恢复为时间正序
    conversation_history = [
        {"role": msg.role, "content": msg.content}
        for msg in history_messages
    ]

    # ── RAG 检索 + 重排序 ──
    # 获取课程文档名映射
    docs_result = await db.execute(
        select(Document).where(Document.course_id == request.course_id)
    )
    docs = {d.id: d.filename for d in docs_result.scalars().all()}

    retrieved_docs = retrieve_with_rerank(request.question, request.course_id)
    for doc in retrieved_docs:
        doc["document_name"] = docs.get(doc["document_id"], "未知文档")

    # ── 生成答案 ──
    result = generate_answer(
        request.question, retrieved_docs, conversation_history,
    )

    # ── 保存用户消息 ──
    user_msg = Message(
        id=gen_uuid(),
        conversation_id=conversation.id,
        role="user",
        content=request.question,
    )
    db.add(user_msg)

    # ── 保存 AI 回复 ──
    assistant_msg = Message(
        id=gen_uuid(),
        conversation_id=conversation.id,
        role="assistant",
        content=result["answer"],
        citations=result["citations"],
        confidence=result["confidence"],
    )
    db.add(assistant_msg)
    await db.flush()

    # ── 构建引文响应 ──
    citations = [
        Citation(
            text=c["text"],
            document_name=c["document_name"],
            page=c.get("page"),
            chunk_id=c["chunk_id"],
            score=c["score"],
        )
        for c in result["citations"]
    ]

    return ChatResponse(
        answer=result["answer"],
        citations=citations,
        conversation_id=conversation.id,
        assistant_message_id=assistant_msg.id,
        confidence=result["confidence"],
    )


@router.post("/follow-up", response_model=FollowUpResponse)
async def ask_follow_up(request: FollowUpRequest, db: AsyncSession = Depends(get_db)):
    """
    追问答疑 —— 上下文隔离的术语解释（支持嵌套追问链）

    顶层追问: message_id 指向主对话消息
    嵌套追问: parent_follow_up_id 指向父追问记录（追问弹窗里的追问）
    """
    # 校验：至少需要一个父引用
    if not request.message_id and not request.parent_follow_up_id:
        raise HTTPException(status_code=400, detail="message_id 或 parent_follow_up_id 至少需要一个")

    # 校验父引用存在
    if request.message_id:
        msg_result = await db.execute(select(Message).where(Message.id == request.message_id))
        if not msg_result.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="消息不存在")
    if request.parent_follow_up_id:
        fu_result = await db.execute(select(FollowUp).where(FollowUp.id == request.parent_follow_up_id))
        if not fu_result.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="父追问不存在")

    # 获取课程文档名映射
    docs_result = await db.execute(
        select(Document).where(Document.course_id == request.course_id)
    )
    docs = {d.id: d.filename for d in docs_result.scalars().all()}

    # 锚点检索
    retrieved_docs = retrieve_follow_up(
        request.selected_text,
        request.context_paragraph,
        request.course_id,
    )
    for doc in retrieved_docs:
        doc["document_name"] = docs.get(doc["document_id"], "未知文档")

    # 生成追问回答（上下文隔离，不读主对话历史）
    result = generate_follow_up(
        request.selected_text,
        request.context_paragraph,
        retrieved_docs,
    )

    # 写入 follow_ups 表（不写入 messages）
    fu = FollowUp(
        id=gen_uuid(),
        message_id=request.message_id if request.message_id else None,
        parent_follow_up_id=request.parent_follow_up_id if request.parent_follow_up_id else None,
        course_id=request.course_id,
        conversation_id=request.conversation_id,
        selected_text=request.selected_text,
        answer=result["answer"],
        citations=result["citations"],
    )
    db.add(fu)
    await db.flush()

    citations = [
        Citation(
            text=c["text"],
            document_name=c["document_name"],
            page=c.get("page"),
            chunk_id=c["chunk_id"],
            score=c["score"],
        )
        for c in result["citations"]
    ]

    return FollowUpResponse(
        id=fu.id,
        answer=result["answer"],
        citations=citations,
        message_id=request.message_id if request.message_id else None,
        parent_follow_up_id=request.parent_follow_up_id if request.parent_follow_up_id else None,
    )


@router.post("/ask/stream")
async def ask_stream(request: ChatRequest, db: AsyncSession = Depends(get_db)):
    """
    流式 RAG 答疑 —— SSE 逐字推送，体验更好
    """

    # ── 获取会话和历史消息（同上面非流式版本）──
    if request.conversation_id:
        result = await db.execute(
            select(Conversation).where(Conversation.id == request.conversation_id)
        )
        conversation = result.scalar_one_or_none()
        if not conversation:
            raise HTTPException(status_code=404, detail="会话不存在")
    else:
        conversation = Conversation(
            id=gen_uuid(),
            course_id=request.course_id,
            title=request.question[:50],
        )
        db.add(conversation)
        await db.flush()

    history_result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conversation.id)
        .order_by(Message.created_at.desc())
        .limit(10)
    )
    history_messages = history_result.scalars().all()[::-1]
    conversation_history = [
        {"role": msg.role, "content": msg.content}
        for msg in history_messages
    ]

    # ── 检索 ──
    docs_result = await db.execute(
        select(Document).where(Document.course_id == request.course_id)
    )
    docs = {d.id: d.filename for d in docs_result.scalars().all()}
    retrieved_docs = retrieve_with_rerank(request.question, request.course_id)
    for doc in retrieved_docs:
        doc["document_name"] = docs.get(doc["document_id"], "未知文档")

    # ── 构建引文元数据（在流开始前发送）──
    citations_meta = [
        {
            "text": doc["content"][:200],
            "document_name": doc.get("document_name", "未知文档"),
            "page": doc.get("page_number"),
            "chunk_id": doc.get("chunk_id", ""),
            "score": doc.get("rerank_score", doc.get("score", 0)),
        }
        for doc in retrieved_docs
    ]

    # ── 保存用户消息 ──
    user_msg = Message(
        id=gen_uuid(),
        conversation_id=conversation.id,
        role="user",
        content=request.question,
    )
    db.add(user_msg)
    await db.flush()

    async def event_stream():
        # 先发送引文元数据
        yield f"data: {json.dumps({'type': 'citations', 'data': citations_meta, 'conversation_id': conversation.id}, ensure_ascii=False)}\n\n"

        # 流式发送答案
        full_answer = ""
        try:
            for token in generate_answer_stream(request.question, retrieved_docs, conversation_history):
                full_answer += token
                yield f"data: {json.dumps({'type': 'token', 'data': token}, ensure_ascii=False)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'data': str(e)}, ensure_ascii=False)}\n\n"

        # 保存 AI 回复到数据库
        async with async_session() as save_session:
            assistant_msg = Message(
                id=gen_uuid(),
                conversation_id=conversation.id,
                role="assistant",
                content=full_answer,
                citations=citations_meta,
                confidence=(
                    sum(d.get("rerank_score", d.get("score", 0)) for d in retrieved_docs) / len(retrieved_docs)
                    if retrieved_docs else 0.0
                ),
            )
            save_session.add(assistant_msg)
            await save_session.commit()

        # 结束信号
        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# 需要在这里导入 async_session for stream saving
from app.core.database import async_session
