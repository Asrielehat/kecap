"""深度思考流式验证：ask/stream 应实时推送 reasoning 事件（先于答案 token）

断言核心：开启思考模式后，存在 reasoning 事件、拼接非空、且首个 reasoning
先于任何 token 事件出现（即推理链实时流式，而非一次性下发）。

用法（backend 目录）:
    ../venv/Scripts/python.exe -m scripts.verify_reasoning_stream            # 思考开启
    ../venv/Scripts/python.exe -m scripts.verify_reasoning_stream --fallback # 思考关闭

settings 在 import 时烘焙，开关必须在导入 app 前经环境变量决定，故分两次独立进程运行。
运行前需先停掉占用 Qdrant 文件锁的服务进程。
"""

import os
import sys

# 本次验证关闭 MCP，聚焦深度思考
os.environ.setdefault("MCP_ENABLED", "false")
FALLBACK = "--fallback" in sys.argv
os.environ["LLM_THINKING_ENABLED"] = "false" if FALLBACK else "true"

from fastapi.testclient import TestClient
from app.main import app

SAMPLE_MD = """# 数据结构查找复杂度

二叉搜索树（BST）的查找时间复杂度平均为 O(log n)，最坏情况退化为 O(n)。
红黑树是自平衡二叉查找树，查找稳定为 O(log n)。
哈希表通过哈希函数映射，平均查找 O(1)，哈希冲突时最坏 O(n)。
"""


def main() -> None:
    with TestClient(app) as c:
        cid = c.post("/api/courses/", json={"name": "深度思考验证课"}).json()["id"]
        r = c.post(
            "/api/documents/upload",
            files={"file": ("深度思考材料.md", SAMPLE_MD.encode("utf-8"), "text/markdown")},
            data={"course_id": cid},
        )
        print(f"课程: {cid} 上传: {r.json().get('status')}")

        kinds: list[str] = []
        reasoning_parts: list[str] = []
        tokens: list[str] = []
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
                if evt["type"] == "reasoning":
                    reasoning_parts.append(evt["data"])
                elif evt["type"] == "token":
                    tokens.append(evt["data"])
                elif evt["type"] == "done":
                    done_id = (evt.get("data") or {}).get("assistant_message_id", "")

        answer = "".join(tokens)
        reasoning = "".join(reasoning_parts)
        print(f"\nevent_types: {kinds}")
        print(f"reasoning_chars: {len(reasoning)}  answer_chars: {len(answer)}  done_id: {bool(done_id)}")
        print(f"reasoning 预览: {reasoning[:100]!r}")

        if FALLBACK:
            assert len(reasoning_parts) == 0, "思考关闭时不应有 reasoning 事件"
            assert answer, "答案不应为空"
            print("\n[判定] 思考关闭：无 reasoning 事件，答案正常流式 ✓")
            return

        assert len(reasoning_parts) > 0, "思考开启时应有 reasoning 事件"
        assert reasoning.strip(), "推理链不应为空"
        first_reasoning = kinds.index("reasoning")
        first_token = kinds.index("token")
        assert first_reasoning < first_token, "推理链应实时先于答案 token 出现"
        assert answer, "答案不应为空"
        assert done_id, "done 事件应携带 assistant_message_id"
        print("\n[判定] 思考开启：reasoning 实时先于 token 流式推送 ✓")


if __name__ == "__main__":
    main()
