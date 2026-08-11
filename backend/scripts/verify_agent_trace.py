"""Agent 轨迹验证：ask 响应携带 agent_trace（真实 LLM）

用法（backend 目录）:
    ../venv/Scripts/python.exe -m scripts.verify_agent_trace            # agent 开启：断言轨迹非空且结构正确
    ../venv/Scripts/python.exe -m scripts.verify_agent_trace --fallback # agent 关闭：断言轨迹为空/None

settings 在 import 时烘焙，开关必须在导入 app 前经环境变量决定，故分两次独立进程运行。
"""

import os
import sys

# 本次验证关闭 MCP，聚焦检索智能体轨迹
os.environ.setdefault("MCP_ENABLED", "false")
FALLBACK = "--fallback" in sys.argv
os.environ["AGENT_RETRIEVAL_ENABLED"] = "false" if FALLBACK else "true"

from fastapi.testclient import TestClient
from app.main import app

SAMPLE_MD = """# 数据结构查找复杂度

二叉搜索树（BST）的查找时间复杂度平均为 O(log n)，最坏情况退化为 O(n)。
红黑树是自平衡二叉查找树，查找稳定为 O(log n)。
哈希表通过哈希函数映射，平均查找 O(1)，哈希冲突时最坏 O(n)。
"""


def main() -> None:
    with TestClient(app) as c:
        cid = c.post("/api/courses/", json={"name": "轨迹验证课"}).json()["id"]
        r = c.post(
            "/api/documents/upload",
            files={"file": ("轨迹验证材料.md", SAMPLE_MD.encode("utf-8"), "text/markdown")},
            data={"course_id": cid},
        )
        print(f"课程: {cid} 上传: {r.json().get('status')}")

        r = c.post("/api/chat/ask", json={"course_id": cid, "question": "二叉搜索树的查找复杂度是多少？"})
        resp = r.json()
        trace = resp.get("agent_trace")
        print(f"\nstatus: {r.status_code}")
        print(f"agent_trace: {trace}")

        if FALLBACK:
            assert trace is None or len(trace) == 0, "agent 关闭时 agent_trace 应为空/None"
            assert resp.get("answer"), "答案不应为空"
            print("\n[判定] agent 关闭：agent_trace 为空/None，普通回答正常 ✓")
            return

        assert trace and len(trace) > 0, "agent 开启时 agent_trace 不应为空"
        assert trace[0]["type"] == "retrieval", f"首条应为 retrieval，实际: {trace[0].get('type')}"
        for key in ("query", "top_k", "hits"):
            assert key in trace[0], f"轨迹条目应含 {key}"
        assert resp.get("answer"), "答案不应为空"
        print("\n[判定] agent 开启：agent_trace 非空且结构正确（首条含 query/top_k/hits）✓")


if __name__ == "__main__":
    main()
