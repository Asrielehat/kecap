"""智能体编排 —— Plan-and-Execute（先规划再行动）

在现有 RAG 硬编码管线前加一层 AI 自主决策：
1. plan_question()  — LLM 产出执行计划（意图/检索关键词/技能/是否澄清）
2. resolve_skill()  — 技能决策（学习模式保底费曼 + 触发词兜底）
3. execute_plan()   — 按计划执行检索，生成执行轨迹
4. build_trace()    — 组装前端展示 + 存库的 execution_trace

任一步失败都安全回退到现有硬编码管线（retrieve_with_rerank），功能不回归。
"""

import json
import re

from app.core.config import get_settings
from app.rag.generator import llm_client
from app.rag.skills import load_skills, get_learning_skill, match_skill_by_trigger

settings = get_settings()

# ── 意图分类 ──
VALID_INTENTS = ("learning_plan", "concept", "factual", "clarification_needed", "casual")
INTENT_LABELS = {
    "learning_plan": "系统学习",
    "concept": "概念理解",
    "factual": "事实查询",
    "clarification_needed": "需要澄清",
    "casual": "闲聊",
}

DEFAULT_PLAN = {
    "intent": "factual",
    "search_queries": [],
    "skill": None,
    "clarification": None,
    "strategy": "",
}

PLANNER_SYSTEM_PROMPT = """你是"课答"智能体的规划器。学生发来一个问题，你需要判断怎么回答它最有效，产出一份**执行计划**。

## 学生的问题类型（intent）

- `learning_plan`：学生想系统学习一块内容（如"我想学XX""教我XX""从零开始学XX"）→ 多关键词检索 + 教学技能
- `concept`：学生想理解某个概念（如"什么是XX""XX怎么理解"）→ 检索 + 概念讲解技能
- `factual`：学生想查一个具体事实/做法 → 单关键词检索即可，一般不需要技能
- `clarification_needed`：问题太模糊，无法确定学生想问什么 → 需要先反问澄清
- `casual`：寒暄、闲聊（如"你好""谢谢""在吗"）→ 不需要检索

## 可用技能（可选，不强制用；没有合适的就填 null）

{skills_listing}

## 输出格式（严格 JSON，不要输出任何其他内容）

{{
  "intent": "learning_plan 或 concept 或 factual 或 clarification_needed 或 casual",
  "search_queries": ["关键词1", "关键词2"],
  "skill": "技能名 或 null",
  "clarification": "需要反问时的一句话，否则填 null",
  "strategy": "一句话说明回答策略"
}}

约束：
- search_queries：1~3 个检索关键词，最好和资料/课件主题相关；intent=casual 时可为空数组。
- skill：只能从「可用技能」里选，且只选一个最贴合的；没有合适的必须填 null。
- clarification：只有 intent=clarification_needed 时才填，其余情况必须 null。
"""


def _extract_json(content: str) -> dict | None:
    """从 LLM 输出中稳健提取 JSON 对象（容忍 markdown 代码围栏 / 前后缀 / 多段文本）"""
    if not content:
        return None
    # 1. 直接解析
    try:
        parsed = json.loads(content)
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        pass
    # 2. 去掉 ```json / ``` 代码围栏后再解析
    cleaned = re.sub(r"```(?:json)?", "", content).strip()
    try:
        parsed = json.loads(cleaned)
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        pass
    # 3. 提取第一个 {...} 对象
    m = re.search(r"\{.*\}", cleaned, re.S)
    if m:
        try:
            parsed = json.loads(m.group(0))
            return parsed if isinstance(parsed, dict) else None
        except Exception:
            pass
    return None


def _sanitize_plan(plan: dict, mode_skills: list[dict]) -> dict:
    """校验/规范化 planner 输出，防止 LLM 输出越界字段"""
    intent = plan.get("intent", "factual")
    if intent not in VALID_INTENTS:
        intent = "factual"

    queries = plan.get("search_queries") or []
    queries = [str(q).strip() for q in queries if str(q) and str(q).strip()][:3]

    skill = plan.get("skill")
    if skill:
        skill_names = {s["name"] for s in mode_skills}
        if skill not in skill_names:
            skill = None

    clarification = plan.get("clarification") or None
    strategy = str(plan.get("strategy") or "").strip()

    return {
        "intent": intent,
        "search_queries": queries,
        "skill": skill,
        "clarification": clarification,
        "strategy": strategy,
    }


