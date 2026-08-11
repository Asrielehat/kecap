"""Agent 流式轨迹验证：ask/stream SSE 事件顺序（真实 LLM）

断言核心：检索/工具轨迹逐条**实时**先于答案 token 出现，而非全部跑完再一次性下发。

用法（backend 目录）:
    ../venv/Scripts/python.exe -m scripts.verify_stream_trace            # agent 开启
    ../venv/Scripts/python.exe -m scripts.verify_stream_trace --fallback # agent 关闭

settings 在 import 时烘焙，开关必须在导入 app 前经环境变量决定，故分两次独立进程运行。
运行前需先停掉占用 Qdrant 文件锁的服务进程。
"""

import os
import sys

# 本次验证关闭 MCP，聚焦检索智能体轨迹
os.environ.setdefault("MCP_ENABLED", "false")
FALLBACK = "--fallback" in sys.argv
os.environ["AGENT_RETRIEVAL_ENABLED"] = "false" if FALLBACK else "true"
# 规划是默认开启的（config 默认 True），fallback 模式必须关掉，否则会有 plan 轨迹
os.environ["AGENT_PLANNING_ENABLED"] = "false" if FALLBACK else "true"

from fastapi.testclient import TestClient
from app.main import app

SAMPLE_MD = """# 数据结构查找复杂度

二叉搜索树（BST）的查找时间复杂度平均为 O(log n)，最坏情况退化为 O(n)。
红黑树是自平衡二叉查找树，查找稳定为 O(log n)。
哈希表通过哈希函数映射，平均查找 O(1)，哈希冲突时最坏 O(n)。
"""


def main() -> None:
    with TestClient(app) as c:
        cid = c.post("/api/courses/", json={"name": "流式轨迹验证课"}).json()["id"]
        r = c.post(
            "/api/documents/upload",
            files={"file": ("流式轨迹验证材料.md", SAMPLE_MD.encode("utf-8"), "text/markdown")},
            data={"course_id": cid},
        )
        print(f"课程: {cid} 上传: {r.json().get('status')}")

        kinds: list[str] = []
        traces: list[dict] = []
        tokens: list[str] = []
        citations: list = []
        done_id = ""

        with c.stream(
            "POST", "/api/chat/ask/stream",
            json={"course_id": cid, "question": "二叉搜索树的查找复杂度是多少？"},
        ) as resp:
            print(f"status: {resp.status_code}")
            for line in resp.iter_lines():
                if not line.startswith("data: "):
                    continue
                evt = __import__("json").loads(line[6:])
                kinds.append(evt["type"])
                if evt["type"] == "trace":
                    traces.append(evt["data"])
                elif evt["type"] == "token":
                    tokens.append(evt["data"])
                elif evt["type"] == "citations":
                    citations = evt["data"]
                elif evt["type"] == "done":
                    done_id = (evt.get("data") or {}).get("assistant_message_id", "")

        answer = "".join(tokens)
        print(f"\nevent_types: {kinds}")
        print(f"trace_entries: {len(traces)} first_type={traces[0].get('type') if traces else None}")
        print(f"answer_chars: {len(answer)}  citations: {len(citations)}  done_id: {bool(done_id)}")

        if FALLBACK:
            assert len(traces) == 0, "agent 关闭时流式不应有 trace 事件"
            assert answer, "答案不应为空"
            print("\n[判定] agent 关闭：无 trace 事件，答案正常流式 ✓")
            return

        assert len(traces) > 0, "agent 开启时流式应有 trace 事件"
        assert traces[0]["type"] in ("plan", "retrieval"), f"首条 trace 应为 plan/retrieval，实际: {traces[0].get('type')}"
        first_trace = kinds.index("trace")
        first_token = kinds.index("token")
        assert first_trace < first_token, "trace 应实时先于 token 出现（而非跑完后一次性下发）"
        assert answer, "答案不应为空"
        assert len(citations) > 0, "应有引文元数据"
        assert done_id, "done 事件应携带 assistant_message_id"
        print("\n[判定] agent 开启：trace 逐条先于 token 实时推送，首条为 plan/retrieval ✓")


if __name__ == "__main__":
    main()
