"""LLM 答案生成 + 引文溯源"""

import json
import re
import time

from openai import OpenAI
from app.core.config import get_settings

settings = get_settings()

# ── LLM 客户端（兼容 OpenAI SDK 格式） ──
llm_client = OpenAI(
    api_key=settings.llm_api_key,
    base_url=settings.llm_base_url,
)


def _read_reasoning(delta) -> str:
    """从流式 delta 读取 DeepSeek 推理链（reasoning_content）。

    不同 OpenAI SDK 版本下该字段可能位于 delta.reasoning_content 或 model_extra。
    """
    v = getattr(delta, "reasoning_content", None)
    if v:
        return v
    return (getattr(delta, "model_extra", None) or {}).get("reasoning_content") or ""

# ── 系统提示词 ──
SYSTEM_PROMPT = """你是一个专业的 AI 学业辅导助手"课答"。你的任务是基于课程资料和你的知识储备，准确、详细地回答学生的问题。

## 核心规则

1. **资料优先**：首先查找「参考资料」中是否有相关信息。有的话优先基于资料回答，句末标注引用编号 [1]、[2]。
2. **智能补充**：如果资料内容不够详细、缺少背景原理、举例或推导过程，你可以用自己的知识自然地进行补充和展开。补充时不要生硬地加标签，自然地融入到回答中即可。
3. **资料完全不相关时**：如果所有参考资料都与问题无关，就直接用自己的知识回答，像普通 AI 助手一样。不要生硬地说"未找到相关内容"然后什么都不答。
4. **标注清晰**：来自资料的内容标注引用编号 [1]、[2]；用自己的知识补充的部分不需要特别标注，自然叙述即可。
5. **回答方式**：先给结论再解释原因。涉及公式或算法的给出推导步骤。适当举例、类比、对比帮助理解。避免只给干巴巴的结论。
6. **回答结尾**：在答案末尾列出「📚 参考来源」清单，格式为：[编号] 文档名 (页码/位置)。如果完全没有用到资料（即纯通用知识回答），可以不列。

## 回答示例

学生问：二叉树有哪三种遍历方式？

你的回答（假设资料中有相关内容，编号 [1]）：
---
二叉树的三种遍历方式分别为：前序遍历、中序遍历和后序遍历 [1]。

- **前序遍历**（根→左→右）：先访问根节点，再递归遍历左子树，最后递归遍历右子树 [1]。
- **中序遍历**（左→根→右）：先递归遍历左子树，再访问根节点，最后递归遍历右子树。对于二叉搜索树，中序遍历可以得到有序序列 [1]。
- **后序遍历**（左→右→根）：先递归遍历左子树，再递归遍历右子树，最后访问根节点 [1]。

这三种遍历方式都属于深度优先搜索，时间复杂度都是 O(n)，其中 n 是节点数。实际应用中，前序常用于复制树结构，中序用于输出排序结果，后序常用于删除树（先删子节点再删父节点）。

📚 **参考来源**
[1] 《数据结构（C语言版）》 第5章 树与二叉树, P.125-128
---
"""


def build_prompt(question: str, retrieved_docs: list[dict], include_context: bool = True) -> str:
    """构建带检索上下文的 prompt"""
    if not include_context:
        # 全历史总结类技能：不注入检索上下文，避免"参考资料"与技能指令冲突
        return f"## 学生的问题\n\n{question}\n\n请基于提供的对话历史进行总结，不要标注引用编号。"
    context_parts = []
    for i, doc in enumerate(retrieved_docs, start=1):
        source = doc.get("document_name", "未知文档")
        page = doc.get("page_number", "")
        page_str = f", 第{page}页" if page else ""
        context_parts.append(
            f"[{i}] 【来源: {source}{page_str}】\n{doc['content']}"
        )

    context = "\n\n---\n\n".join(context_parts)

    prompt = f"""## 参考资料

{context}

---

## 学生的问题

{question}

---

请优先基于上述参考资料回答。资料有的就引用标注 [编号]，资料不够详细的地方用自己的知识自然补充，资料完全不相关就直接用通用知识回答。"""
    return prompt


def _fit_full_history(history: list[dict], max_chars: int) -> list[dict]:
    """完整历史超长时，从最旧的开始裁剪，保住最近的内容（防止超 token）"""
    if sum(len(m.get("content", "")) for m in history) <= max_chars:
        return history
    kept: list[dict] = []
    total = 0
    for m in reversed(history):          # 从最新往前累加
        c = m.get("content", "")
        room = max_chars - total
        if len(c) > room:
            if room > 50:
                kept.append({**m, "content": "…" + c[-room:]})  # 最旧一条仅保留尾部
            break
        kept.append(m)
        total += len(c)
    return list(reversed(kept))


