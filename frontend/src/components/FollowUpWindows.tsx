"use client";
import { useState, useRef, useEffect } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import type { FollowUpModalState, FollowUpDialogState, FollowUpTurn } from "../lib/types";
// ── 共享拖拽窗口 hook（弹窗 / 对话框共用）──
function useDraggableWindow(initialX: number, initialY: number, width: number) {
  const [pos, setPos] = useState({ x: initialX, y: initialY });
  const [dragging, setDragging] = useState(false);
  const dragRef = useRef({ startX: 0, startY: 0, startLeft: 0, startTop: 0 });

  // 窗口初始位置变更时同步（多弹窗各自来自状态）


  useEffect(() => {
    if (!dragging) return;
    function handleMouseMove(e: MouseEvent) {
      const dx = e.clientX - dragRef.current.startX;
      const dy = e.clientY - dragRef.current.startY;
      setPos({
        x: Math.max(0, Math.min(window.innerWidth - width, dragRef.current.startLeft + dx)),
        y: Math.max(0, Math.min(window.innerHeight - 100, dragRef.current.startTop + dy)),
      });
    }
    function handleMouseUp() { setDragging(false); }
    window.addEventListener("mousemove", handleMouseMove);
    window.addEventListener("mouseup", handleMouseUp);
    return () => {
      window.removeEventListener("mousemove", handleMouseMove);
      window.removeEventListener("mouseup", handleMouseUp);
    };
  }, [dragging, width]);

  function handleTitleMouseDown(e: React.MouseEvent, onFocus?: () => void) {
    if (onFocus) onFocus();
    setDragging(true);
    dragRef.current = { startX: e.clientX, startY: e.clientY, startLeft: pos.x, startTop: pos.y };
    e.preventDefault();
  }

  return { pos, handleTitleMouseDown };
}