def plan_question(
    question: str,
    history: list[dict] | None = None,
    mode: str = "query",
    skills: list[dict] | None = None,
) -> dict:
    """LLM 规划：产出执行计划。任何失败都回退默认计划（走现有检索路径）。"""
    skills = skills if skills is not None else load_skills()
    mode_skills = [s for s in skills if not s.get("modes") or mode in s["modes"]]
    if mode_skills:
        listing = "\n".join(f"- {s['name']}：{s['description']}" for s in mode_skills)
    else:
        listing = "（当前模式无可用技能）"

    system_prompt = PLANNER_SYSTEM_PROMPT.replace("{skills_listing}", listing)
    messages = [{"role": "system", "content": system_prompt}]
    if history:
        messages.extend(history[-6:])  # 最近几轮帮助判断意图
    messages.append({"role": "user", "content": question})

    try:
        response = llm_client.chat.completions.create(
            model=settings.agent_planner_model or settings.llm_model,
            messages=messages,
            temperature=settings.agent_planner_temperature,
            max_tokens=settings.agent_planner_max_tokens,
            response_format={"type": "json_object"},
        )
        content = response.choices[0].message.content or ""
        plan = _extract_json(content)
        if plan is None:
            raise ValueError("无法从 planner 输出中解析出 JSON")
        plan = _sanitize_plan(plan, mode_skills)
    except Exception as e:
        print(f"[Agent] 规划失败，回退默认计划: {e}", flush=True)
        plan = dict(DEFAULT_PLAN)

    # 学习意图兜底：问题命中学习触发词（"我想学/教我/怎么学"等）时，
    # 即使 planner 判成澄清/闲聊，也强制 learning_plan 并取消澄清——
    # 费曼技能会在教学流程内先了解情况，而不是用阻塞式反问挡在学生前面。
    if _is_learning_intent(question):
        plan["intent"] = "learning_plan"
        plan["clarification"] = None
    return plan


def _is_learning_intent(question: str) -> bool:
    """问题是否表达学习意图：命中主学习技能 description 里声明的触发词
    （「我想学」「教我」「怎么学」「从零」「想学」「学一下」「带我把」「过一遍」）。

    与 match_skill_by_trigger 的区别：这里不受模式门控限制——"我想学XX"在任何模式下
    都是学习意图，必须进入结构化教学，否则 query 模式会把"我想学第一周"当成普通总结。
    """
    ls = get_learning_skill()
    if not ls:
        return False
    for s in load_skills():
        if s["name"] == ls:
            for t in s.get("triggers", []):
                t = t.strip()
                if t and len(t) >= 2 and t in question:
                    return True
    return False


def resolve_skill(plan: dict, question: str, mode: str = "query") -> str | None:
    """技能决策（优先级从高到低）：
    0. 学习意图（intent=learning_plan 或问题命中学习触发词）→ 强制主学习技能，
       无视模式门控 —— 保证"我想学XX"在任何模式下都进入结构化教学（大纲+清单+逐节点推进），
       而"XX讲了什么"这类查询/概念问题不会被误套教学模板。
    1. 学习模式 → 强制主学习技能（费曼学习计划），保证学习模式风格稳定
    2. planner 选中的技能（须通过模式门控）
    3. 确定性触发词兜底
    """
    if plan and plan.get("intent") == "learning_plan":
        ls = get_learning_skill()
        if ls:
            return ls
    if _is_learning_intent(question):
        ls = get_learning_skill()
        if ls:
            return ls
    if mode == "learning":
        ls = get_learning_skill()
        if ls:
            return ls
    skill = plan.get("skill") if plan else None
    if skill:
        skills = load_skills()
        valid = [
            s for s in skills
            if s["name"] == skill and (not s.get("modes") or mode in s["modes"])
        ]
        if valid:
            return skill
    return match_skill_by_trigger(question, load_skills(), mode=mode)


def execute_plan(plan: dict, question: str, course_id: str, mode: str = "query") -> dict:
    """按计划执行检索 + 生成执行轨迹。

    返回 {retrieved_docs, steps}，其中 steps 为前端展示的轨迹（规划 + 检索两步）。
    检索失败/无关键词时回退 retrieve_with_rerank(question)，保证不空手回答。
    """
    from app.rag.retriever import retrieve_for_plan, retrieve_with_rerank

    steps = []
    queries = plan.get("search_queries") or []
    intent_label = INTENT_LABELS.get(plan.get("intent"), plan.get("intent") or "未知")
    strategy = plan.get("strategy") or ""
    steps.append({
        "tool": "plan",
        "label": "📋 规划",
        "detail": f"识别为「{intent_label}」意图" + (f"，策略：{strategy}" if strategy else ""),
    })

    if queries:
        try:
            retrieved_docs = retrieve_for_plan(queries, course_id, mode=mode)
        except Exception as e:
            print(f"[Agent] 计划检索失败，回退原问题检索: {e}", flush=True)
            retrieved_docs = retrieve_with_rerank(question, course_id, mode=mode)
    else:
        # 无关键词：回退按原问题检索（保证回答有依据）
        retrieved_docs = retrieve_with_rerank(question, course_id, mode=mode)

    steps.append({
        "tool": "retrieve",
        "label": "🔍 检索",
        "detail": f"关键词：{' · '.join(queries) if queries else '自动'}，命中 {len(retrieved_docs)} 段资料",
    })

    return {"retrieved_docs": retrieved_docs, "steps": steps}


def build_trace(plan: dict, steps: list[dict], skill: str | None = None) -> dict:
    """组装前端展示 + 存库的 execution_trace（含规划信息 + 实际执行的轨迹步骤）

    skill 为实际采用的技能名（学习模式保底 / 触发词兜底后），优先于 plan 里 planner 的初选。
    """
    return {
        "intent": plan.get("intent", ""),
        "search_queries": plan.get("search_queries") or [],
        "skill": skill if skill is not None else plan.get("skill"),
        "clarification": plan.get("clarification"),
        "strategy": plan.get("strategy", ""),
        "steps": steps,
    }
