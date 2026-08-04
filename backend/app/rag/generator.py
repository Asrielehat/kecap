"""LLM 答案生成 + 引文溯源"""

from openai import OpenAI
from app.core.config import get_settings
from app.rag.skills import load_skills, get_learning_skill

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

# ── 学习模式系统提示词 ──
LEARNING_SYSTEM_PROMPT = """你现在是一个叫"课答"的老师。你正在一对一教一个学生。

## 你的教学风格

你不是在"回答提问"，你是在"上课"。区别在于：回答提问是把信息丢给对方，上课是带着对方一步一步理解。

具体来说：
- 你关心学生是不是真的懂了，不是关心自己讲得全不全
- 你会在讲的过程中穿插提问，让学生思考，而不是一口气讲完
- 你会根据学生的反应调整节奏——他没跟上你就慢下来，他懂了你就往前走
- 你的语气是老师在跟学生说话，不是客服在回答用户问题

## 怎么教

**先搞清楚学生的情况**
如果学生的问题很模糊（比如"讲一下这门课"），先问他学到了哪、哪里不太懂，而不是直接开始从头讲。有针对性地教比全面覆盖有用得多。

**讲核心，不要铺开**
抓住最关键的 1-2 个点讲透。讲透的意思是：学生听完能用自己话说出来。

**用参考资料当教材，不要当答案**
参考资料是给你备课用的——你知道里面有什么。但你对学生是用你自己的话来讲，讲到相关内容时自然标上 [1] [2]。不要念资料。

**讲了就要检验**
每讲完一个要点，抛一个问题给学生。这个问题不是"你懂了吗"，而是需要他动脑子的——比如"那你觉得在这种情况呢？"或者"你用自己的话说说看？"

**问完就停，别自己回答**
你抛出的问题是留给学生想的，问完立刻停下来等学生回答。不要自己接着把答案讲出来，更不要把自己问过的问题复述一遍然后自己答。

**学生说"不知道"时**
学生回答"不知道""不会""没想法"这类话时，你可以把刚才那个问题的答案讲给他听——这是老师在答疑。但开头要说「那我来讲」或「老师来解答」，绝不能开口就是「好问题。你问的是...」或「你提出的问题是...」——那个问题是你自己问的，不是学生问的，不要把它说成学生的问题。

**学生说错了不要直接纠正**
如果他理解有偏差，先肯定他思路对的部分，再引导他发现问题所在。直接说"你错了"是最差的教法。

**偶尔让学生自己推导**
不是所有东西都需要你来讲。如果一个结论可以从前面的知识推导出来，让学生试试看。"根据刚才讲的，你觉得接下来会发生什么？"比直接给答案好。

## 长度

大多数时候 200-500 字就够了，因为你讲一段之后会提问、等学生回应。
不要一次性把所有东西倒出来——你是在上课，不是在写讲义。

## 禁止

- 不要用"核心结论""背景与动机""详细讲解"这类标题分段
- 不要说"同学，你好！"这类开场白，直接开始教
- 不要列 1、2、3、4 这种清单式结构
- 不要放"🔗 延伸思考"列表
- 不要在每句话后面都加引用——相关的自然标，不相关的不用硬标
- 不要念一遍参考资料就当教学

## 结尾格式

讲完之后如果需要列参考资料，一行 `📚 参考来源` 加列表即可。但这不重要——重要的是你最后留的那个问题，学生能不能接得住。
"""


def _build_skills_section(skills: list[dict], mode: str = "query", force_skills: list[str] | None = None) -> str:
    """把技能列表组织成注入文本 —— AI 根据问题自动触发合适的技能

    - 按模式门控：技能 frontmatter 声明了 mode 且不含当前模式 → 不注入（该模式下技能不可见）。
    - force_skills: 强制必须使用的技能名列表（学习模式下强制费曼 skill）。
      强制技能单独标注「必须使用」；学习模式下其余技能不再注入，避免 AI 风格摇摆。
    """
    skills = [s for s in skills if not s.get("modes") or mode in s["modes"]]
    if not skills:
        return ""
    force_names = set(force_skills or [])
    forced = [s for s in skills if s["name"] in force_names]
    normal = [s for s in skills if s["name"] not in force_names]
    if forced and mode == "learning":
        normal = []  # 学习模式只保留强制技能

    parts = []

    if forced:
        listing = "\n".join(
            f"- **{s['name']}**：{s['description']}" for s in forced
        )
        details = "\n\n---\n\n".join(
            f"### {s['name']}\n{s['instruction']}" for s in forced
        )
        parts.append(f"""## 必须使用的技能（本模式强制）

本模式下你必须使用以下技能，严格按其指令调整回答内容和风格。即使学生的问题没有直接提到技能名，也必须使用。

{listing}

使用该技能时，在回答末尾添加一行隐藏标记 `<!--skill:技能名-->`（技能名必须是上方列表里的精确名称，仅供系统记录，绝对不要显示给学生）。

## 技能详细指令

{details}
""")

    if normal:
        listing = "\n".join(
            f"- **{s['name']}**：{s['description']}" for s in normal
        )
        details = "\n\n---\n\n".join(
            f"### {s['name']}\n{s['instruction']}" for s in normal
        )
        parts.append(f"""## 可用技能（Skills）

本应用内置了以下技能。请先判断学生的问题是否命中某个技能的「触发词」或「触发场景」。

**命中规则**：如果学生的问题里出现了某个技能描述中的触发词（例如「费曼」「用费曼视角」「费曼学习法」），或者问题的性质明确符合某个技能描述的使用场景，那么**必须使用该技能**，严格按该技能的指令调整回答内容和风格。没有命中任何技能，就按正常方式回答，不要强行套用。

{listing}

**使用技能时**：在回答末尾添加一行隐藏标记 `<!--skill:技能名-->`（技能名必须是上方列表里的精确名称，仅供系统记录，绝对不要显示给学生）。未使用任何技能则不要添加该标记。

## 技能详细指令

{details}
""")

    return "\n\n---\n\n".join(parts)


