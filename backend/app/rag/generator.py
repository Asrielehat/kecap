"""LLM 答案生成 + 引文溯源"""

from openai import OpenAI
from app.core.config import get_settings

settings = get_settings()

# ── LLM 客户端（兼容 OpenAI SDK 格式） ──
llm_client = OpenAI(
    api_key=settings.llm_api_key,
    base_url=settings.llm_base_url,
)

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


def build_prompt(question: str, retrieved_docs: list[dict]) -> str:
    """构建带检索上下文的 prompt"""
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


def generate_answer(
    question: str,
    retrieved_docs: list[dict],
    conversation_history: list[dict] = None,
) -> dict:
    """
    基于检索结果生成答案

    参数:
        question: 学生的问题
        retrieved_docs: 检索+重排序后的文档片段列表
        conversation_history: 可选的历史消息 [{role, content}, ...]

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

    # 构建消息
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    # 加入历史对话（最近 10 条）
    if conversation_history:
        messages.extend(conversation_history[-10:])

    # 构建含检索上下文的用户消息
    user_prompt = build_prompt(question, retrieved_docs)
    messages.append({"role": "user", "content": user_prompt})

    # 调用 LLM
    response = llm_client.chat.completions.create(
        model=settings.llm_model,
        messages=messages,
        temperature=settings.llm_temperature,
        max_tokens=settings.llm_max_tokens,
    )

    answer = response.choices[0].message.content

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


def generate_follow_up(
    selected_text: str,
    context_paragraph: str,
    retrieved_docs: list[dict],
) -> dict:
    """
    追问答案生成 —— 上下文隔离，不读取主对话历史

    参数:
        selected_text: 用户选中的文字
        context_paragraph: 选中文字所在的完整段落
        retrieved_docs: 锚点检索返回的文档片段列表

    返回: {answer, citations}
    """
    # 构建带检索上下文的用户消息
    context_parts = []
    for i, doc in enumerate(retrieved_docs, start=1):
        source = doc.get("document_name", "未知文档")
        page = doc.get("page_number", "")
        page_str = f"，第{page}页" if page else ""
        context_parts.append(
            f"[{i}]【来源: {source}{page_str}】\n{doc['content']}"
        )

    context = "\n\n---\n\n".join(context_parts) if context_parts else "（课件中未找到相关内容）"

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
        {"role": "system", "content": FOLLOW_UP_PROMPT},
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
):
    """
    流式生成答案 —— 用于 SSE 推送到前端

    Yields: str (逐 token 输出)
    """
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    if conversation_history:
        messages.extend(conversation_history[-10:])

    user_prompt = build_prompt(question, retrieved_docs)
    messages.append({"role": "user", "content": user_prompt})

    stream = llm_client.chat.completions.create(
        model=settings.llm_model,
        messages=messages,
        temperature=settings.llm_temperature,
        max_tokens=settings.llm_max_tokens,
        stream=True,
    )

    for chunk in stream:
        if chunk.choices[0].delta.content:
            yield chunk.choices[0].delta.content
