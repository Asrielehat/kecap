"""检索智能体 —— LLM 自主决定检索，多轮换词重查，收集完整 docs 供 generate_answer

方案 A（检索循环 + 生成分离）：本模块的 agent loop 只负责"决定查什么、查几次"，
把多轮检索到的完整 docs（按 chunk_id 去重）交给主生成器 generate_answer 作答，
引文 / 置信度逻辑不动。复用 app.mcp.agent.run_tool_rounds 这个通用循环，
把 search_knowledge_base 作为 in-process 工具注入（与 MCP fetch 共用同一 loop）。
"""

from app.core.config import get_settings
from app.rag.retriever import retrieve_with_rerank
from app.mcp.agent import run_tool_rounds

settings = get_settings()

# 检索决策专用系统提示：只决策检索，不负责写最终答案（作答由主生成器负责）
RETRIEVAL_TOOL_SYSTEM = (
    "你是'课答'的检索决策器。你的任务是通过调用工具获取回答学生问题所需的课件资料。\n"
    "1. 需要课件资料时调用 search_knowledge_base，query 要具体、贴合课件术语；\n"
    "2. 返回结果与问题不相关或信息不足时，换更准确的关键词再次检索；\n"
    "3. 信息已足够时，直接回复'检索完成'，不要作答（作答由主生成器负责）。"
)

# search_knowledge_base 工具的 OpenAI function calling schema
search_knowledge_base_schema = {
    "name": "search_knowledge_base",
    "description": "在当前课程的课件资料库中检索相关知识点片段，返回 Top-K 个最相关文本及其来源。"
                   "当问题涉及课件内容、需要依据课程资料回答、或需要查证概念时使用。"
                   "返回结果与问题不相关时，可换更准确的关键词再次检索。",
    "parameters": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "检索词或问题，要具体、贴合课件术语"},
            "top_k": {"type": "integer", "description": "返回片段数，默认 3，话题宽泛时可取 5"},
        },
        "required": ["query"],
    },
}

# 回填给决策 LLM 的每段检索结果摘要上限（字符）
_DIGEST_PER_DOC_CHARS = 800


def run_retrieval_agent(
    question: str,
    llm_client,
    course_id: str,
    *,
    max_steps: int | None = None,
    trace: list[dict] | None = None,
) -> list[dict]:
    """多轮自主检索，返回按 chunk_id 去重后的完整 docs 列表（供 generate_answer 使用）。

    决策 LLM 通过 function calling 决定检索词与轮次；本函数只收集 docs，不产答案。
    返回空列表时，调用方（chat.py）会兜底走硬编码 retrieve_with_rerank。
    trace（可选）：out-param 就地追加检索轮次轨迹，供前端"思考过程"面板展示。
    """
    collector: list[dict] = []
    seen: set[str] = set()

    def search(query: str, top_k: int = 3):
        docs = retrieve_with_rerank(query, course_id, top_k=top_k)
        for d in docs:                      # 跨轮去重，保留第一命中
            if d["chunk_id"] not in seen:
                seen.add(d["chunk_id"])
                collector.append(d)
        print(f"[Agent] 检索: query={query[:60]} top_k={top_k} hits={len(docs)}", flush=True)
        if trace is not None:
            trace.append({
                "step": len(trace) + 1,
                "type": "retrieval",
                "query": query,
                "top_k": top_k,
                "hits": len(docs),
                "scores": [d.get("score") for d in docs],
                "preview": (docs[0]["content"][:60] + "…") if docs else "",
                # 完整检索文本：前端展开后展示 LLM 实际读到的内容
                "content": "\n\n---\n\n".join(d["content"] for d in docs),
            })
        # 喂回给决策 LLM 的紧凑摘要（截断防 token 膨胀），is_error=False
        digest = "\n".join(
            f"- [score {d.get('score')}] {d['content'][:_DIGEST_PER_DOC_CHARS]}" for d in docs
        )
        return digest, False

    tools = [{"type": "function", "function": search_knowledge_base_schema}]
    messages = [
        {"role": "system", "content": RETRIEVAL_TOOL_SYSTEM},
        {"role": "user", "content": question},
    ]

    run_tool_rounds(
        messages,
        llm_client,
        tools=tools,
        executor={"search_knowledge_base": lambda name, args: search(**args)},
        max_steps=max_steps or settings.agent_max_steps,
        tool_max_tokens=settings.agent_tool_max_tokens,
        tool_max_chars=settings.agent_tool_result_max_chars,
        system_prompt=RETRIEVAL_TOOL_SYSTEM,
        label="Agent",
    )
    return collector
