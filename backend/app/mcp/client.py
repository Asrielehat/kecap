"""MCP 客户端管理 —— 每次调用独立建连（独立线程 asyncio.run）

历史：曾实现"单例 + 常驻 event loop 线程 + 请求队列"以复用 stdio 连接，但实测
在 Windows ProactorEventLoop 上，跨线程唤醒（call_soon_threadsafe + asyncio.Queue）
与 MCP SDK 底层的 anyio 机制不兼容——worker 协程收不到请求唤醒而挂起，而同一 loop
内跨协程调用（asyncio 直连）完全正常。为稳妥改用最直接的方案：每次调用在独立
线程里 asyncio.run() 完整建连（spawn 子进程 + initialize + 调用 + 关闭）。
代价是每次调用 +0.5~1s 建连开销，但绝无跨线程/跨 loop 兼容问题；fetch 属低频
可选功能，可接受。未来若需常驻连接优化，可在此替换为可靠的复用实现。
"""

import asyncio
import concurrent.futures
import shlex
import sys

from app.core.config import get_settings

# MCP SDK 懒导入：未安装 mcp 包时保持 _MCP_AVAILABLE=False，主链路不受影响
try:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    _MCP_AVAILABLE = True
except ImportError:  # pragma: no cover - 依赖缺失时的兜底
    _MCP_AVAILABLE = False
    ClientSession = StdioServerParameters = stdio_client = None


class MCPNotReadyError(RuntimeError):
    """MCP 客户端未就绪（未启用 / SDK 未安装 / 调用失败）"""


class MCPClientManager:
    def __init__(self) -> None:
        self.settings = get_settings()
        self._last_error = ""
        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="mcp")

    # ── 对外状态 ──
    def is_enabled(self) -> bool:
        return bool(self.settings.mcp_enabled)

    def is_ready(self) -> bool:
        """就绪判断：开关开启 + SDK 已安装（连接为每次调用动态建立）"""
        return self.is_enabled() and _MCP_AVAILABLE

    def ensure_started(self) -> None:
        """无状态：每次调用动态建连，无需预启动。仅记录 SDK 缺失信息。"""
        if not _MCP_AVAILABLE:
            self._last_error = "MCP SDK 未安装（pip install mcp mcp-server-fetch）"

    # ── 子进程命令解析 ──
    def _resolve_command(self) -> str:
        """配置优先；留空时：开发用 sys.executable（venv python，已装 mcp-server-fetch），EXE 模式用 python"""
        if self.settings.mcp_server_command:
            return self.settings.mcp_server_command
        if getattr(sys, "frozen", False):
            return "python"   # PyInstaller 下 sys.executable 是课答.exe，不能当解释器
        return sys.executable

    def _resolve_args(self) -> list[str]:
        return shlex.split(self.settings.mcp_server_args)   # "-m mcp_server_fetch" → ["-m", "mcp_server_fetch"]

    # ── 核心：一次完整建连 + 调用 ──
    async def _call_once(self, name: str, arguments: dict):
        """在临时 event loop 中完整建连并执行一次 MCP 调用。

        name == "__list__" 时返回 OpenAI 兼容的 tools 列表；否则调用指定工具，
        返回 (文本结果, 是否出错)。
        """
        params = StdioServerParameters(command=self._resolve_command(), args=self._resolve_args())
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                if name == "__list__":
                    r = await session.list_tools()
                    from app.mcp.tools import mcp_tools_to_openai
                    return mcp_tools_to_openai(r.tools)
                r = await session.call_tool(name, arguments)
                text = "\n".join(getattr(b, "text", "") for b in r.content if getattr(b, "text", None))
                return text, bool(r.isError)

    def _run_sync(self, name: str, arguments: dict):
        """在独立线程里 asyncio.run 一次调用（当前线程可能有 running loop，不能直接 asyncio.run）"""
        if not self.is_ready():
            raise MCPNotReadyError(self._last_error or "MCP 客户端未就绪")

        async def _wrapped():
            return await asyncio.wait_for(
                self._call_once(name, arguments),
                timeout=self.settings.mcp_tool_timeout,
            )

        try:
            return self._executor.submit(asyncio.run, _wrapped()).result(
                timeout=self.settings.mcp_tool_timeout + 5
            )
        except concurrent.futures.TimeoutError as e:
            raise TimeoutError(f"MCP 工具 {name} 调用超时") from e
        except MCPNotReadyError:
            raise
        except Exception as e:
            raise RuntimeError(f"MCP 调用失败: {e}") from e

    # ── 对外同步接口 ──
    def list_tools_openai(self) -> list[dict]:
        result = self._run_sync("__list__", {})
        return result if isinstance(result, list) else []

    def call_tool_sync(self, name: str, arguments: dict) -> tuple[str, bool]:
        return self._run_sync(name, arguments)

    # ── 关闭 ──
    def close(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)
        print("[MCP] 客户端已关闭", flush=True)


mcp_manager = MCPClientManager()   # 模块级单例
