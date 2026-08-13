"""对话 API —— RAG 答疑接口"""

import asyncio
import json
import threading
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.core.config import get_settings
from app.core.trace import TraceRecorder
from app.models.db_models import Conversation, Message, Document, FollowUp, gen_uuid
from app.models.schemas import ChatRequest, ChatResponse, Citation, FollowUpRequest, FollowUpResponse
from app.rag.retriever import retrieve_with_rerank, retrieve_follow_up
from app.rag.generator import generate_answer, generate_answer_stream, generate_follow_up, llm_client

router = APIRouter(prefix="/api/chat", tags=["智能答疑"])

settings = get_settings()


def _retrieve_docs(
    question: str, course_id: str, needs_full: bool, trace: list[dict] | None = None
) -> list[dict]:
    """检索决策：全历史技能→不检索；agent 开启→LLM 自主多轮检索（查不到则兜底硬编码）；否则单次检索。

    trace（可选）：out-param，检索智能体每轮检索 / 兜底情况就地追加轨迹条目。
    """
    if needs_full:
        return []
    if settings.agent_planning_enabled:
        # 智能体流水线第 1 步：规划拆解 → 逐子问题检索 → 合并去重（覆盖不同侧面）
        from app.rag.planner import plan_sub_questions   # 懒导入，规划失败不影响主链路
        sub_questions = plan_sub_questions(question, llm_client, trace=trace)
        if trace is not None:
            trace.append({
                "step": len(trace) + 1, "type": "plan",
                "sub_questions": sub_questions,
                "note": f"问题拆解为 {len(sub_questions)} 个子问题",
            })
        best: dict[str, dict] = {}
        for sq in sub_questions:
            hits = retrieve_with_rerank(sq, course_id)
            if trace is not None:
                trace.append({
                    "step": len(trace) + 1, "type": "retrieval",
                    "query": sq, "hits": len(hits),
                })
            for d in hits:
                cid = d.get("chunk_id", d.get("id"))
                if not cid:
                    continue
                if cid not in best or d["score"] > best[cid]["score"]:
                    best[cid] = d
        docs = sorted(best.values(), key=lambda d: d["score"], reverse=True)
        return docs[: settings.retrieval_top_k]
    if settings.agent_retrieval_enabled:
        from app.rag.agent import run_retrieval_agent   # 懒导入，检索智能体不可用时不影响主链路
        docs = run_retrieval_agent(question, llm_client, course_id, trace=trace)
        if not docs:
            if trace is not None:
                trace.append({
                    "step": len(trace) + 1, "type": "fallback", "query": question,
                    "note": "检索智能体未命中，回退单次检索",
                })
            docs = retrieve_with_rerank(question, course_id)   # 兜底：LLM 没查 / 没查到
        return docs
    return retrieve_with_rerank(question, course_id)


# 典型追问开头：单独看没有主题，检索时必须带上上一轮用户问题才不会跑偏
_FOLLOWUP_STARTERS = (
    "为什么", "那", "那么", "再", "继续", "接着", "换个", "换种", "换个角度",
    "还有", "用", "举", "它", "这个", "这样", "所以",
)


def _build_retrieval_question(question: str, history: list[dict]) -> str:
    """模糊追问时，用上一轮用户问题做主题锚点，避免检索跑偏到无关课件章节。

    例：上一问"什么是词向量"，当前问"用不同的例子解释一下"
      → 锚定后检索词 "什么是词向量 | 用不同的例子解释一下"
    新主题的完整提问（如"解释一下什么是死锁"）自身带主题词，不锚定。
    """
    q = question.strip()
    if not q or not history:
        return question
    last_user = next((m["content"] for m in reversed(history) if m.get("role") == "user"), None)
    if not last_user or not last_user.strip():
        return question
    short = len(q) <= 6
    vague_start = any(q.startswith(s) for s in _FOLLOWUP_STARTERS)
    if short or vague_start:
        return f"{last_user.strip()} | {q}"
    return question


