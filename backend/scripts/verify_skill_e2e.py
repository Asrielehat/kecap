"""技能系统手动端到端验证（真实 LLM，需 SKILLS_ENABLED=true）

用法（backend 目录）:
    SKILLS_ENABLED=true ../venv/Scripts/python.exe scripts/verify_skill_e2e.py

流程：建课程 → 同一对话多轮提问 → "帮我总结我学到了什么" 触发学习总结技能 →
断言答案含 Mermaid mindmap 结构；再验证普通问题不含 mindmap。
"""

import os

os.environ.setdefault("SKILLS_ENABLED", "true")

from fastapi.testclient import TestClient
from app.main import app


def main() -> None:
    with TestClient(app) as c:
        # 1. 建课程
        r = c.post("/api/courses/", json={"name": "技能E2E测试课"})
        course = r.json()
        cid = course["id"]
        print(f"课程: {cid}")

        # 2. 同一对话多轮提问
        conv = None
        questions = ["什么是二叉树", "讲一下哈希表", "解释动态规划"]
        for q in questions:
            r = c.post("/api/chat/ask", json={
                "course_id": cid, "question": q, "conversation_id": conv,
            })
            d = r.json()
            conv = d["conversation_id"]
            print(f"Q: {q} -> HTTP {r.status_code}")

        # 3. 触发学习总结技能
        r = c.post("/api/chat/ask", json={
            "course_id": cid, "question": "帮我总结我学到了什么", "conversation_id": conv,
        })
        d = r.json()
        ans = d.get("answer", "") or ""
        print("\n=== 总结答案（前 900 字）===")
        print(ans[:900])
        print("\n[判定] 含 'mindmap':", "mindmap" in ans)
        print("[判定] 含 'root((': ", "root((" in ans)
        print("[判定] citations 为空（基于对话总结）:", not d.get("citations"))

        # 4. 普通问题（未命中技能）应不含 mindmap
        r = c.post("/api/chat/ask", json={
            "course_id": cid, "question": "什么是快速排序", "conversation_id": conv,
        })
        ans2 = r.json().get("answer", "") or ""
        print("\n[判定] 普通问题不含 mindmap:", "mindmap" not in ans2)


if __name__ == "__main__":
    main()
