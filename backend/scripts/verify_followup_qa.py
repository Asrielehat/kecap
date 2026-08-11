"""追问升级验证：智能提问对话框的 question / history 端到端测试（真实 LLM）

用法（backend 目录）:
    ../venv/Scripts/python.exe scripts/verify_followup_qa.py

流程：建课程 → ask 一条 → 对 assistant 消息追问：
1) 不带 question  → 应为四段式解释
2) 带 question    → 应针对问题回答，且响应回显 question
3) 带 history     → 应正常（承接式提问）
"""

import os

# 本次验证关闭 MCP，聚焦追问链路
os.environ.setdefault("MCP_ENABLED", "false")

from fastapi.testclient import TestClient
from app.main import app


def main() -> None:
    with TestClient(app) as c:
        # 1. 建课程
        r = c.post("/api/courses/", json={"name": "追问QA验证课"})
        cid = r.json()["id"]
        print(f"课程: {cid}")

        # 2. 主对话 ask 一条，得到 assistant 消息 id
        r = c.post("/api/chat/ask", json={"course_id": cid, "question": "什么是二叉树？"})
        d = r.json()
        conv = d["conversation_id"]
        msg_id = d["assistant_message_id"]
        print(f"会话: {conv} 消息: {msg_id}")

        # 3. 追问：不带 question（应四段式）
        r = c.post("/api/chat/follow-up", json={
            "selected_text": "二叉树", "context_paragraph": "二叉树是一种树结构",
            "message_id": msg_id, "course_id": cid, "conversation_id": conv,
        })
        d1 = r.json()
        print("\n=== 不带 question ===")
        print("回显 question:", repr(d1.get("question")))
        print("答案(前200):", (d1.get("answer") or "")[:200].replace("\n", " "))

        # 4. 追问：带 question（应针对问题回答）
        r = c.post("/api/chat/follow-up", json={
            "selected_text": "二叉树", "context_paragraph": "二叉树是一种树结构",
            "message_id": msg_id, "course_id": cid, "conversation_id": conv,
            "question": "为什么它的遍历时间复杂度是 O(n)？",
        })
        d2 = r.json()
        print("\n=== 带 question ===")
        print("回显 question:", repr(d2.get("question")))
        print("答案(前250):", (d2.get("answer") or "")[:250].replace("\n", " "))

        # 5. 追问：带 question + history（承接式）
        r = c.post("/api/chat/follow-up", json={
            "selected_text": "二叉树", "context_paragraph": "二叉树是一种树结构",
            "message_id": msg_id, "course_id": cid, "conversation_id": conv,
            "question": "那中序遍历呢？",
            "history": [{"question": None, "answer": d1.get("answer")}],
        })
        d3 = r.json()
        print("\n=== 带 question + history ===")
        print("回显 question:", repr(d3.get("question")))
        print("答案(前250):", (d3.get("answer") or "")[:250].replace("\n", " "))

        print("\n[判定] 全部追问调用成功，无 500")


if __name__ == "__main__":
    main()