async def fetch_conversation_messages(
    conversation_id: str, db: AsyncSession, limit: int | None = None
) -> list[dict]:
    """查询某对话的消息（时间正序），返回 [{role, content}, ...]。

    limit 语义：取"最近 limit 条"（先 DESC LIMIT 再反转为正序）；limit=None 取全部。
    """
    if limit is not None:
        q = (select(Message)
             .where(Message.conversation_id == conversation_id)
             .order_by(Message.created_at.desc())
             .limit(limit))
        result = await db.execute(q)
        rows = list(result.scalars().all())[::-1]
    else:
        q = (select(Message)
             .where(Message.conversation_id == conversation_id)
             .order_by(Message.created_at.asc()))
        result = await db.execute(q)
        rows = result.scalars().all()
    return [{"role": m.role, "content": m.content} for m in rows]


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

    # ── 技能解析（可选增强，默认关闭；决定是否需要完整历史 / 跳过检索）──
    skill = None
    needs_full = False
    if settings.skills_enabled:
        try:
            from app.skills.loader import resolve_skill
            skill = resolve_skill(request.question, request.mode)
        except Exception as e:
            print(f"[Skill] 技能匹配失败，忽略: {e}", flush=True)
    needs_full = bool(skill and getattr(skill, "needs_full_history", False))
    if skill:
        print(f"[Skill] 命中技能: {skill.name} (needs_full_history={needs_full})", flush=True)

    # ── 获取历史消息 ──
    if needs_full:
        # 完整历史：该对话全部消息（不限于最近 10 条）
        conversation_history = await fetch_conversation_messages(conversation.id, db)
    else:
        # 最近 10 条
        conversation_history = await fetch_conversation_messages(conversation.id, db, limit=10)

    # 模糊追问锚定上一轮用户问题：避免"用不同的例子解释一下"这类短问把检索带偏到别的章节
    retrieval_question = _build_retrieval_question(request.question, conversation_history)

    # ── RAG 检索（全历史技能基于对话历史总结，跳过文档检索）──
    trace: list[dict] = []   # Agent 运行轨迹（检索轮次 / MCP 工具调用），供前端"思考过程"面板
    if needs_full:
        retrieved_docs = []
    else:
        # 获取课程文档名映射
        docs_result = await db.execute(
            select(Document).where(Document.course_id == request.course_id)
        )
        docs = {d.id: d.filename for d in docs_result.scalars().all()}

        # 检索：agent 开启时由 LLM 自主多轮检索（换词重查），否则硬编码单次检索
        retrieved_docs = _retrieve_docs(retrieval_question, request.course_id, needs_full, trace)
        for doc in retrieved_docs:
            doc["document_name"] = docs.get(doc["document_id"], "未知文档")

    # ── 生成答案（透传 mode；MCP 工具调用轨迹追加进 trace）──
    result = generate_answer(
        request.question, retrieved_docs, conversation_history, mode=request.mode, trace=trace,
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
        agent_trace=trace or None,
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
        request.question,
        request.history,
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
        question=request.question,
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

    # ── 技能解析（可选增强，默认关闭）──
    skill = None
    needs_full = False
    if settings.skills_enabled:
        try:
            from app.skills.loader import resolve_skill
            skill = resolve_skill(request.question, request.mode)
        except Exception as e:
            print(f"[Skill] 技能匹配失败，忽略: {e}", flush=True)
    needs_full = bool(skill and getattr(skill, "needs_full_history", False))

    # ── 历史消息 ──
    if needs_full:
        conversation_history = await fetch_conversation_messages(conversation.id, db)
    else:
        conversation_history = await fetch_conversation_messages(conversation.id, db, limit=10)

    # 模糊追问锚定上一轮用户问题：避免"用不同的例子解释一下"这类短问把检索带偏到别的章节
    retrieval_question = _build_retrieval_question(request.question, conversation_history)

    # ── 文档名映射（全历史技能跳过）──
    docs_map: dict[str, str] = {}
    if not needs_full:
        docs_result = await db.execute(
            select(Document).where(Document.course_id == request.course_id)
        )
        docs_map = {d.id: d.filename for d in docs_result.scalars().all()}

    # ── 保存用户消息 ──
    user_msg = Message(
        id=gen_uuid(),
        conversation_id=conversation.id,
        role="user",
        content=request.question,
    )
    db.add(user_msg)
    # 提交请求会话：流式期间 get_db 的 yield 依赖要到响应体消费完才退出，
    # 若不先 commit，事件循环里保存回复的新会话会撞上 SQLite 单写锁（database is locked）
    await db.commit()

    # ── 实时轨迹通道：阻塞的检索+生成跑工作线程 → asyncio.Queue → SSE ──
    queue: asyncio.Queue = asyncio.Queue()
    trace = TraceRecorder()
    loop = asyncio.get_running_loop()

    def push(kind: str, payload):
        # asyncio.Queue 非线程安全，跨线程写入必须回到事件循环线程
        loop.call_soon_threadsafe(queue.put_nowait, (kind, payload))

    # 每完成一轮检索/工具调用，trace.append 即实时推给 SSE
    trace.listen(lambda step: push("trace", step))

    def run_pipeline():
        """工作线程：检索 + 生成答案，逐步 push 到队列（不阻塞事件循环）"""
        try:
            # 检索：agent 开启时逐轮实时推 trace（换词重查）
            docs = _retrieve_docs(retrieval_question, request.course_id, needs_full, trace)
            for doc in docs:
                doc["document_name"] = docs_map.get(doc["document_id"], "未知文档")

            # 置信度（同 generate_answer 公式）
            if docs:
                scores = [d.get("rerank_score", d.get("score", 0)) for d in docs]
                confidence = round(max(scores) * 0.7 + (sum(scores) / len(scores)) * 0.3, 4)
            else:
                confidence = 0.0

            # 引文元数据（答案流开始前发）
            citations_meta = [
                {
                    "text": doc["content"][:200],
                    "document_name": doc.get("document_name", "未知文档"),
                    "page": doc.get("page_number"),
                    "chunk_id": doc.get("chunk_id", ""),
                    "score": doc.get("rerank_score", doc.get("score", 0)),
                }
                for doc in docs
            ]
            push("citations", {
                "citations": citations_meta,
                "conversation_id": conversation.id,
                "confidence": confidence,
                # 刚保存的 user 消息 id：前端据此能删除刚发错的输入
                "user_message_id": user_msg.id,
            })

            # 答案：MCP 工具轮次实时推 trace，推理链(reasoning)/答案(token) 实时推
            for kind, text in generate_answer_stream(
                request.question, docs, conversation_history, mode=request.mode, trace=trace,
            ):
                push(kind, text)
        except Exception as e:
            print(f"[ask_stream] 流水线失败: {e}", flush=True)
            push("error", str(e))
        finally:
            push("end", None)

    threading.Thread(target=run_pipeline, daemon=True).start()

    async def event_stream():
        full_answer = ""
        citations_meta: list[dict] = []
        confidence = 0.0
        try:
            while True:
                kind, payload = await queue.get()
                if kind == "trace":
                    yield f"data: {json.dumps({'type': 'trace', 'data': payload}, ensure_ascii=False)}\n\n"
                elif kind == "citations":
                    citations_meta = payload["citations"]
                    confidence = payload.get("confidence", 0.0)
                    yield f"data: {json.dumps({'type': 'citations', 'data': citations_meta, 'conversation_id': payload['conversation_id'], 'user_message_id': payload.get('user_message_id')}, ensure_ascii=False)}\n\n"
                elif kind == "reasoning":
                    # 深度思考推理链：仅实时转发，不并入答案正文、不落库
                    yield f"data: {json.dumps({'type': 'reasoning', 'data': payload}, ensure_ascii=False)}\n\n"
                elif kind == "token":
                    full_answer += payload
                    yield f"data: {json.dumps({'type': 'token', 'data': payload}, ensure_ascii=False)}\n\n"
                elif kind == "error":
                    yield f"data: {json.dumps({'type': 'error', 'data': payload}, ensure_ascii=False)}\n\n"
                    break
                elif kind == "end":
                    break
        finally:
            # 出错/中断也保存已产生的部分答案
            try:
                async with async_session() as save_session:
                    assistant_msg = Message(
                        id=gen_uuid(),
                        conversation_id=conversation.id,
                        role="assistant",
                        content=full_answer,
                        citations=citations_meta,
                        confidence=confidence,
                    )
                    save_session.add(assistant_msg)
                    await save_session.commit()
                    saved_id = assistant_msg.id
            except Exception as e:
                print(f"[ask_stream] 保存回复失败: {e}", flush=True)
                saved_id = ""
        # 结束信号（携带 assistant_message_id 供前端反馈定位）
        yield f"data: {json.dumps({'type': 'done', 'data': {'assistant_message_id': saved_id}}, ensure_ascii=False)}\n\n"

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
