"""MCP 工具 Schema 转换 —— MCP 定义 ↔ OpenAI function calling 格式"""


def mcp_tools_to_openai(mcp_tools: list) -> list[dict]:
    """MCP list_tools() 返回的 Tool 列表 → OpenAI 兼容 tools 参数

    MCP Tool 含 name / description / inputSchema（本就是 JSON Schema）；
    OpenAI 格式为 {type:"function", function:{name, description, parameters}}，
    parameters 直接复用 inputSchema 即可，无需额外映射。
    """
    out = []
    for t in mcp_tools:
        out.append({
            "type": "function",
            "function": {
                "name": t.name,
                "description": getattr(t, "description", "") or "",
                "parameters": getattr(t, "inputSchema", None)
                              or {"type": "object", "properties": {}},
            },
        })
    return out
