"""最小 agent loop —— LLM 通过 function calling 调用 MCP 工具（如 fetch 抓网页）

与 generator.py 解耦：不 import generator，LLM 客户端通过参数注入，避免循环导入。
任一环节失败都返回原始 messages（安全回退纯 RAG），保证主链路不回归。
"""

import json

from app.core.config import get_settings
from app.core.work import checkpoint
from app.mcp.client import mcp_manager

settings = get_settings()

# 工具轮次专用系统提示：告诉 LLM 它可以通过调用工具补充信息
TOOL_ROUND_SYSTEM = (
    "你是'课答'智能体的工具决策器。你可以调用提供的工具获取额外信息（如抓取网页）。"
    "只有当问题需要实时/外部信息、或现有上下文不足时，才调用工具；"
    "调用工具后，等工具结果返回再决定下一步。"
    "当已有信息足够时，请**直接作答**：写出一份可直接展示给学生的完整答案，"
    "遵循消息中主系统提示的格式要求（分点、标注来源）。"
    "不要回复'好的''已了解''检索完成'等空话；能答就答，答不了才继续调工具。"
)


def run_tool_rounds(
    messages: list[dict],
    llm_client,
    *,
    tools: list[dict] | None = None,
    executor: dict | None = None,
    max_steps: int | None = None,
    tool_max_tokens: int | None = None,
    tool_max_chars: int | None = None,
    system_prompt: str | None = None,
    label: str = "MCP",
    trace: list[dict] | None = None,
) -> tuple[list[dict], str | None]:
    """通用 agent loop —— LLM 选择工具 → 执行 → 回填 role=tool 结果，循环最多 max_steps 轮。

    tools / executor 均为 None 时走 MCP 工具来源（保持原行为）：
      - tools = mcp_manager.list_tools_openai()，executor = mcp_manager.call_tool_sync
    两者都提供时跳过 MCP 前置检查，用传入的工具列表与执行器（如检索智能体
    app.rag.agent 的 search_knowledge_base）。executor 为 {name: callable(name, args)}，
    callable 返回 (result_text, is_error)，与 MCP call_tool_sync 契约一致。

    返回 (messages, answer)：
      - messages：去掉工具轮次系统提示后的消息（含工具结果），供最终回答 LLM 使用；
      - answer：模型停止调工具时**直接给出的结论**（智能体作答；可能为 None——未作答时
        调用方需回退单次生成）。
    工具轮次失败时返回 (入参 messages, None)（安全回退）。
    """
    use_mcp = tools is None or executor is None
    if use_mcp:
        if not mcp_manager.is_ready():
            return messages
        try:
            tools = mcp_manager.list_tools_openai()
        except Exception as e:
            print(f"[MCP] 获取工具列表失败，回退纯 RAG: {e}", flush=True)
            return messages
        if not tools:
            return messages

    loop_messages = [{"role": "system", "content": system_prompt or TOOL_ROUND_SYSTEM}] + list(messages)
    answer: str | None = None   # 模型停止调工具时直接给出的结论（智能体作答）
    try:
        for _ in range(max(1, max_steps or settings.mcp_max_steps)):
            checkpoint()
            resp = llm_client.chat.completions.create(
                model=settings.llm_model,
                messages=loop_messages,
                tools=tools,
                tool_choice="auto",
                temperature=0.0,
                max_tokens=tool_max_tokens or settings.mcp_tool_max_tokens,
            )
            msg = resp.choices[0].message
            if not msg.tool_calls:
                # 模型决定不调工具 → 结束工具轮次；若它直接给出了结论文本，即为智能体答案
                if msg.content and msg.content.strip():
                    answer = msg.content
                break
            loop_messages.append(msg.model_dump(exclude_none=True))   # 回填 assistant(tool_calls)
            for tc in msg.tool_calls:
                name = tc.function.name
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}
                try:
                    if use_mcp:
                        result_text, is_error = mcp_manager.call_tool_sync(name, args)
                    else:
                        result_text, is_error = executor[name](name, args)
                except Exception as e:
                    result_text, is_error = f"[工具调用失败] {e}", True
                content = result_text[: (tool_max_chars or settings.mcp_tool_result_max_chars)]
                if is_error:
                    content = f"[工具执行出错] {content}"
                if trace is not None:
                    trace.append({
                        "step": len(trace) + 1,
                        "type": "tool",
                        "tool": name,
                        "args": json.dumps(args, ensure_ascii=False)[:100],
                        "ok": not is_error,
                        "result_chars": len(content),
                        # 完整工具返回：前端展开后展示 LLM 实际读到的内容
                        "content": content,
                    })
                print(f"[{label}] 调用工具 {name}({json.dumps(args, ensure_ascii=False)[:100]}) -> "
                      f"{'出错' if is_error else '成功'} {len(content)} 字符", flush=True)
                loop_messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": content,
                })
    except Exception as e:
        print(f"[{label}] 工具轮次失败，回退纯 RAG: {e}", flush=True)
        return messages, None
    # 返回：去掉工具轮次系统提示后的 messages（含工具结果）+ 智能体直接作答的结论（可能为 None）
    return loop_messages[1:], answer


def enhance_with_tools(
    messages: list[dict], llm_client=None, trace: list[dict] | None = None,
) -> tuple[list[dict], str | None]:
    """MCP 可选增强入口：启动→就绪判断→工具轮次，任一失败都原样返回（安全回退）

    返回 (messages, answer)：
      - messages：增强后的消息（含工具结果）；
      - answer：智能体在工具轮次中**直接给出的结论**（可能为 None——未直接作答时，
        调用方需回退单次生成）。
    结论轮使用完整答案 token 预算（tool_max_tokens 抬高到 llm_max_tokens），
    保证智能体直接作答时答案长度与常规回答一致。
    trace（可选）：out-param，透传给 run_tool_rounds 记录 MCP 工具调用轨迹。
    """
    if not mcp_manager.is_enabled():
        return messages, None
    if llm_client is None:
        return messages, None
    try:
        mcp_manager.ensure_started()
        if mcp_manager.is_ready():
            return run_tool_rounds(
                messages,
                llm_client=llm_client,
                trace=trace,
                tool_max_tokens=max(settings.mcp_tool_max_tokens, settings.llm_max_tokens),
            )
    except Exception as e:
        print(f"[MCP] 增强失败，回退纯 RAG: {e}", flush=True)
    return messages, None