def generate_answer(
    question: str,
    retrieved_docs: list[dict],
    conversation_history: list[dict] = None,
    mode: str = "all",                 # 学习模式（query/learning/all），技能系统据此触发必触发技能
    trace: list[dict] | None = None,   # out-param：MCP 工具调用轨迹，供前端"思考过程"面板展示
) -> dict:
    """
    基于检索结果生成答案

    参数:
        question: 学生的问题
        retrieved_docs: 检索+重排序后的文档片段列表
        conversation_history: 可选的历史消息 [{role, content}, ...]
        trace: 可选轨迹列表，MCP 增强执行工具轮次时就地追加

    返回: {answer, citations, confidence}
    """
    # 计算整体置信度
    if retrieved_docs:
        scores = [d.get("rerank_score", d.get("score", 0)) for d in retrieved_docs]
        top_score = max(scores)
        avg_score = sum(scores) / len(scores)
        confidence = round(top_score * 0.7 + avg_score * 0.3, 4)
    else:
        confidence = 0.0

    # ── 技能解析（可选增强，默认关闭；与 MCP 同模式的懒导入 + 安全回退）──
    skill = None
    use_full_history = False
    if settings.skills_enabled:
        try:
            from app.skills.loader import resolve_skill   # 懒导入，技能系统不可用时不影响主链路
            skill = resolve_skill(question, mode)
        except Exception as e:
            print(f"[Skill] 技能匹配失败，回退纯 RAG: {e}", flush=True)
        if skill:
            use_full_history = bool(getattr(skill, "needs_full_history", False))
            print(f"[Skill] 命中技能: {skill.name} (needs_full_history={use_full_history})", flush=True)

    # 构建消息
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    # 历史：全历史技能不截断（超长再按字符裁剪），否则保持最近 10 条
    if conversation_history:
        if use_full_history:
            messages.extend(_fit_full_history(conversation_history, settings.skills_max_history_chars))
        else:
            messages.extend(conversation_history[-10:])

    # 用户消息：全历史技能不走检索上下文
    user_prompt = build_prompt(question, retrieved_docs, include_context=not use_full_history)
    messages.append({"role": "user", "content": user_prompt})

    # 技能指令注入：作为独立 system 消息插在系统提示词之后、历史之前（覆盖式指导，越靠后越强）
    if skill:
        messages.insert(1, {"role": "system", "content": skill.instruction})

    # ── MCP 工具增强（可选）：放在技能之后，工具决策轮也能看到技能上下文 ──
    agent_answer: str | None = None
    if settings.mcp_enabled:
        try:
            from app.mcp.agent import enhance_with_tools   # 懒导入，未装 mcp 包也不报错
            messages, agent_answer = enhance_with_tools(messages, llm_client=llm_client, trace=trace)
        except Exception as e:
            print(f"[MCP] 工具增强不可用，回退纯 RAG: {e}", flush=True)

    if agent_answer and len(agent_answer.strip()) >= 20:
        # 智能体已自行作答：工具轮次中模型直接给出结论，不再二次调用（agent 闭环）
        print(f"[Generator] 智能体直接作答 {len(agent_answer)} 字符（跳过二次生成）", flush=True)
        answer = agent_answer
    else:
        # 回退单次生成：智能体未直接作答 / MCP 未启用
        response = llm_client.chat.completions.create(
            model=settings.llm_model,
            messages=messages,
            temperature=settings.llm_temperature,
            max_tokens=settings.llm_max_tokens,
        )
        answer = response.choices[0].message.content

    # ── 智能体流水线最后一步：答案自检（对照参考资料质检，跑偏/漏点/有错就重写）──
    if settings.answer_selfcheck_enabled:
        answer, revised = self_check_answer(question, retrieved_docs, answer, llm_client)
        print(f"[SelfCheck] 自检{'已修正' if revised else '通过'}（{len(answer or '')} 字符）", flush=True)
        if trace is not None:
            trace.append({
                "step": len(trace) + 1, "type": "selfcheck",
                "note": "对照参考资料质检：" + ("发现偏差，已重写为修正版" if revised else "通过"),
            })

    # 构建引文列表
    citations = []
    for i, doc in enumerate(retrieved_docs, start=1):
        citations.append({
            "text": doc["content"][:200] + ("..." if len(doc["content"]) > 200 else ""),
            "document_name": doc.get("document_name", "未知文档"),
            "page": doc.get("page_number"),
            "chunk_id": doc.get("chunk_id", ""),
            "score": doc.get("rerank_score", doc.get("score", 0)),
        })

    return {
        "answer": answer,
        "citations": citations,
        "confidence": confidence,
    }


