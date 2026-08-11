"""MCP 客户端集成包：让课答的 LLM 能通过 function calling 调用外部 MCP 工具（如 fetch 抓网页）。"""

from app.mcp.client import MCPNotReadyError, mcp_manager

__all__ = ["mcp_manager", "MCPNotReadyError"]
