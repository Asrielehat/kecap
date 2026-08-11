"""可订阅轨迹列表 —— 流式端点借此实时推送 Agent 思考过程的每一步。"""


class TraceRecorder(list):
    """list 子类：append 时通知订阅者。

    所有现有 `trace.append(...)` 调用点不改即可获得实时通知（流式端点订阅后把每步
    推进 SSE）。外部调用方传普通 list 时行为不变。
    """

    def __init__(self):
        super().__init__()
        self._listeners = []

    def listen(self, fn):
        self._listeners.append(fn)

    def append(self, item):
        super().append(item)
        for fn in self._listeners:
            try:
                fn(item)
            except Exception:
                pass
