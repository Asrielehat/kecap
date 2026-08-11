"""验证"智能体直接作答"：工具轮次中模型直接给结论 → 不再二次单次生成

对运行中的服务（:8000）流式提问，收集 SSE 事件，并验证：
1. trace 实时先于 token 出现
2. 答案非空、有 done
3. 后端日志出现 [Generator] 智能体直接作答（需重启后端后查日志）

用法（backend 目录）:
    ../venv/Scripts/python.exe -m scripts.verify_agent_answer <course_id> <question>
"""

import json
import sys

import httpx

COURSE = sys.argv[1] if len(sys.argv) > 1 else ""
QUESTION = sys.argv[2] if len(sys.argv) > 2 else "Transformer 的自注意力机制是什么？"


def main() -> None:
    assert COURSE, "需要课程 id"
    kinds: list[str] = []
    traces: list[dict] = []
    tokens: list[str] = []
    citations: list = []
    done_id = ""
    with httpx.Client(trust_env=False, timeout=120) as c:
        with c.stream(
            "POST", "http://localhost:8000/api/chat/ask/stream",
            json={"course_id": COURSE, "question": QUESTION},
        ) as resp:
            print(f"status: {resp.status_code}")
            for line in resp.iter_lines():
                if not line.startswith("data: "):
                    continue
                evt = json.loads(line[6:])
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
    print(f"trace_steps: {len(traces)}  types={[t.get('type') for t in traces]}")
    print(f"answer_chars: {len(answer)}  citations: {len(citations)}  done_id: {bool(done_id)}")

    first_trace = kinds.index("trace") if "trace" in kinds else None
    first_token = kinds.index("token") if "token" in kinds else None
    assert answer, "答案不应为空"
    assert done_id, "done 应携带 assistant_message_id"
    if first_trace is not None and first_token is not None:
        assert first_trace < first_token, "trace 应先于 token"
    print("\n[判定] 流式正常 OK（查看后端日志确认是否走智能体直接作答）")


if __name__ == "__main__":
    main()