# ── 追问专用 System Prompt（四段式：定义→联系原文→举例→关联）──
FOLLOW_UP_PROMPT = """你是一个耐心的学业辅导老师。学生正在阅读 AI 的回答时，对其中的一个术语或表述产生了疑问，选中了一段文字来向你追问。

## 你的任务

用尽可能通俗易懂的方式解释学生选中的术语。按以下四段结构组织回答：

**【定义】** 先用一句话直接解释这个术语是什么。不要兜圈子。

**【联系原文】** 说明这个术语在原文语境中为什么出现、起什么作用。

**【举例】** 给一个具体、简单的例子。越具体越好，让学生看完就能自己复述。

**【补充】** 如果课件里还有相关概念，简要提一句，供学生进一步了解。

## 原则

- 假设学生对当前术语是完全陌生的，从零开始解释
- 优先基于参考资料回答，参考资料的引用标注 [1]、[2]
- 如果参考资料中没有相关内容，用自己的知识回答，但在末尾注明「注：以上解释来自通用知识，课件中未直接涉及此术语」
- 答案控制在 500 字以内，精炼但完整
- 回答结尾列出「参考来源」清单（如有）"""

# ── 追问对话框专用 System Prompt（回答用户的具体问题，而非固定四段式）──
FOLLOW_UP_QUESTION_PROMPT = """你是一个耐心的学业辅导老师。学生正在阅读 AI 的回答，他选中了其中一段文字，并基于这段文字提出了一个更具体的问题。

## 你的任务

围绕学生选中的文字，直接、准确地回答他提出的问题。回答要针对问题本身，不要答非所问，也不要泛泛地重复解释术语。

## 回答要求

1. 结论先行：先用一两句话直接给出问题的答案，再展开解释或推导。
2. 紧扣选中文字和原文语境作答，不要跑题。
3. 参考资料中有相关内容时，优先基于资料回答，并在句末标注引用编号 [1]、[2]。
4. 参考资料不足时，用自己的知识自然补充，不要生硬地说"资料里没有"。
5. 涉及公式、算法、推导时，给出关键步骤；适当举例或类比帮助理解。
6. 如果此前对话框已讨论过相关问题，可以在新回答里自然衔接，不必重复全部旧内容。

## 原则

- 答案控制在 600 字以内，精炼但完整
- 回答结尾列出「参考来源」清单（如有）"""


# ── 答案自检（智能体流水线最后一步）──
SELFCHECK_SYSTEM = (
    "你是'课答'智能体的答案质检员。学生会给你问题、参考资料和 AI 生成的答案，你要检查：\n"
    "1. 是否答非所问 / 跑题；\n"
    "2. 参考资料中明确有的关键点是否被遗漏；\n"
    "3. 是否存在事实错误、或与参考资料矛盾的内容。\n"
    "只返回 JSON，不要任何解释：{\"verdict\": \"ok\" 或 \"revise\", \"revised\": \"修正后的完整答案\"}\n"
    "- verdict 为 \"ok\" 时，revised 给空字符串；\n"
    "- verdict 为 \"revise\" 时，revised 必须是覆盖原答案的完整修正版，不要只写修改意见。"
)


def _extract_json_object(text: str) -> dict | None:
    """鲁棒提取 LLM 输出里的 JSON 对象（容忍代码块 / 前后废话）"""
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def self_check_answer(
    question: str,
    retrieved_docs: list[dict],
    answer: str,
    llm_client,
) -> tuple[str, bool]:
    """答案自检：对照参考资料质检，发现跑题 / 漏关键点 / 事实错误就重写为修正版。

    返回 (final_answer, revised)。任何一步失败都保留原答案（安全回退）。
    """
    try:
        context = "\n\n---\n\n".join(
            f"[{i}] 【来源: {d.get('document_name', '未知文档')}】\n{(d.get('content') or '')[:800]}"
            for i, d in enumerate(retrieved_docs[:5], start=1)
        ) or "（无参考资料）"
        resp = llm_client.chat.completions.create(
            model=settings.llm_model,
            messages=[
                {"role": "system", "content": SELFCHECK_SYSTEM},
                {"role": "user", "content": (
                    f"## 学生的问题\n{question}\n\n"
                    f"## 参考资料\n{context}\n\n"
                    f"## AI 生成的答案\n{(answer or '')[:3000]}"
                )},
            ],
            temperature=0.3,
            max_tokens=max(settings.llm_max_tokens, 2048),
        )
        data = _extract_json_object(resp.choices[0].message.content)
        if data and data.get("verdict") == "revise":
            revised = (data.get("revised") or "").strip()
            if len(revised) >= 20 and revised != (answer or "").strip():
                return revised, True
    except Exception as e:
        print(f"[SelfCheck] 质检失败，保留原答案: {e}", flush=True)
    return answer, False