def _get_skill(skill_name: str) -> dict | None:
    """按名字取单个技能（含 instruction）"""
    for s in load_skills():
        if s["name"] == skill_name:
            return s
    return None


def _build_mandatory_skill_section(skill: dict) -> str:
    """构建单个技能的强制使用指令段（智能体选定技能后注入）"""
    return f"""
## 必须使用的技能（本回答强制）

本回答必须使用技能「{skill['name']}」，严格按其指令调整回答内容和风格。

### {skill['name']}
{skill['instruction']}

使用该技能时，在回答末尾添加一行隐藏标记 `<!--skill:{skill['name']}-->`（仅供系统记录，绝对不要显示给学生）。
"""


def _append_skill_to_prompt(
    system_prompt: str,
    skill_name: str | None = None,
    mode: str = "query",
    inject_skill_list: bool = True,
) -> str:
    """向 system prompt 注入技能指令，三种情况：

    - skill_name 给定 → 只注入该技能（标注"必须使用"），智能体已决策
    - 否则 inject_skill_list=True → 注入当前模式可用技能列表（旧行为，AI 自选）
    - 否则 → 不注入任何技能（agent 模式且 planner 判定无需技能）
    """
    if skill_name:
        skill = _get_skill(skill_name)
        if skill:
            return system_prompt + _build_mandatory_skill_section(skill)
        return system_prompt
    if inject_skill_list:
        learning_skill = get_learning_skill() if mode == "learning" else None
        section = _build_skills_section(
            load_skills(), mode=mode,
            force_skills=[learning_skill] if learning_skill else [],
        )
        return system_prompt + section
    return system_prompt


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
    mode: str = "query",
    skill_name: str | None = None,
    inject_skill_list: bool = True,
) -> dict:
    """
    基于检索结果生成答案

    参数:
        question: 学生的问题
        retrieved_docs: 检索+重排序后的文档片段列表
        conversation_history: 可选的历史消息 [{role, content}, ...]
        mode: "learning" | "query" —— 选择 System Prompt 和 LLM 参数
        skill_name: 智能体选定的技能名，给定则只注入该技能（标注必须使用）
        inject_skill_list: 无 skill_name 时是否注入可用技能列表（旧行为）

    返回: {answer, citations, confidence}
    """
    preset = settings.rag_mode_presets.get(mode, settings.rag_mode_presets["query"])
    temperature = preset["temperature"]
    max_tokens = preset["max_tokens"]
    system_prompt = LEARNING_SYSTEM_PROMPT if mode == "learning" else SYSTEM_PROMPT
    system_prompt = _append_skill_to_prompt(
        system_prompt, skill_name=skill_name, mode=mode, inject_skill_list=inject_skill_list
    )

    # 计算整体置信度
    if retrieved_docs:
        scores = [d.get("rerank_score", d.get("score", 0)) for d in retrieved_docs]
        top_score = max(scores)
        avg_score = sum(scores) / len(scores)
        confidence = round(top_score * 0.7 + avg_score * 0.3, 4)
    else:
        confidence = 0.0

    # 构建消息
    messages = [{"role": "system", "content": system_prompt}]

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
        temperature=temperature,
        max_tokens=max_tokens,
    )

    answer = response.choices[0].message.content

    # 构建引文列表
    citations = []
    for i, doc in enumerate(retrieved_docs, start=1):
        citations.append({
            "text": doc["content"][:200] + ("..." if len(doc["content"]) > 200 else ""),
            "full_text": doc["content"],  # 完整原文，前端点击参考来源可查看
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
            "full_text": doc["content"],  # 完整原文，前端点击参考来源可查看
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
    mode: str = "query",
    skill_name: str | None = None,
    inject_skill_list: bool = True,
):
    """
    流式生成答案 —— 用于 SSE 推送到前端

    Yields: str (逐 token 输出)
    """
    preset = settings.rag_mode_presets.get(mode, settings.rag_mode_presets["query"])
    temperature = preset["temperature"]
    max_tokens = preset["max_tokens"]
    system_prompt = LEARNING_SYSTEM_PROMPT if mode == "learning" else SYSTEM_PROMPT
    system_prompt = _append_skill_to_prompt(
        system_prompt, skill_name=skill_name, mode=mode, inject_skill_list=inject_skill_list
    )

    messages = [{"role": "system", "content": system_prompt}]

    if conversation_history:
        messages.extend(conversation_history[-10:])

    user_prompt = build_prompt(question, retrieved_docs)
    messages.append({"role": "user", "content": user_prompt})

    stream = llm_client.chat.completions.create(
        model=settings.llm_model,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
        stream=True,
    )

    for chunk in stream:
        if chunk.choices[0].delta.content:
            yield chunk.choices[0].delta.content
