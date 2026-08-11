"""检索工具化验证：LLM 自主多轮检索（真实 LLM）

用法（backend 目录）:
    ../venv/Scripts/python.exe -m scripts.verify_agent_retrieval            # agent 开启全链路
    ../venv/Scripts/python.exe -m scripts.verify_agent_retrieval --fallback # agent 关闭回归

说明：settings 在 import 时烘焙（lru_cache），开关必须在导入 app 前经环境变量决定，
故分两次独立进程运行。开启模式验证 search_knowledge_base 被自主调用、多轮换词重查、
E2E 答案带引文；关闭模式验证回退硬编码检索、行为与现状一致（上方不应出现 [Agent] 日志）。
"""

import os
import sys

# 本次验证关闭 MCP，聚焦检索智能体链路
os.environ.setdefault("MCP_ENABLED", "false")
FALLBACK = "--fallback" in sys.argv
os.environ["AGENT_RETRIEVAL_ENABLED"] = "false" if FALLBACK else "true"

from fastapi.testclient import TestClient
from app.main import app
from app.rag.generator import llm_client
from app.rag.agent import run_retrieval_agent

# 临时课件内容：涵盖复合题的多个角度，确保多轮检索能命中
SAMPLE_MD = """# 数据结构查找复杂度

## 二叉搜索树（BST）
二叉搜索树（Binary Search Tree）的查找时间复杂度：平均情况下为 O(log n)，因为树大致平衡时，
每层能把搜索范围减半。但在最坏情况下（例如按有序序列插入，树退化成单链），查找退化为 O(n)。
每次查找从根节点开始，与当前节点比较后决定去左子树还是右子树。

## 红黑树
红黑树是一种自平衡的二叉查找树，通过给节点着色（红/黑）和旋转操作维持平衡。
它的查找时间复杂度稳定为 O(log n)，最坏情况也不会退化，因为任何路径都不会比最短路径长两倍以上。

## 哈希表
哈希表通过哈希函数把键映射到数组下标，平均情况下查找为 O(1)。但发生哈希冲突时，
同一槽位会形成链表，若大量键冲突到同一槽位，查找退化为 O(n)。这就是哈希表平均 O(1)、最坏 O(n) 的原因。
"""


def _setup_course(c: TestClient) -> str:
    """建课 + 上传临时课件，返回 course_id"""
    cid = c.post("/api/courses/", json={"name": "检索智能体验证课"}).json()["id"]
    r = c.post(
        "/api/documents/upload",
        files={"file": ("检索验证材料.md", SAMPLE_MD.encode("utf-8"), "text/markdown")},
        data={"course_id": cid},
    )
    d = r.json()
    print(f"课程: {cid} 上传: {d.get('filename')} chunks={d.get('chunk_count')}")
    assert d.get("status") == "success", f"上传未成功: {d}"
    return cid


def main() -> None:
    with TestClient(app) as c:
        cid = _setup_course(c)

        if FALLBACK:
            # ── 回归：agent 关闭 → 硬编码检索，行为与现状一致 ──
            r = c.post("/api/chat/ask", json={"course_id": cid, "question": "什么是红黑树？"})
            resp = r.json()
            print("\n=== E2E ask（agent 关闭，回归）===")
            print("答案(前180):", (resp.get("answer") or "")[:180].replace("\n", " "))
            assert resp.get("answer"), "agent 关闭时也应正常回答（回退硬编码检索）"
            assert resp.get("citations"), "agent 关闭时仍应返回检索引文（与现状一致）"
            print("\n[判定] agent 关闭链路通过（上方不应出现 [Agent] 日志 = 硬编码路径生效）")
            return

        # ── 直接调检索智能体 —— 证明 search_knowledge_base 被调用且收集到 docs ──
        question = "二叉搜索树和红黑树的查找复杂度分别是什么，为什么不同？"
        docs = run_retrieval_agent(question, llm_client, cid)
        print(f"\n=== 直接调 run_retrieval_agent ===")
        print(f"收集到 docs: {len(docs)}（每行 [Agent] 检索 代表一轮自主检索，>1 轮即换词重查）")
        assert docs, "检索智能体未收集到任何文档 —— search_knowledge_base 未被调用或没检索到内容"

        # ── E2E ask（agent 开启）—— 走完整管道 ──
        r = c.post("/api/chat/ask", json={"course_id": cid, "question": question})
        resp = r.json()
        answer = resp.get("answer") or ""
        citations = resp.get("citations") or []
        print(f"\n=== E2E ask（agent 开启）===")
        print(f"citations: {len(citations)} 条, confidence: {resp.get('confidence')}")
        print("答案(前260):", answer[:260].replace("\n", " "))
        assert answer, "answer 为空"
        assert "[1]" in answer, "答案应含引用标记 [1]"
        assert citations, "citations 不应为空 —— 应有检索引文"
        assert citations[0].get("document_name"), "引文应带文档名"

        print("\n[判定] agent 开启链路全部通过")


if __name__ == "__main__":
    main()
