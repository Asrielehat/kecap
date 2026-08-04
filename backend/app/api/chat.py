"""对话 API —— RAG 答疑接口"""

import json
import re
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.config import get_settings
from app.core.database import get_db
from app.models.db_models import Conversation, Message, Document, FollowUp, gen_uuid
from app.models.schemas import ChatRequest, ChatResponse, Citation, FollowUpRequest, FollowUpResponse, ExecutionTrace
from app.rag.retriever import retrieve_with_rerank, retrieve_follow_up
from app.rag.generator import generate_answer, generate_answer_stream, generate_follow_up
from app.rag.skills import load_skills, get_learning_skill, match_skill_by_trigger
from app.rag.agent import plan_question, resolve_skill, execute_plan, build_trace, DEFAULT_PLAN

settings = get_settings()

router = APIRouter(prefix="/api/chat", tags=["智能答疑"])


def extract_skill(answer: str) -> tuple[str | None, str]:
    """从回答中提取 <!--skill:xxx--> 标记，返回 (skill_name, 清理后的回答)"""
    m = re.search(r"<!--skill:\s*(.+?)\s*-->", answer)
    if m:
        return m.group(1).strip(), answer.replace(m.group(0), "").strip()
    return None, answer


def _run_agent(
    question: str,
    history: list[dict],
    mode: str,
    course_id: str,
) -> tuple[dict, str | None, list[dict], list[dict], str | None]:
    """智能体规划 + 执行。

    返回 (plan, skill_name, retrieved_docs, steps, clarification)：
    - plan: 执行计划（agent 关闭时用默认计划）
    - skill_name: 技能决策结果（学习模式保底费曼 + 触发词兜底）
    - retrieved_docs: 检索结果
    - steps: 执行轨迹（规划 + 检索）
    - clarification: 需要澄清时返回反问文本，否则 None

    agent_enabled=False 时完全走旧管线（按原问题检索、注入技能列表），功能不回归。
    """
    if not settings.agent_enabled:
        plan = dict(DEFAULT_PLAN)
        retrieved_docs = retrieve_with_rerank(question, course_id, mode=mode)
        return plan, resolve_skill(plan, question, mode), retrieved_docs, [], None

    plan = plan_question(question, history, mode=mode)
    if plan.get("clarification"):
        return plan, None, [], [], plan["clarification"]

    skill_name = resolve_skill(plan, question, mode)
    exec_result = execute_plan(plan, question, course_id, mode=mode)
    return plan, skill_name, exec_result["retrieved_docs"], exec_result["steps"], None


