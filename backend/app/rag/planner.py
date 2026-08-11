"""检索规划器 —— 把学生的问题拆成子问题，覆盖不同侧面

智能体流水线第 1 步：先"想清楚要查什么"，再逐个子问题检索。
拆解出的子问题各自独立、可直接用于课件检索；拆无可拆时退化为原问题单查询。
"""

import json
import re

from app.core.config import get_settings

settings = get_settings()

PLANNER_SYSTEM = (
    "你是'课答'智能体的检索规划器。学生问了一个问题，你要把它拆成最多 3 个"
    "能直接用于课件检索的子问题，覆盖问题的不同侧面（如：概念 / 原理 / 示例 / 对比 / 应用）。\n"
    "要求：\n"
    "1. 子问题相互独立，避免重复；\n"
    "2. 每个子问题必须自包含关键词，脱离上下文也能直接拿去搜课件；\n"
    "3. 如果问题本身很具体、拆无可拆，就返回只含原问题的一个数组。\n"
    "只返回 JSON 数组，不要任何解释、不要 markdown 代码块标记。\n"
    "示例：学生问'什么是词向量？' → [\"什么是词向量？\", \"词向量的作用和意义\", \"词向量与传统 One-Hot 编码的区别\"]"
)


def _parse_json_array(text: str) -> list[str]:
    """从 LLM 输出中鲁棒地提取 JSON 字符串数组（容忍代码块/前后废话）"""
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
    m = re.search(r"\[.*\]", text, re.DOTALL)
    if not m:
        return []
    try:
        data = json.loads(m.group(0))
        if isinstance(data, list):
            return [str(s).strip() for s in data if str(s).strip()]
    except json.JSONDecodeError:
        pass
    return []


def plan_sub_questions(question: str, llm_client, trace: list[dict] | None = None, max_subs: int = 3) -> list[str]:
    """把问题拆解成子问题；任何失败都安全回退为 [原问题]。

    trace（可选）：out-param，本函数不追加轨迹（由调用方统一加 plan 条目），
    避免与检索步骤的 step 编号冲突。
    """
    subs: list[str] = []
    try:
        resp = llm_client.chat.completions.create(
            model=settings.llm_model,
            messages=[
                {"role": "system", "content": PLANNER_SYSTEM},
                {"role": "user", "content": f"学生的问题：{question}"},
            ],
            temperature=0.3,
            max_tokens=400,
        )
        subs = _parse_json_array(resp.choices[0].message.content)
    except Exception as e:
        print(f"[Planner] 规划失败，回退单查询: {e}", flush=True)
        subs = []

    # 原问题永远保留为第一查询（保底覆盖主题），再补拆解出的子问题；去重 + 上限
    merged = [question]
    for s in subs:
        s = s.strip()
        if not s or s == question or s in merged or len(merged) >= max_subs:
            continue
        merged.append(s)
    if len(merged) > 1:
        print(f"[Planner] {len(merged)} 个子问题: {merged}", flush=True)
    return merged