def _build_follow_up_context(retrieved_docs: list[dict]) -> str:
    """从检索片段构建「参考资料」块，两种追问 prompt 共用"""
    context_parts = []
    for i, doc in enumerate(retrieved_docs, start=1):
        source = doc.get("document_name", "未知文档")
        page = doc.get("page_number", "")
        page_str = f"，第{page}页" if page else ""
        context_parts.append(
            f"[{i}]【来源: {source}{page_str}】\n{doc['content']}"
        )
    return "\n\n---\n\n".join(context_parts) if context_parts else "（课件中未找到相关内容）"


def generate_follow_up(
    selected_text: str,
    context_paragraph: str,
    retrieved_docs: list[dict],
    question: str | None = None,
    history: list[dict] | None = None,
) -> dict:
    """
    追问答案生成 —— 上下文隔离，不读取主对话历史

    参数:
        selected_text: 用户选中的文字
        context_paragraph: 选中文字所在的完整段落
        retrieved_docs: 锚点检索返回的文档片段列表
        question: 用户在追问对话框内输入的具体问题（None = 原四段式自动解释）
        history: 该对话框此前的问答轮次 [{question?, answer}, ...]，帮助理解承接式提问

    返回: {answer, citations}
    """
    context = _build_follow_up_context(retrieved_docs)

    # 此前对话框问答（紧凑：最近 ≤10 轮、每轮截断，防止 prompt 膨胀）
    history_block = ""
    if history:
        lines = []
        for h in history[-10:]:
            q = (h.get("question") or "").strip()
            a = (h.get("answer") or "").strip()
            if q:
                lines.append(f"问：{q[:300]}")
            if a:
                lines.append(f"答：{a[:500]}")
        if lines:
            history_block = "\n\n## 此前在该对话框中的问答\n\n" + "\n".join(lines)

    if question:
        system_prompt = FOLLOW_UP_QUESTION_PROMPT
        user_message = f"""## 参考资料

{context}

---

## 学生选中的文字

"{selected_text}"

## 选中文字所在的原文语境

{context_paragraph}
{history_block}

---

## 学生的问题

{question}

请围绕选中的文字，直接回答这个问题。"""
    else:
        system_prompt = FOLLOW_UP_PROMPT
        user_message = f"""## 参考资料

{context}

---

## 学生选中的文字

"{selected_text}"

## 选中文字所在的原文语境

{context_paragraph}

---

请按四段式（定义 → 联系原文 → 举例 → 补充）解释以上术语。"""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message},
    ]

    response = llm_client.chat.completions.create(
        model=settings.llm_model,
        messages=messages,
        temperature=0.15,      # 低温度：定义解释追求准确而非创意
        max_tokens=800,         # 追问精炼，500 字以内
    )

    answer = response.choices[0].message.content

    citations = []
    for i, doc in enumerate(retrieved_docs, start=1):
        citations.append({
            "text": doc["content"][:200] + ("..." if len(doc["content"]) > 200 else ""),
            "document_name": doc.get("document_name", "未知文档"),
            "page": doc.get("page_number"),
            "chunk_id": doc.get("chunk_id", ""),
            "score": doc.get("score", 0),
        })

    return {"answer": answer, "citations": citations}