def _build_trace_steps(steps: list[dict], skill_name: str | None, num_docs: int) -> list[dict]:
    """在规划/检索轨迹后追加技能、生成两步，得到完整执行轨迹"""
    steps = list(steps)
    if skill_name:
        steps.append({"tool": "skill", "label": "🛠 技能", "detail": f"采用「{skill_name}」教学策略"})
    steps.append({"tool": "generate", "label": "✍️ 生成", "detail": f"基于 {num_docs} 段资料生成回答"})
    return steps


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

    # ── 智能体：规划 + 执行（回答前 AI 自主决策）──
    # 获取课程文档名映射
    docs_result = await db.execute(
        select(Document).where(Document.course_id == request.course_id)
    )
    docs = {d.id: d.filename for d in docs_result.scalars().all()}

    mode = request.mode.value if request.mode else "query"
    plan, skill_name, retrieved_docs, steps, clarification = _run_agent(
        request.question, conversation_history, mode, request.course_id,
    )
    for doc in retrieved_docs:
        doc["document_name"] = docs.get(doc["document_id"], "未知文档")

    # ── 保存用户消息 ──
    user_msg = Message(
        id=gen_uuid(),
        conversation_id=conversation.id,
        role="user",
        content=request.question,
    )
    db.add(user_msg)

    # ── 需要澄清：先反问，不生成回答 ──
    if clarification:
        trace_steps = [
            {"tool": "plan", "label": "📋 规划", "detail": "识别为「需要澄清」意图，信息不足"},
            {"tool": "clarify", "label": "💬 澄清", "detail": clarification},
        ]
        execution_trace = ExecutionTrace(**build_trace(plan, trace_steps, skill=None))
        assistant_msg = Message(
            id=gen_uuid(),
            conversation_id=conversation.id,
            role="assistant",
            content=clarification,
            citations=[],
            confidence=0.0,
            skill=None,
            execution_trace=execution_trace.model_dump(),
        )
        db.add(assistant_msg)
        await db.flush()
        return ChatResponse(
            answer=clarification,
            citations=[],
            conversation_id=conversation.id,
            assistant_message_id=assistant_msg.id,
            user_message_id=user_msg.id,
            confidence=0.0,
            skill=None,
            execution_trace=execution_trace,
        )

    # ── 生成答案（智能体已决策技能；非 agent 模式注入技能列表让 AI 自选）──
    result = generate_answer(
        request.question, retrieved_docs, conversation_history, mode=mode,
        skill_name=skill_name, inject_skill_list=not settings.agent_enabled,
    )
    extracted, clean_answer = extract_skill(result["answer"])
    if extracted:
        skill_name = extracted
    elif skill_name is None and mode == "learning":
        ls = get_learning_skill()
        if ls:
            skill_name = ls

    # ── 组装执行轨迹 ──
    execution_trace = None
    if settings.agent_enabled:
        full_steps = _build_trace_steps(steps, skill_name, len(retrieved_docs))
        execution_trace = ExecutionTrace(**build_trace(plan, full_steps, skill=skill_name))

    # ── 保存 AI 回复 ──
    assistant_msg = Message(
        id=gen_uuid(),
        conversation_id=conversation.id,
        role="assistant",
        content=clean_answer,
        citations=result["citations"],
        confidence=result["confidence"],
        skill=skill_name,  # 持久化技能名，重新加载对话时前端仍能显示
        execution_trace=execution_trace.model_dump() if execution_trace else None,
    )
    db.add(assistant_msg)
    await db.flush()

    # ── 构建引文响应 ──
    citations = [
        Citation(
            text=c["text"],
            full_text=c.get("full_text"),
            document_name=c["document_name"],
            page=c.get("page"),
            chunk_id=c["chunk_id"],
            score=c["score"],
        )
        for c in result["citations"]
    ]

    return ChatResponse(
        answer=clean_answer,
        citations=citations,
        conversation_id=conversation.id,
        assistant_message_id=assistant_msg.id,
        user_message_id=user_msg.id,
        confidence=result["confidence"],
        skill=skill_name,
        execution_trace=execution_trace,
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
            full_text=c.get("full_text"),
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

    # ── 智能体：规划 + 执行（回答前 AI 自主决策）──
    docs_result = await db.execute(
        select(Document).where(Document.course_id == request.course_id)
    )
    docs = {d.id: d.filename for d in docs_result.scalars().all()}
    mode = request.mode.value if request.mode else "query"
    plan, skill_name, retrieved_docs, steps, clarification = _run_agent(
        request.question, conversation_history, mode, request.course_id,
    )
    for doc in retrieved_docs:
        doc["document_name"] = docs.get(doc["document_id"], "未知文档")

    # ── 构建引文元数据（在流开始前发送）──
    citations_meta = [
        {
            "text": doc["content"][:200],
            "full_text": doc["content"],  # 完整原文，前端点击参考来源可查看
            "document_name": doc.get("document_name", "未知文档"),
            "page": doc.get("page_number"),
            "chunk_id": doc.get("chunk_id", ""),
            "score": doc.get("rerank_score", doc.get("score", 0)),
        }
        for doc in retrieved_docs
    ]

    # ── 组装执行轨迹（在流开始前完成）──
    execution_trace = None
    if settings.agent_enabled:
        if clarification:
            trace_steps = [
                {"tool": "plan", "label": "📋 规划", "detail": "识别为「需要澄清」意图，信息不足"},
                {"tool": "clarify", "label": "💬 澄清", "detail": clarification},
            ]
        else:
            trace_steps = _build_trace_steps(steps, skill_name, len(retrieved_docs))
        execution_trace = ExecutionTrace(**build_trace(plan, trace_steps, skill=skill_name))

    # ── 保存用户消息 ──
    user_msg = Message(
        id=gen_uuid(),
        conversation_id=conversation.id,
        role="user",
        content=request.question,
    )
    db.add(user_msg)
    # 提前提交，释放 SQLite 写锁：否则流式生成期间（可能几十秒）请求会话一直占锁，
    # event_stream 里第二个会话写入 AI 回复时会报 database is locked
    await db.commit()

    async def event_stream():
        # 先发送执行轨迹（智能体"想了什么、做了什么"）
        if execution_trace is not None:
            yield f"data: {json.dumps({'type': 'trace', 'data': execution_trace.model_dump()}, ensure_ascii=False)}\n\n"
        # 再发送引文元数据
        yield f"data: {json.dumps({'type': 'citations', 'data': citations_meta, 'conversation_id': conversation.id}, ensure_ascii=False)}\n\n"

        # 流式发送答案（澄清时直接整段返回反问）
        full_answer = ""
        try:
            if clarification:
                full_answer = clarification
                yield f"data: {json.dumps({'type': 'token', 'data': clarification}, ensure_ascii=False)}\n\n"
            else:
                for token in generate_answer_stream(
                    request.question, retrieved_docs, conversation_history, mode=mode,
                    skill_name=skill_name, inject_skill_list=not settings.agent_enabled,
                ):
                    full_answer += token
                    yield f"data: {json.dumps({'type': 'token', 'data': token}, ensure_ascii=False)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'data': str(e)}, ensure_ascii=False)}\n\n"

        # 技能标记（澄清时无技能）
        final_skill = skill_name
        clean_answer = full_answer
        if not clarification:
            extracted, clean_answer = extract_skill(full_answer)
            if extracted:
                final_skill = extracted
            elif final_skill is None and mode == "learning":
                ls = get_learning_skill()
                if ls:
                    final_skill = ls

        # 技能最终值同步进执行轨迹
        final_trace = execution_trace
        if final_trace is not None:
            trace_dict = final_trace.model_dump()
            trace_dict["skill"] = final_skill
            final_trace = ExecutionTrace(**trace_dict)

        # 保存 AI 回复到数据库
        async with async_session() as save_session:
            assistant_msg = Message(
                id=gen_uuid(),
                conversation_id=conversation.id,
                role="assistant",
                content=clean_answer,
                citations=citations_meta,
                confidence=(
                    sum(d.get("rerank_score", d.get("score", 0)) for d in retrieved_docs) / len(retrieved_docs)
                    if retrieved_docs else 0.0
                ),
                skill=final_skill,  # 持久化技能名，重新加载对话时前端仍能显示
                execution_trace=final_trace.model_dump() if final_trace else None,
            )
            save_session.add(assistant_msg)
            await save_session.commit()

        # 技能标记 + 结束信号
        yield f"data: {json.dumps({'type': 'skill', 'data': final_skill})}\n\n"
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
