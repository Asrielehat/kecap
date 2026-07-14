"use client";

import { useState, useRef, useEffect } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

interface Message {
  id?: string;
  role: "user" | "assistant";
  content: string;
  citations?: Citation[];
}

interface Citation {
  text: string;
  document_name: string;
  page?: number;
  chunk_id: string;
  score: number;
}

interface Course {
  id: string;
  name: string;
  document_count: number;
}

interface ConversationItem {
  id: string;
  course_id: string;
  title: string;
  created_at: string;
}

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api";

export default function Home() {
  const [courses, setCourses] = useState<Course[]>([]);
  const [selectedCourse, setSelectedCourse] = useState<string>("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [newCourseName, setNewCourseName] = useState("");
  const [uploading, setUploading] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const [dragTargetCourse, setDragTargetCourse] = useState<string | null>(null);
  const [conversations, setConversations] = useState<ConversationItem[]>([]);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [feedbackMap, setFeedbackMap] = useState<Record<number, string>>({});
  const chatEndRef = useRef<HTMLDivElement>(null);
  const dragCounter = useRef(0);
  const thinkingIntervalRef = useRef<NodeJS.Timeout | null>(null);
  const [thinkingStep, setThinkingStep] = useState(0);
  const thinkingMessages = [
    "🔍 正在检索相关资料...",
    "🤔 正在分析内容相关性...",
    "📝 正在整理答案...",
    "✨ 马上就好...",
  ];

  // ── 初始化 ──
  useEffect(() => {
    fetchCourses();
  }, []);

  // 课程切换时加载对话列表
  useEffect(() => {
    if (selectedCourse) {
      fetchConversations(selectedCourse);
    }
  }, [selectedCourse]);

  // 滚动到最新
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // 思考中文字轮播
  useEffect(() => {
    if (loading) {
      setThinkingStep(0);
      const interval = setInterval(() => {
        setThinkingStep((prev) => (prev + 1) % thinkingMessages.length);
      }, 2500);
      thinkingIntervalRef.current = interval;
    } else {
      if (thinkingIntervalRef.current) {
        clearInterval(thinkingIntervalRef.current);
        thinkingIntervalRef.current = null;
      }
    }
    return () => {
      if (thinkingIntervalRef.current) {
        clearInterval(thinkingIntervalRef.current);
      }
    };
  }, [loading]);

  // ── API 调用 ──

  async function fetchCourses() {
    try {
      const res = await fetch(`${API_BASE}/courses/`);
      const data = await res.json();
      setCourses(data);
    } catch (e) {
      console.error("获取课程列表失败", e);
    }
  }

  async function fetchConversations(courseId: string) {
    try {
      const res = await fetch(`${API_BASE}/conversations/${courseId}`);
      const data = await res.json();
      setConversations(data);
    } catch (e) {
      console.error("获取对话列表失败", e);
    }
  }

  async function loadConversation(convId: string) {
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/conversations/${convId}/messages`);
      const data = await res.json();
      setConversationId(data.conversation_id);
      setSelectedCourse(data.course_id);
      setMessages(
        data.messages.map((m: any) => ({
          role: m.role,
          content: m.content,
          citations: m.citations,
        }))
      );
    } catch (e) {
      console.error("加载对话失败", e);
    } finally {
      setLoading(false);
    }
  }

  function startNewConversation() {
    setMessages([]);
    setConversationId(null);
  }

  async function deleteConversation(convId: string) {
    setDeletingId(convId);
    try {
      await fetch(`${API_BASE}/conversations/${convId}`, { method: "DELETE" });
      setConversations((prev) => prev.filter((c) => c.id !== convId));
      if (conversationId === convId) {
        startNewConversation();
      }
    } catch (e) {
      console.error("删除对话失败", e);
    } finally {
      setDeletingId(null);
    }
  }

  async function handleCreateCourse() {
    if (!newCourseName.trim()) return;
    try {
      const res = await fetch(`${API_BASE}/courses/`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: newCourseName.trim() }),
      });
      if (res.ok) {
        setNewCourseName("");
        await fetchCourses();
      }
    } catch (e) {
      console.error("创建课程失败", e);
    }
  }

  async function handleUpload(courseId: string, file: File) {
    setUploading(courseId);
    try {
      const formData = new FormData();
      formData.append("file", file);
      formData.append("course_id", courseId);
      const res = await fetch(`${API_BASE}/documents/upload`, {
        method: "POST",
        body: formData,
      });
      const data = await res.json();
      if (res.ok) {
        await fetchCourses();
        if (!selectedCourse) setSelectedCourse(courseId);
        alert(`上传成功！${data.filename} → ${data.chunk_count} 个文本块已索引`);
      } else {
        alert(`上传失败: ${data.detail || JSON.stringify(data)}`);
      }
    } catch (e: any) {
      alert(`上传出错: ${e.message || "网络错误，请确认后端已启动"}`);
      console.error("上传失败", e);
    } finally {
      setUploading(null);
    }
  }

  async function handleSend() {
    if (!input.trim() || !selectedCourse || loading) return;

    const question = input.trim();
    setInput("");
    setMessages((prev) => [...prev, { role: "user", content: question }]);
    setLoading(true);

    try {
      const res = await fetch(`${API_BASE}/chat/ask`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          course_id: selectedCourse,
          question,
          conversation_id: conversationId,
        }),
      });
      const data = await res.json();
      setConversationId(data.conversation_id);
      // 刷新对话列表（标题可能更新）
      if (selectedCourse) fetchConversations(selectedCourse);
      setMessages((prev) => [
        ...prev,
        {
          id: data.assistant_message_id,
          role: "assistant",
          content: data.answer,
          citations: data.citations,
        },
      ]);
    } catch (e) {
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: "❌ 请求失败，请检查后端服务是否启动。" },
      ]);
    } finally {
      setLoading(false);
    }
  }

  async function handleFeedback(msgIndex: number, msgId: string | undefined, fb: string) {
    // 找到对应消息的 id（从 citations 推断）
    setFeedbackMap((prev) => ({ ...prev, [msgIndex]: fb }));
    // 消息 id 存储在 data 属性中
    if (msgId) {
      try {
        await fetch(`${API_BASE}/feedback/${msgId}?feedback=${fb}`, { method: "POST" });
      } catch (e) { console.error("反馈失败", e); }
    }
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  }

  // ── 拖拽上传 ──
  function handleDragEnter(e: React.DragEvent) {
    e.preventDefault();
    e.stopPropagation();
    dragCounter.current++;
    setDragOver(true);
  }

  function handleDragLeave(e: React.DragEvent) {
    e.preventDefault();
    e.stopPropagation();
    dragCounter.current--;
    if (dragCounter.current <= 0) {
      dragCounter.current = 0;
      setDragOver(false);
      setDragTargetCourse(null);
    }
  }

  function handleDragOver(e: React.DragEvent) {
    e.preventDefault();
    e.stopPropagation();
  }

  function handleDrop(e: React.DragEvent, courseId?: string) {
    e.preventDefault();
    e.stopPropagation();
    dragCounter.current = 0;
    setDragOver(false);
    setDragTargetCourse(null);

    const files = e.dataTransfer.files;
    if (files.length === 0) return;

    const targetCourse = courseId || dragTargetCourse || selectedCourse;
    if (!targetCourse) {
      alert("请先在左侧选择或创建一个课程");
      return;
    }

    Array.from(files).forEach((file) => handleUpload(targetCourse, file));
  }

  return (
    <div
      className="flex h-full bg-white relative"
      onDragEnter={handleDragEnter}
      onDragLeave={handleDragLeave}
      onDragOver={handleDragOver}
      onDrop={(e) => handleDrop(e)}
    >
      {/* 全屏拖拽提示覆盖层 */}
      {dragOver && (
        <div className="absolute inset-0 z-50 bg-blue-600/10 backdrop-blur-sm flex items-center justify-center pointer-events-none">
          <div className="bg-white rounded-2xl shadow-xl px-10 py-8 text-center border-2 border-blue-400 border-dashed">
            <p className="text-5xl mb-4">📂</p>
            <p className="text-xl font-bold text-blue-600">释放文件以上传</p>
            <p className="text-sm text-zinc-500 mt-2">
              {dragTargetCourse
                ? `上传至「${courses.find((c) => c.id === dragTargetCourse)?.name}」`
                : selectedCourse
                  ? `上传至「${courses.find((c) => c.id === selectedCourse)?.name}」`
                  : "请先将文件拖到左侧课程上"}
            </p>
            <p className="text-xs text-zinc-400 mt-3">支持 PDF · PPT · Word · Markdown · TXT</p>
          </div>
        </div>
      )}

      {/* ── 侧边栏 ── */}
      <aside
        className={`${
          sidebarOpen ? "w-72" : "w-0"
        } transition-all duration-200 border-r border-zinc-200 bg-zinc-50 flex flex-col overflow-hidden shrink-0`}
      >
        {/* ── 未选课程：首页侧栏 ── */}
        {!selectedCourse && (
          <>
            <div className="p-4 border-b border-zinc-200">
              <h1 className="text-lg font-bold text-zinc-800">📚 课答</h1>
            </div>
            <div className="p-3 flex-1 overflow-auto space-y-4">
              {/* 创建课程 */}
              <div>
                <div className="flex gap-1">
                  <input
                    type="text"
                    value={newCourseName}
                    onChange={(e) => setNewCourseName(e.target.value)}
                    onKeyDown={(e) => e.key === "Enter" && handleCreateCourse()}
                    placeholder="输入课程名..."
                    className="flex-1 px-2 py-1.5 text-xs border border-zinc-300 rounded-md focus:outline-none focus:ring-1 focus:ring-blue-500"
                  />
                  <button
                    onClick={handleCreateCourse}
                    disabled={!newCourseName.trim()}
                    className="px-2 py-1.5 text-xs bg-blue-600 text-white rounded-md hover:bg-blue-700 disabled:opacity-40 shrink-0"
                  >
                    + 创建
                  </button>
                </div>
              </div>

              {/* 课程列表 */}
              <div>
                <h2 className="text-xs font-semibold text-zinc-500 uppercase tracking-wider mb-2">
                  课程列表
                </h2>
                {courses.length === 0 && (
                  <p className="text-xs text-zinc-400">暂无课程，请先创建</p>
                )}
                {courses.map((c) => (
                  <div
                    key={c.id}
                    className={`mb-1 rounded-lg transition-colors ${
                      dragTargetCourse === c.id ? "bg-blue-100 ring-2 ring-blue-400" : ""
                    }`}
                    onDragEnter={(e) => {
                      e.preventDefault();
                      e.stopPropagation();
                      setDragTargetCourse(c.id);
                    }}
                    onDragLeave={(e) => {
                      e.preventDefault();
                      e.stopPropagation();
                      setDragTargetCourse(null);
                    }}
                    onDragOver={(e) => {
                      e.preventDefault();
                      e.stopPropagation();
                    }}
                    onDrop={(e) => handleDrop(e, c.id)}
                  >
                    <button
                      onClick={() => {
                        setSelectedCourse(c.id);
                        setMessages([]);
                        setConversationId(null);
                      }}
                      className="w-full text-left px-3 py-2 rounded-lg text-sm hover:bg-zinc-200 text-zinc-700 transition-colors"
                    >
                      <div className="truncate">{c.name}</div>
                      <div className="text-xs text-zinc-400">{c.document_count} 份文档</div>
                    </button>
                    <div className="px-3 pb-1">
                      <label
                        className={`block w-full text-center text-xs py-1 rounded border border-dashed cursor-pointer transition-colors ${
                          uploading === c.id
                            ? "border-blue-400 bg-blue-50 text-blue-600"
                            : "border-zinc-300 text-zinc-400 hover:border-zinc-400 hover:text-zinc-500"
                        }`}
                      >
                        {uploading === c.id ? "上传中..." : "+ 上传文档 / 拖到此处"}
                        <input
                          type="file"
                          className="hidden"
                          accept=".pdf,.ppt,.pptx,.doc,.docx,.md,.txt"
                          multiple
                          onChange={(e) => {
                            const files = e.target.files;
                            if (files && files.length > 0) {
                              Array.from(files).forEach((file) => handleUpload(c.id, file));
                            }
                          }}
                        />
                      </label>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </>
        )}

        {/* ── 已选课程：课程模式侧栏 ── */}
        {selectedCourse && (
          <>
            <div className="p-3 border-b border-zinc-200">
              <button
                onClick={() => {
                  setSelectedCourse("");
                  setMessages([]);
                  setConversationId(null);
                }}
                className="text-xs text-blue-600 hover:text-blue-800 mb-1 flex items-center gap-0.5"
              >
                ← 返回课程列表
              </button>
              <h1 className="text-base font-bold text-zinc-800 truncate">
                {courses.find((c) => c.id === selectedCourse)?.name || "课程"}
              </h1>
              <div className="flex items-center gap-2 mt-1">
                <span className="text-xs text-zinc-400">
                  {courses.find((c) => c.id === selectedCourse)?.document_count || 0} 份文档
                </span>
                <label
                  className={`text-xs px-2 py-0.5 rounded border border-dashed cursor-pointer transition-colors ${
                    uploading === selectedCourse
                      ? "border-blue-400 bg-blue-50 text-blue-600"
                      : "border-zinc-300 text-zinc-400 hover:border-zinc-400 hover:text-zinc-500"
                  }`}
                >
                  {uploading === selectedCourse ? "上传中..." : "+ 上传文档"}
                  <input
                    type="file"
                    className="hidden"
                    accept=".pdf,.ppt,.pptx,.doc,.docx,.md,.txt"
                    multiple
                    onChange={(e) => {
                      const files = e.target.files;
                      if (files && files.length > 0) {
                        Array.from(files).forEach((file) => handleUpload(selectedCourse!, file));
                      }
                    }}
                  />
                </label>
              </div>
            </div>

            <div className="p-3 flex-1 overflow-auto space-y-3">
              {/* 历史对话 */}
              <div>
                <div className="flex items-center justify-between mb-2">
                  <h2 className="text-xs font-semibold text-zinc-500 uppercase tracking-wider">
                    历史对话
                  </h2>
                  <button
                    onClick={startNewConversation}
                    className="text-xs text-blue-600 hover:text-blue-800 font-medium"
                  >
                    + 新对话
                  </button>
                </div>
                {conversations.length === 0 && (
                  <p className="text-xs text-zinc-400">暂无历史对话</p>
                )}
                <div className="space-y-0.5">
                  {conversations.map((conv) => (
                    <div
                      key={conv.id}
                      className={`group flex items-center rounded-md transition-colors ${
                        conversationId === conv.id
                          ? "bg-blue-100"
                          : "hover:bg-zinc-200"
                      }`}
                    >
                      <button
                        onClick={() => loadConversation(conv.id)}
                        className="flex-1 text-left px-2 py-1.5 text-xs truncate text-zinc-600 hover:text-zinc-800"
                      >
                        <span className="block truncate">{conv.title}</span>
                        <span className="text-zinc-400 text-[10px]">
                          {new Date(conv.created_at).toLocaleDateString("zh-CN", {
                            month: "short",
                            day: "numeric",
                            hour: "2-digit",
                            minute: "2-digit",
                          })}
                        </span>
                      </button>
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          if (confirm("确定删除此对话？")) deleteConversation(conv.id);
                        }}
                        disabled={deletingId === conv.id}
                        className="px-1.5 py-0.5 text-zinc-400 hover:text-red-500 opacity-0 group-hover:opacity-100 transition-opacity text-xs shrink-0"
                        title="删除对话"
                      >
                        {deletingId === conv.id ? "..." : "🗑"}
                      </button>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </>
        )}

        <button
          onClick={() => setSidebarOpen(!sidebarOpen)}
          className="p-2 text-xs text-zinc-400 hover:text-zinc-600 border-t border-zinc-200"
        >
          {sidebarOpen ? "◀ 收起侧栏" : "▶"}
        </button>
      </aside>

      {/* ── 主聊天区域 ── */}
      <main className="flex-1 flex flex-col min-w-0">
        {/* 顶栏 */}
        <header className="px-6 py-3 border-b border-zinc-200 bg-white shrink-0">
          <div className="flex items-center gap-3">
            {!sidebarOpen && (
              <button
                onClick={() => setSidebarOpen(true)}
                className="text-zinc-500 hover:text-zinc-700"
              >
                ▶
              </button>
            )}
            <h2 className="font-semibold text-zinc-800">
              {selectedCourse
                ? courses.find((c) => c.id === selectedCourse)?.name || "对话"
                : "请先选择一门课程"}
            </h2>
            {conversationId && conversations.length > 0 && (
              <span className="text-xs text-zinc-400 bg-zinc-100 px-2 py-0.5 rounded">
                {
                  conversations.find((c) => c.id === conversationId)?.title?.slice(0, 25)
                }
              </span>
            )}
          </div>
        </header>

        {/* 消息列表 */}
        <div className="flex-1 overflow-auto px-6 py-4 space-y-6">
          {messages.length === 0 && selectedCourse && (
            <div className="flex items-center justify-center h-full">
              <div className="text-center text-zinc-400">
                <p className="text-4xl mb-3">💬</p>
                <p className="text-lg font-medium">开始提问</p>
                <p className="text-sm mt-1">基于课程资料的 AI 答疑，每句答案可溯源</p>
                <div className="mt-4 grid grid-cols-2 gap-2 max-w-md mx-auto">
                  {["二叉树有哪三种遍历方式？", "请总结第三章的核心概念"].map((q) => (
                    <button
                      key={q}
                      onClick={() => setInput(q)}
                      className="text-xs text-left px-3 py-2 border border-zinc-200 rounded-lg hover:bg-zinc-50 text-zinc-600 transition-colors"
                    >
                      {q}
                    </button>
                  ))}
                </div>
              </div>
            </div>
          )}

          {!selectedCourse && (
            <div className="flex items-center justify-center h-full">
              <div className="text-center text-zinc-400">
                <p className="text-5xl mb-4">📚</p>
                <p className="text-lg font-medium">欢迎使用课答</p>
                <p className="text-sm mt-2">请先在左侧选择一个课程开始提问</p>
              </div>
            </div>
          )}

          {messages.map((msg, i) => (
            <div
              key={i}
              className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}
            >
              <div
                className={`max-w-[80%] rounded-2xl px-5 py-3 ${
                  msg.role === "user"
                    ? "bg-blue-600 text-white"
                    : "bg-zinc-100 text-zinc-800"
                }`}
              >
                {msg.role === "user" && (
                  <p className="whitespace-pre-wrap text-sm leading-relaxed">{msg.content}</p>
                )}

                {msg.role === "assistant" && (
                  <div className="text-sm leading-relaxed">
                    <div className="markdown-body">
                      <ReactMarkdown
                        remarkPlugins={[remarkGfm]}
                        components={{
                          h1: ({ children }) => <h1 className="text-base font-semibold text-zinc-800 mt-3 mb-1.5 pb-1 border-b border-zinc-200">{children}</h1>,
                          h2: ({ children }) => <h2 className="text-sm font-semibold text-zinc-800 mt-2.5 mb-1">{children}</h2>,
                          h3: ({ children }) => <h3 className="text-sm font-medium text-zinc-700 mt-2 mb-1">{children}</h3>,
                          p: ({ children }) => <p className="text-sm text-zinc-700 my-1.5 leading-relaxed">{children}</p>,
                          strong: ({ children }) => <strong className="font-semibold text-zinc-800">{children}</strong>,
                          ul: ({ children }) => <ul className="list-disc list-inside my-1.5 space-y-0.5">{children}</ul>,
                          ol: ({ children }) => <ol className="list-decimal list-inside my-1.5 space-y-0.5">{children}</ol>,
                          li: ({ children }) => <li className="text-sm text-zinc-700">{children}</li>,
                          code: ({ className, children, ...props }: any) => {
                            const isInline = !className;
                            return isInline
                              ? <code className="bg-zinc-200 text-zinc-800 px-1 py-0.5 rounded text-xs font-mono">{children}</code>
                              : <code className="block bg-zinc-800 text-zinc-100 text-xs p-3 rounded-lg my-2 overflow-x-auto font-mono whitespace-pre-wrap">{children}</code>;
                          },
                          pre: ({ children }) => <>{children}</>,
                          a: ({ href, children }) => <a href={href} target="_blank" rel="noopener" className="text-blue-600 underline hover:text-blue-800">{children}</a>,
                          table: ({ children }) => <div className="overflow-x-auto my-2"><table className="w-full text-xs border-collapse">{children}</table></div>,
                          th: ({ children }) => <th className="border border-zinc-300 bg-zinc-100 px-2 py-1 text-left font-medium text-zinc-700">{children}</th>,
                          td: ({ children }) => <td className="border border-zinc-300 px-2 py-1 text-zinc-600">{children}</td>,
                          blockquote: ({ children }) => <blockquote className="border-l-4 border-blue-400 bg-blue-50 px-3 py-1.5 my-2 text-sm text-zinc-600 rounded-r">{children}</blockquote>,
                          hr: () => <hr className="border-zinc-200 my-3" />,
                          em: ({ children }) => <em className="italic text-zinc-700">{children}</em>,
                          del: ({ children }) => <del className="line-through text-zinc-400">{children}</del>,
                        }}
                      >
                        {msg.content}
                      </ReactMarkdown>
                    </div>

                    {/* 操作按钮 */}
                    <div className="flex items-center gap-2 mt-2 pt-2 border-t border-zinc-300 flex-wrap">
                      <span className="text-[10px] text-zinc-400">搞懂了吗？</span>
                      <button
                        onClick={() => handleFeedback(i, (msg as any).id, "understood")}
                        className={`text-xs px-2 py-0.5 rounded-full transition-colors ${
                          feedbackMap[i] === "understood"
                            ? "bg-green-500 text-white"
                            : "bg-zinc-200 text-zinc-600 hover:bg-green-100 hover:text-green-700"
                        }`}
                      >
                        懂了
                      </button>
                      <button
                        onClick={() => handleFeedback(i, (msg as any).id, "confused")}
                        className={`text-xs px-2 py-0.5 rounded-full transition-colors ${
                          feedbackMap[i] === "confused"
                            ? "bg-orange-500 text-white"
                            : "bg-zinc-200 text-zinc-600 hover:bg-orange-100 hover:text-orange-700"
                        }`}
                      >
                        还不懂
                      </button>
                    </div>

                    {msg.citations && msg.citations.length > 0 && (
                      <details className="mt-3 pt-3 border-t border-zinc-300">
                        <summary className="text-xs text-zinc-500 cursor-pointer hover:text-zinc-700 font-medium">
                          📖 参考来源（{msg.citations.length} 条）
                        </summary>
                        <div className="mt-2 space-y-2">
                          {msg.citations.map((cit, j) => (
                            <div
                              key={j}
                              className="bg-white rounded-lg p-2 border border-zinc-200"
                            >
                              <div className="flex items-center justify-between mb-1">
                                <span className="text-xs font-medium text-blue-600">
                                  📄 {cit.document_name}
                                  {cit.page ? ` · 第 ${cit.page} 页` : ""}
                                </span>
                                <span className="text-xs text-zinc-400">
                                  相关度 {(cit.score * 100).toFixed(0)}%
                                </span>
                              </div>
                              <p className="text-xs text-zinc-600 line-clamp-3">{cit.text}</p>
                            </div>
                          ))}
                        </div>
                      </details>
                    )}
                  </div>
                )}
              </div>
            </div>
          ))}

          {loading && (
            <div className="flex justify-start">
              <div className="bg-gradient-to-br from-zinc-50 to-blue-50 rounded-2xl px-5 py-4 border border-zinc-200/60 shadow-sm max-w-sm">
                <div className="flex items-center gap-3 mb-2">
                  <div className="relative w-8 h-8 shrink-0">
                    <div className="absolute inset-0 bg-blue-500 rounded-full animate-ping opacity-20" />
                    <div className="relative w-8 h-8 bg-blue-100 rounded-full flex items-center justify-center">
                      <span className="text-lg animate-pulse">🧠</span>
                    </div>
                  </div>
                  <div className="flex gap-1">
                    <span className="w-1.5 h-1.5 bg-blue-400 rounded-full animate-bounce" />
                    <span className="w-1.5 h-1.5 bg-blue-400 rounded-full animate-bounce [animation-delay:0.2s]" />
                    <span className="w-1.5 h-1.5 bg-blue-400 rounded-full animate-bounce [animation-delay:0.4s]" />
                  </div>
                </div>
                <p className="text-xs text-zinc-500 transition-opacity duration-500">
                  {thinkingMessages[thinkingStep]}
                </p>
                <div className="flex gap-1.5 mt-2">
                  {thinkingMessages.map((_, i) => (
                    <div
                      key={i}
                      className={`h-1 flex-1 rounded-full transition-all duration-500 ${
                        i === thinkingStep
                          ? "bg-blue-500"
                          : i < thinkingStep
                            ? "bg-blue-300"
                            : "bg-zinc-200"
                      }`}
                    />
                  ))}
                </div>
              </div>
            </div>
          )}
          <div ref={chatEndRef} />
        </div>

        {/* 输入区域 */}
        <div className="px-6 py-4 border-t border-zinc-200 bg-white shrink-0">
          <div className="flex gap-3 max-w-4xl mx-auto">
            <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={
                selectedCourse
                  ? "输入你的问题（Enter 发送，Shift+Enter 换行）"
                  : "请先选择课程"
              }
              disabled={!selectedCourse || loading}
              className="flex-1 px-4 py-2.5 border border-zinc-300 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent disabled:bg-zinc-100 disabled:text-zinc-400"
            />
            <button
              onClick={handleSend}
              disabled={!input.trim() || !selectedCourse || loading}
              className="px-6 py-2.5 bg-blue-600 text-white rounded-xl text-sm font-medium hover:bg-blue-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors shrink-0"
            >
              {loading ? "思考中…" : "发送"}
            </button>
          </div>
          <p className="text-xs text-zinc-400 text-center mt-2">
            答案基于已上传课程资料生成 · 每句标注来源 · 对话自动保存到左侧历史记录
          </p>
        </div>
      </main>
    </div>
  );
}