def generate_answer_stream(
    question: str,
    retrieved_docs: list[dict],
    conversation_history: list[dict] = None,
    mode: str = "all",                 # 学习模式（query/learning/all），技能系统据此触发必触发技能
    trace: list[dict] | None = None,   # out-param：MCP 工具调用轨迹（订阅后实时推送每步）
):
    """
    流式生成答案 —— 用于 SSE 推送到前端

    与 generate_answer 一致：技能解析 + MCP 工具增强（trace 就地追加 tool 条目），
    最后流式调用 LLM。开启深度思考时，先用思考模型实时流式返回推理链
    （reasoning），再流式返回答案正文（token）。

    Yields: tuple[str, str] —— ("reasoning", 推理链增量) 或 ("token", 答案增量)
    """
    # ── 技能解析（与 generate_answer 一致；懒导入 + 安全回退）──
    skill = None
    use_full_history = False
    if settings.skills_enabled:
        try:
            from app.skills.loader import resolve_skill
            skill = resolve_skill(question, mode)
        except Exception as e:
            print(f"[Skill] 技能匹配失败，回退纯 RAG: {e}", flush=True)
        if skill:
            use_full_history = bool(getattr(skill, "needs_full_history", False))

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    # 历史：全历史技能不截断（超长再按字符裁剪），否则保持最近 10 条
    if conversation_history:
        if use_full_history:
            messages.extend(_fit_full_history(conversation_history, settings.skills_max_history_chars))
        else:
            messages.extend(conversation_history[-10:])

    user_prompt = build_prompt(question, retrieved_docs, include_context=not use_full_history)
    messages.append({"role": "user", "content": user_prompt})

    # 技能指令注入（插在系统提示词之后、历史之前）
    if skill:
        messages.insert(1, {"role": "system", "content": skill.instruction})

    # ── MCP 工具增强（可选）：与 generate_answer 一致，工具决策轮能看到技能上下文 ──
    agent_answer: str | None = None
    if settings.mcp_enabled:
        try:
            from app.mcp.agent import enhance_with_tools   # 懒导入，未装 mcp 包也不报错
            messages, agent_answer = enhance_with_tools(messages, llm_client=llm_client, trace=trace)
        except Exception as e:
            print(f"[MCP] 工具增强不可用，回退纯 RAG: {e}", flush=True)

    # ── 得到完整答案（自检需对照全文，故先生成完整版再流式输出）──
    if agent_answer and len(agent_answer.strip()) >= 20:
        # 智能体已自行作答：工具轮次中模型直接给出结论，不再二次调用（agent 闭环）
        print(f"[Generator] 智能体直接作答 {len(agent_answer)} 字符（跳过二次生成）", flush=True)
        answer = agent_answer
    elif settings.llm_thinking_enabled:
        # 深度思考：流式调用思考模型，推理链实时推、正文缓冲后自检再重放
        try:
            stream = llm_client.chat.completions.create(
                model=settings.llm_thinking_model,
                messages=messages,
                temperature=settings.llm_temperature,
                max_tokens=settings.llm_thinking_max_tokens,
                stream=True,
                extra_body={"thinking_mode": settings.llm_thinking_mode},
            )
            parts: list[str] = []
            for chunk in stream:
                delta = chunk.choices[0].delta
                r = _read_reasoning(delta)
                if r:
                    yield ("reasoning", r)
                if delta.content:
                    parts.append(delta.content)
            answer = "".join(parts)
        except Exception as e:
            print(f"[Thinking] 深度思考失败，回退纯 RAG 生成: {e}", flush=True)
            answer = ""
        # 思考模型偶尔只输出推理链而无正文（被截断），回退非思考模型补正文
        if not answer.strip():
            response = llm_client.chat.completions.create(
                model=settings.llm_model,
                messages=messages,
                temperature=settings.llm_temperature,
                max_tokens=settings.llm_max_tokens,
            )
            answer = response.choices[0].message.content or ""
    elif settings.answer_selfcheck_enabled:
        # 自检需对照全文，先非流式取全文再质检
        response = llm_client.chat.completions.create(
            model=settings.llm_model,
            messages=messages,
            temperature=settings.llm_temperature,
            max_tokens=settings.llm_max_tokens,
        )
        answer = response.choices[0].message.content or ""
    else:
        # 未启用自检：保持真流式（逐 token 直达）
        stream = llm_client.chat.completions.create(
            model=settings.llm_model,
            messages=messages,
            temperature=settings.llm_temperature,
            max_tokens=settings.llm_max_tokens,
            stream=True,
        )
        for chunk in stream:
            if chunk.choices[0].delta.content:
                yield ("token", chunk.choices[0].delta.content)
        return

    # ── 智能体流水线最后一步：答案自检 ──
    if settings.answer_selfcheck_enabled:
        answer, revised = self_check_answer(question, retrieved_docs, answer, llm_client)
        print(f"[SelfCheck] 自检{'已修正' if revised else '通过'}（{len(answer or '')} 字符）", flush=True)
        if trace is not None:
            trace.append({
                "step": len(trace) + 1, "type": "selfcheck",
                "note": "对照参考资料质检：" + ("发现偏差，已重写为修正版" if revised else "通过"),
            })

    # 逐小段流式输出最终答案，保持"逐字流式"观感（思考过程已实时展示）
    for i in range(0, len(answer or ""), 3):
        yield ("token", (answer or "")[i:i + 3])
        time.sleep(0.015)