// ── 可拖拽追问弹窗子组件 ──
export function DraggableModal({
  modal,
  topZIndex,
  onClose,
  onFocus,
  onFollowUp,
}: {
  modal: FollowUpModalState;
  topZIndex: number;
  onClose: () => void;
  onFocus: () => void;
  onFollowUp: (text: string, paragraph: string, parentFollowUpId: string) => void;
}) {
  const [pos, setPos] = useState({ x: modal.x, y: modal.y });
  const [dragging, setDragging] = useState(false);
  const dragRef = useRef({ startX: 0, startY: 0, startLeft: 0, startTop: 0 });
  const [innerSelection, setInnerSelection] = useState<{
    text: string; paragraph: string; x: number; y: number;
  } | null>(null);

  // 窗口大小变化时保持弹窗在可视范围内


  // 弹窗内文字选中检测
  function handleInnerMouseUp(e: React.MouseEvent) {
    setTimeout(() => {
      const sel = window.getSelection();
      if (!sel || !sel.toString().trim()) {
        setInnerSelection(null);
        return;
      }
      const text = sel.toString().trim();
      if (text.length < 2 || text.length > 500) {
        setInnerSelection(null);
        return;
      }
      // 获取所在段落的文本
      const anchorNode = sel.anchorNode;
      let paragraph = text;
      if (anchorNode) {
        const parent = anchorNode.parentElement;
        if (parent) {
          paragraph = (parent.textContent || text).substring(0, 800);
        }
      }
      setInnerSelection({ text, paragraph, x: e.clientX, y: e.clientY });
    }, 10);
  }

  function handleInnerFollowUp() {
    if (!innerSelection) return;
    onFollowUp(innerSelection.text, innerSelection.paragraph, modal.followUpId || modal.id);
    setInnerSelection(null);
  }

  function handleMouseDown(e: React.MouseEvent) {
    setDragging(true);
    onFocus();
    dragRef.current = {
      startX: e.clientX,
      startY: e.clientY,
      startLeft: pos.x,
      startTop: pos.y,
    };
    e.preventDefault();
  }

  useEffect(() => {
    if (!dragging) return;
    function handleMouseMove(e: MouseEvent) {
      const dx = e.clientX - dragRef.current.startX;
      const dy = e.clientY - dragRef.current.startY;
      setPos({
        x: Math.max(0, Math.min(window.innerWidth - 420, dragRef.current.startLeft + dx)),
        y: Math.max(0, Math.min(window.innerHeight - 100, dragRef.current.startTop + dy)),
      });
    }
    function handleMouseUp() { setDragging(false); }
    window.addEventListener("mousemove", handleMouseMove);
    window.addEventListener("mouseup", handleMouseUp);
    return () => {
      window.removeEventListener("mousemove", handleMouseMove);
      window.removeEventListener("mouseup", handleMouseUp);
    };
  }, [dragging]);

  const width = 400;
  const maxHeight = 480;

  return (
    <div
      className="fixed bg-white rounded-xl shadow-2xl border border-zinc-300 flex flex-col overflow-hidden"
      style={{
        left: pos.x,
        top: pos.y,
        width,
        maxHeight,
        zIndex: modal.zIndex,
      }}
      onMouseDown={onFocus}
    >
      {/* 标题栏（拖拽把手） */}
      <div
        className="flex items-center gap-2 px-4 py-2.5 bg-gradient-to-r from-blue-50 to-indigo-50 border-b border-zinc-200 cursor-move select-none shrink-0"
        onMouseDown={handleMouseDown}
      >
        <span className="text-sm">🔍</span>
        <span className="text-xs font-medium text-zinc-700 truncate flex-1">
          追问: {modal.selectedText.slice(0, 40)}{modal.selectedText.length > 40 ? "…" : ""}
        </span>
        <button
          onClick={(e) => { e.stopPropagation(); onClose(); }}
          className="text-zinc-400 hover:text-zinc-600 hover:bg-zinc-200 rounded-full w-5 h-5 flex items-center justify-center text-xs shrink-0 transition-colors"
        >
          ×
        </button>
      </div>

      {/* 正文区 */}
      <div className="flex-1 overflow-auto px-4 py-3">
        {modal.loading ? (
          <div className="flex items-center gap-2.5 py-6">
            <div className="w-5 h-5 border-2 border-blue-400 border-t-transparent rounded-full animate-spin shrink-0" />
            <span className="text-xs text-zinc-400">正在从课件中检索解释…</span>
          </div>
        ) : (
          <div
            className="text-sm leading-relaxed markdown-body"
            onMouseUp={handleInnerMouseUp}
            style={{ userSelect: "text", cursor: "text" }}>
            {/* 弹窗内追问浮动按钮 */}
            {innerSelection && (
              <div
                className="fixed bg-white border border-purple-400 shadow-lg rounded-lg px-3 py-2 flex items-center gap-2"
                style={{ zIndex: topZIndex + 2, left: Math.min(innerSelection.x, window.innerWidth - 120), top: innerSelection.y + 20 }}
              >
                <span className="text-[11px] text-zinc-500 max-w-[200px] truncate">
                  追问: &quot;{innerSelection.text.slice(0, 25)}{innerSelection.text.length > 25 ? "…" : ""}&quot;
                </span>
                <button
                  onClick={(e) => { e.stopPropagation(); handleInnerFollowUp(); }}
                  className="px-2.5 py-1 text-xs bg-purple-600 text-white rounded-md hover:bg-purple-700 transition-colors shrink-0"
                >
                  追问
                </button>
                <button
                  onClick={(e) => { e.stopPropagation(); setInnerSelection(null); }}
                  className="text-zinc-300 hover:text-zinc-500 text-xs shrink-0"
                >
                  ×
                </button>
              </div>
            )}
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              components={{
                h1: ({ children }) => <h1 className="text-sm font-semibold text-zinc-800 mt-2 mb-1">{children}</h1>,
                h2: ({ children }) => <h2 className="text-xs font-semibold text-zinc-800 mt-2 mb-1">{children}</h2>,
                h3: ({ children }) => <h3 className="text-xs font-medium text-zinc-700 mt-1.5 mb-0.5">{children}</h3>,
                p: ({ children }) => <p className="text-xs text-zinc-700 my-1.5 leading-relaxed">{children}</p>,
                strong: ({ children }) => <strong className="font-semibold text-zinc-800">{children}</strong>,
                ul: ({ children }) => <ul className="list-disc list-inside my-1 space-y-0.5 text-xs">{children}</ul>,
                ol: ({ children }) => <ol className="list-decimal list-inside my-1 space-y-0.5 text-xs">{children}</ol>,
                li: ({ children }) => <li className="text-xs text-zinc-700">{children}</li>,
                code: ({ className, children }) => {
                  const isInline = !className;
                  return isInline
                    ? <code className="bg-zinc-200 text-zinc-800 px-1 py-0.5 rounded text-[11px] font-mono">{children}</code>
                    : <code className="block bg-zinc-800 text-zinc-100 text-[11px] p-2.5 rounded-lg my-1.5 overflow-x-auto font-mono whitespace-pre-wrap">{children}</code>;
                },
                pre: ({ children }) => <>{children}</>,
                a: ({ href, children }) => <a href={href} target="_blank" rel="noopener" className="text-blue-600 underline">{children}</a>,
                blockquote: ({ children }) => <blockquote className="border-l-3 border-blue-400 bg-blue-50 px-2.5 py-1 my-1.5 text-xs text-zinc-600 rounded-r">{children}</blockquote>,
                hr: () => <hr className="border-zinc-200 my-2" />,
                em: ({ children }) => <em className="italic text-zinc-600">{children}</em>,
                table: ({ children }) => <div className="overflow-x-auto my-1.5"><table className="w-full text-[11px] border-collapse">{children}</table></div>,
                th: ({ children }) => <th className="border border-zinc-300 bg-zinc-100 px-1.5 py-0.5 text-left font-medium text-zinc-700">{children}</th>,
                td: ({ children }) => <td className="border border-zinc-300 px-1.5 py-0.5 text-zinc-600">{children}</td>,
              }}
            >
              {modal.answer}
            </ReactMarkdown>

            {modal.citations && modal.citations.length > 0 && (
              <details className="mt-3 pt-2 border-t border-zinc-200">
                <summary className="text-[11px] text-zinc-400 cursor-pointer hover:text-zinc-600">
                  参考来源（{modal.citations.length} 条）
                </summary>
                <div className="mt-1.5 space-y-1.5">
                  {modal.citations.map((cit, j) => (
                    <div key={j} className="bg-zinc-50 rounded-md p-2 border border-zinc-100">
                      <div className="flex items-center justify-between mb-0.5">
                        <span className="text-[11px] font-medium text-blue-600">
                          {cit.document_name}{cit.page ? ` · 第${cit.page}页` : ""}
                        </span>
                        <span className="text-[10px] text-zinc-400">
                          {(cit.score * 100).toFixed(0)}%
                        </span>
                      </div>
                      <p className="text-[11px] text-zinc-500 line-clamp-2">{cit.text}</p>
                    </div>
                  ))}
                </div>
              </details>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

// ── 智能提问对话框子组件（聊天式：问答无限叠加 + 底部输入框）──
const dialogMarkdownComponents: Components = {
  h1: ({ children }) => <h1 className="text-sm font-semibold text-zinc-800 mt-2 mb-1">{children}</h1>,
  h2: ({ children }) => <h2 className="text-xs font-semibold text-zinc-800 mt-2 mb-1">{children}</h2>,
  h3: ({ children }) => <h3 className="text-xs font-medium text-zinc-700 mt-1.5 mb-0.5">{children}</h3>,
  p: ({ children }) => <p className="text-xs text-zinc-700 my-1.5 leading-relaxed">{children}</p>,
  strong: ({ children }) => <strong className="font-semibold text-zinc-800">{children}</strong>,
  ul: ({ children }) => <ul className="list-disc list-inside my-1 space-y-0.5 text-xs">{children}</ul>,
  ol: ({ children }) => <ol className="list-decimal list-inside my-1 space-y-0.5 text-xs">{children}</ol>,
  li: ({ children }) => <li className="text-xs text-zinc-700">{children}</li>,
  code: ({ className, children }) => {
    const isInline = !className;
    return isInline
      ? <code className="bg-zinc-200 text-zinc-800 px-1 py-0.5 rounded text-[11px] font-mono">{children}</code>
      : <code className="block bg-zinc-800 text-zinc-100 text-[11px] p-2.5 rounded-lg my-1.5 overflow-x-auto font-mono whitespace-pre-wrap">{children}</code>;
  },
  pre: ({ children }) => <>{children}</>,
  a: ({ href, children }) => <a href={href} target="_blank" rel="noopener" className="text-blue-600 underline">{children}</a>,
  blockquote: ({ children }) => <blockquote className="border-l-3 border-blue-400 bg-blue-50 px-2.5 py-1 my-1.5 text-xs text-zinc-600 rounded-r">{children}</blockquote>,
  hr: () => <hr className="border-zinc-200 my-2" />,
  em: ({ children }) => <em className="italic text-zinc-600">{children}</em>,
  table: ({ children }) => <div className="overflow-x-auto my-1.5"><table className="w-full text-[11px] border-collapse">{children}</table></div>,
  th: ({ children }) => <th className="border border-zinc-300 bg-zinc-100 px-1.5 py-0.5 text-left font-medium text-zinc-700">{children}</th>,
  td: ({ children }) => <td className="border border-zinc-300 px-1.5 py-0.5 text-zinc-600">{children}</td>,
};

export function DraggableDialog({
  dialog,
  topZIndex,
  onClose,
  onFocus,
  onSendQuestion,
  onInnerFollowUp,
}: {
  dialog: FollowUpDialogState;
  topZIndex: number;
  onClose: () => void;
  onFocus: () => void;
  onSendQuestion: (dialogId: string, question: string) => void;
  onInnerFollowUp: (turnId: string, text: string, paragraph: string) => void;
}) {
  const [input, setInput] = useState("");
  const [innerSelection, setInnerSelection] = useState<{
    turnId: string; text: string; paragraph: string; x: number; y: number;
  } | null>(null);
  const bodyRef = useRef<HTMLDivElement>(null);
  const { pos, handleTitleMouseDown } = useDraggableWindow(dialog.x, dialog.y, 440);

  const lastTurn = dialog.turns[dialog.turns.length - 1];
  const isSending = !!lastTurn?.loading;

  // 新问答进来时自动滚动到底
  useEffect(() => {
    bodyRef.current?.scrollTo({ top: bodyRef.current.scrollHeight, behavior: "smooth" });
  }, [dialog.turns]);

  // 对话框内某条回答的框选检测（带 turnId，用于嵌套追问的父引用）
  function handleTurnMouseUp(turn: FollowUpTurn, e: React.MouseEvent) {
    setTimeout(() => {
      const sel = window.getSelection();
      if (!sel || !sel.toString().trim()) {
        setInnerSelection(null);
        return;
      }
      const text = sel.toString().trim();
      if (text.length < 2 || text.length > 500) {
        setInnerSelection(null);
        return;
      }
      const anchorNode = sel.anchorNode;
      let paragraph = text;
      if (anchorNode) {
        const parent = anchorNode.parentElement;
        if (parent) {
          paragraph = (parent.textContent || text).substring(0, 800);
        }
      }
      setInnerSelection({ turnId: turn.id, text, paragraph, x: e.clientX, y: e.clientY });
    }, 10);
  }

  function handleInnerFollowUp() {
    if (!innerSelection) return;
    onInnerFollowUp(innerSelection.turnId, innerSelection.text, innerSelection.paragraph);
    setInnerSelection(null);
  }

  function handleSend() {
    if (!input.trim() || isSending) return;
    onSendQuestion(dialog.id, input.trim());
    setInput("");
  }

  function handleInputKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Enter") {
      e.preventDefault();
      handleSend();
    }
  }

  return (
    <div
      className="fixed bg-white rounded-xl shadow-2xl border border-zinc-300 flex flex-col overflow-hidden"
      style={{ left: pos.x, top: pos.y, width: 440, height: 520, zIndex: dialog.zIndex }}
      onMouseDown={onFocus}
    >
      {/* 标题栏（拖拽把手） */}
      <div
        className="flex items-center gap-2 px-4 py-2.5 bg-gradient-to-r from-blue-50 to-indigo-50 border-b border-zinc-200 cursor-move select-none shrink-0"
        onMouseDown={(e) => handleTitleMouseDown(e, onFocus)}
      >
        <span className="text-sm">💬</span>
        <span className="text-xs font-medium text-zinc-700 truncate flex-1">
          追问: {dialog.selectedText.slice(0, 40)}{dialog.selectedText.length > 40 ? "…" : ""}
        </span>
        <button
          onClick={(e) => { e.stopPropagation(); onClose(); }}
          className="text-zinc-400 hover:text-zinc-600 hover:bg-zinc-200 rounded-full w-5 h-5 flex items-center justify-center text-xs shrink-0 transition-colors"
        >
          ×
        </button>
      </div>

      {/* 问答滚动区 */}
      <div ref={bodyRef} className="flex-1 overflow-auto px-3 py-3 space-y-3">
        {dialog.turns.map((turn) => (
          <div key={turn.id} className="space-y-1.5">
            {/* 用户问题气泡（自动解释轮无 question，不渲染） */}
            {turn.question && (
              <div className="flex justify-end">
                <div className="max-w-[85%] bg-blue-600 text-white rounded-xl px-3 py-2">
                  <p className="text-xs whitespace-pre-wrap leading-relaxed">{turn.question}</p>
                </div>
              </div>
            )}
            {turn.loading ? (
              <div className="flex items-center gap-2.5 py-3">
                <div className="w-5 h-5 border-2 border-blue-400 border-t-transparent rounded-full animate-spin shrink-0" />
                <span className="text-xs text-zinc-400">正在从课件中检索…</span>
              </div>
            ) : (
              <div className="flex justify-start">
                <div className="max-w-[85%] bg-zinc-100 text-zinc-800 rounded-xl px-3 py-2">
                  <div
                    className="text-xs leading-relaxed markdown-body"
                    onMouseUp={(e) => handleTurnMouseUp(turn, e)}
                    style={{ userSelect: "text", cursor: "text" }}
                  >
                    <ReactMarkdown remarkPlugins={[remarkGfm]} components={dialogMarkdownComponents}>
                      {turn.answer}
                    </ReactMarkdown>
                    {turn.citations.length > 0 && (
                      <details className="mt-2 pt-1.5 border-t border-zinc-200">
                        <summary className="text-[11px] text-zinc-400 cursor-pointer hover:text-zinc-600">
                          参考来源（{turn.citations.length} 条）
                        </summary>
                        <div className="mt-1.5 space-y-1.5">
                          {turn.citations.map((cit, j) => (
                            <div key={j} className="bg-white rounded-md p-2 border border-zinc-100">
                              <div className="flex items-center justify-between mb-0.5">
                                <span className="text-[11px] font-medium text-blue-600">
                                  {cit.document_name}{cit.page ? ` · 第${cit.page}页` : ""}
                                </span>
                                <span className="text-[10px] text-zinc-400">
                                  {(cit.score * 100).toFixed(0)}%
                                </span>
                              </div>
                              <p className="text-[11px] text-zinc-500 line-clamp-2">{cit.text}</p>
                            </div>
                          ))}
                        </div>
                      </details>
                    )}
                  </div>
                </div>
              </div>
            )}
          </div>
        ))}

        {/* 对话框内嵌套追问紫色气泡 */}
        {innerSelection && (
          <div
            className="fixed bg-white border border-purple-400 shadow-lg rounded-lg px-3 py-2 flex items-center gap-2"
            style={{ zIndex: topZIndex + 2, left: Math.min(innerSelection.x, window.innerWidth - 120), top: innerSelection.y + 20 }}
          >
            <span className="text-[11px] text-zinc-500 max-w-[200px] truncate">
              追问: &quot;{innerSelection.text.slice(0, 25)}{innerSelection.text.length > 25 ? "…" : ""}&quot;
            </span>
            <button
              onClick={(e) => { e.stopPropagation(); handleInnerFollowUp(); }}
              className="px-2.5 py-1 text-xs bg-purple-600 text-white rounded-md hover:bg-purple-700 transition-colors shrink-0"
            >
              追问
            </button>
            <button
              onClick={(e) => { e.stopPropagation(); setInnerSelection(null); }}
              className="text-zinc-300 hover:text-zinc-500 text-xs shrink-0"
            >
              ×
            </button>
          </div>
        )}
      </div>

      {/* 底部输入框 */}
      <div className="px-3 py-2 border-t border-zinc-200 shrink-0 flex items-center gap-2 bg-white">
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleInputKeyDown}
          placeholder={isSending ? "思考中，稍候…" : "继续提问（Enter 发送）"}
          disabled={isSending}
          className="flex-1 px-3 py-1.5 text-xs border border-zinc-300 rounded-lg focus:outline-none focus:ring-1 focus:ring-blue-500 disabled:bg-zinc-100 disabled:text-zinc-400"
        />
        <button
          onClick={handleSend}
          disabled={!input.trim() || isSending}
          className="px-3.5 py-1.5 text-xs bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-40 shrink-0"
        >
          发送
        </button>
      </div>
    </div>
  );
}
