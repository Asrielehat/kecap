"use client";

import { useState, useRef, useEffect } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

interface Message {
  id?: string;
  role: "user" | "assistant";
  content: string;
  citations?: Citation[];
  agentTrace?: AgentTraceStep[];
  streaming?: boolean;   // 流式生成中：思考面板实时展开、隐藏"思考中"占位
  traceOpen?: boolean;   // 思考面板展开态（流式后保留，用户可自由收/放）
}

/** Agent 运行轨迹单步：检索轮次 / MCP 工具调用 / 兜底 */
interface AgentTraceStep {
  step: number;
  type: "retrieval" | "tool" | "fallback";
  query?: string;
  top_k?: number;
  hits?: number;
  scores?: number[];
  preview?: string;
  content?: string;
  tool?: string;
  args?: string;
  ok?: boolean;
  result_chars?: number;
  note?: string;
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

interface FollowUpModalState {
  id: string;
  followUpId?: string; // 后端返回的 FollowUp 记录 ID，用于嵌套追问
  selectedText: string;
  contextParagraph: string;
  messageId: string;
  answer: string;
  citations: Citation[];
  loading: boolean;
  x: number;
  y: number;
  zIndex: number;
}

// 对话框内的一轮问答（question 为 null 表示自动解释轮）
interface FollowUpTurn {
  id: string;               // 客户端 turn id（对话框内区分轮次）
  followUpId?: string;      // 后端 FollowUp 记录 id（嵌套追问的 parent_follow_up_id 用这个）
  question: string | null;  // 用户该轮的问题；自动解释轮为 null
  answer: string;
  citations: Citation[];
  loading: boolean;
}

// 智能提问对话框：框选文字后打开，问答可无限叠加
interface FollowUpDialogState {
  id: string;
  selectedText: string;     // 对话框锚点：主消息区选中的文字
  contextParagraph: string;
  messageId: string;        // 被追问的 assistant 消息 id（第一轮 POST 用）
  turns: FollowUpTurn[];
  x: number;
  y: number;
  zIndex: number;
}

function genId(): string {
  try { return crypto.randomUUID ? crypto.randomUUID() : String(Date.now()); }
  catch { return String(Date.now()) + "-" + Math.random().toString(36).slice(2, 10); }
}

// EXE/Docker 同源部署时页面由 FastAPI 提供（端口 8000），直接用相对路径 /api；
// 否则（开发模式 :3000 或独立前端）回退到环境变量 / 本地默认地址。
// 注意：不要依赖构建期 NEXT_PUBLIC_API_URL=/api —— Git Bash 会把 /api 误转成 E:/Git/api。
const API_BASE =
  typeof window !== "undefined" && window.location.port === "8000"
    ? "/api"
    : process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api";

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
  const [followUpModals, setFollowUpModals] = useState<FollowUpModalState[]>([]);
  const [followUpDialogs, setFollowUpDialogs] = useState<FollowUpDialogState[]>([]);
  const [selectionData, setSelectionData] = useState<{
    text: string; paragraph: string; messageId: string; x: number; y: number;
  } | null>(null);
  const [topZIndex, setTopZIndex] = useState(200);
  const chatEndRef = useRef<HTMLDivElement>(null);
  const dragCounter = useRef(0);
  const thinkingIntervalRef = useRef<NodeJS.Timeout | null>(null);
  const [thinkingStep, setThinkingStep] = useState(0);
  const [thinkingSecs, setThinkingSecs] = useState(0);
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

  // 思考中文字轮播 + 耗时秒数
  useEffect(() => {
    if (loading) {
      setThinkingStep(0);
      setThinkingSecs(0);
      const interval = setInterval(() => {
        setThinkingStep((prev) => (prev + 1) % thinkingMessages.length);
        setThinkingSecs((prev) => prev + 1);
      }, 1000);
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
          id: m.id,
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

  // 删除单条消息（用户输错 / LLM 答偏时，防止污染后续上下文）
  async function deleteMessage(msgIndex: number) {
    const msg = messages[msgIndex];
    if (!msg.id || !conversationId) return;
    if (!window.confirm("删除这条消息？\n用户输入或 AI 回答都会被移除，之后的问答不再受它影响。")) return;
    try {
      const res = await fetch(`${API_BASE}/conversations/${conversationId}/messages/${msg.id}`, { method: "DELETE" });
      if (!res.ok) {
        console.error("删除消息失败", res.status);
        return;
      }
      setMessages((prev) => prev.filter((_, i) => i !== msgIndex));
      // 关闭挂在被删消息上的追问弹窗/对话框
      setFollowUpModals((prev) => prev.filter((m) => m.messageId !== msg.id));
      setFollowUpDialogs((prev) => prev.filter((d) => d.messageId !== msg.id));
      // 删除的是首条时，对话标题可能已变
      if (selectedCourse) fetchConversations(selectedCourse);
    } catch (e) {
      console.error("删除消息失败", e);
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
    const targetIndex = messages.length + 1;   // 先推用户消息，再推 assistant 占位
    setInput("");
    setLoading(true);
    // 一次性推两条（React 自动批处理）：流式中即见实时内容，无"思考中"闪烁
    setMessages((prev) => [
      ...prev,
      { role: "user", content: question },
      { role: "assistant", content: "", citations: [], agentTrace: [], streaming: true },
    ]);

    // 原地更新第 targetIndex 条（流式期间不重建整个消息数组）
    const patchAssist = (patch: Partial<Message>) =>
      setMessages((prev) => prev.map((m, i) => (i === targetIndex ? { ...m, ...patch } : m)));
    // 用户消息在 targetIndex-1（从 citations 事件拿到后端 id 后回填，用于删除）
    const patchUser = (patch: Partial<Message>) =>
      setMessages((prev) => prev.map((m, i) => (i === targetIndex - 1 ? { ...m, ...patch } : m)));

    let savedId = "";
    try {
      const res = await fetch(`${API_BASE}/chat/ask/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          course_id: selectedCourse,
          question,
          conversation_id: conversationId,
        }),
      });
      if (!res.ok || !res.body) throw new Error(`HTTP ${res.status}`);

      // ── 消费 SSE：思考步骤实时蹦出，答案逐字流式渲染 ──
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buf = "";
      let answer = "";
      let trace: AgentTraceStep[] = [];
      let citations: Citation[] = [];

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        const frames = buf.split("\n\n");
        buf = frames.pop() ?? "";   // 帧尾可能不完整，留到下一轮
        for (const frame of frames) {
          const line = frame.split("\n").find((l) => l.startsWith("data: "));
          if (!line) continue;
          let evt: any;
          try {
            evt = JSON.parse(line.slice(6));
          } catch {
            continue;
          }
          if (evt.type === "trace") {
            trace = [...trace, evt.data];
            patchAssist({ agentTrace: trace });
          } else if (evt.type === "token") {
            answer += evt.data;
            patchAssist({ content: answer });
          } else if (evt.type === "citations") {
            citations = evt.data;
            if (evt.conversation_id) setConversationId(evt.conversation_id);
            if (evt.user_message_id) patchUser({ id: evt.user_message_id });
            patchAssist({ citations });
          } else if (evt.type === "done") {
            savedId = evt.data?.assistant_message_id || "";
          }
        }
      }
    } catch (e) {
      patchAssist({ content: "❌ 请求失败，请检查后端服务是否启动。" });
    } finally {
      patchAssist({ id: savedId || undefined, streaming: false });
      setLoading(false);
      // 刷新对话列表（标题可能更新）
      if (selectedCourse) fetchConversations(selectedCourse);
    }
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  }

  // ── 追问答疑 ──

  function handleMessageSelect(e: React.MouseEvent, msgIndex: number) {
    // 延迟获取选中内容（mouseup 时 Selection 对象尚未就绪）
    setTimeout(() => {
      const sel = window.getSelection();
      if (!sel || !sel.toString().trim()) {
        setSelectionData(null);
        return;
      }
      const text = sel.toString().trim();
      if (text.length < 2 || text.length > 500) {
        setSelectionData(null);
        return;
      }

      const msg = messages[msgIndex];
      if (msg.role !== "assistant") { setSelectionData(null); return; }

      // 获取选中文字所在段落
      const anchorNode = sel.anchorNode;
      let paragraph = "";
      if (anchorNode) {
        const bubble = anchorNode.parentElement?.closest(".markdown-body");
        if (bubble) {
          paragraph = (bubble as HTMLElement).innerText?.substring(0, 1000) || "";
        }
      }
      if (!paragraph) paragraph = text;

      const messageId = (msg as any).id || "";

      setSelectionData({ text, paragraph, messageId, x: e.clientX, y: e.clientY });
    }, 10);
  }

  async function doFollowUp(
    text: string, paragraph: string, messageId: string, parentFollowUpId?: string
  ) {
    if (!selectedCourse) return;
    console.log("[追问] 开始:", { text, messageId, parentFollowUpId });

    let id: string;
    try { id = crypto.randomUUID ? crypto.randomUUID() : String(Date.now()); }
    catch { id = String(Date.now()) + "-" + Math.random().toString(36).slice(2, 10); }
    const newZ = topZIndex + 1;
    setTopZIndex(newZ);

    setFollowUpModals((prev) => [
      ...prev,
      {
        id, selectedText: text, contextParagraph: paragraph,
        messageId, answer: "", citations: [], loading: true,
        x: 180 + prev.length * 30, y: 120 + prev.length * 30, zIndex: newZ,
      },
    ]);

    // 构建请求体：顶层追问传 message_id，嵌套追问传 parent_follow_up_id
    const body: any = {
      selected_text: text,
      context_paragraph: paragraph,
      course_id: selectedCourse,
      conversation_id: conversationId || "",
    };
    if (parentFollowUpId) {
      body.parent_follow_up_id = parentFollowUpId;
    } else {
      body.message_id = messageId;
    }

    try {
      const res = await fetch(`${API_BASE}/chat/follow-up`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      console.log("[追问] 响应状态:", res.status);
      const rawText = await res.text();
      console.log("[追问] 响应原文(前500):", rawText.substring(0, 500));
      const data = JSON.parse(rawText);
      console.log("[追问] answer 长度:", data.answer?.length, "citations:", data.citations?.length);
      setFollowUpModals((prev) =>
        prev.map((m) =>
          m.id === id ? { ...m, followUpId: data.id, answer: data.answer || "(空)", citations: data.citations || [], loading: false } : m
        )
      );
    } catch (err) {
      console.error("追问请求失败:", err);
      setFollowUpModals((prev) =>
        prev.map((m) =>
          m.id === id ? { ...m, answer: "请求失败，请检查后端服务是否启动。", loading: false } : m
        )
      );
    }
  }

  async function handleFollowUp() {
    if (!selectionData) return;
    const { text, paragraph, messageId } = selectionData;
    setSelectionData(null);
    await openFollowUpDialog(text, paragraph, messageId);
  }

  function closeFollowUpModal(id: string) {
    setFollowUpModals((prev) => prev.filter((m) => m.id !== id));
  }

  function bringToFront(id: string) {
    const newZ = topZIndex + 1;
    setTopZIndex(newZ);
    setFollowUpModals((prev) =>
      prev.map((m) => (m.id === id ? { ...m, zIndex: newZ } : m))
    );
  }

  // ── 智能提问对话框 ──

  // 打开对话框并触发第一条自动解释（POST 不带 question）
  async function openFollowUpDialog(text: string, paragraph: string, messageId: string) {
    if (!selectedCourse) return;
    const id = genId();
    const turnId = genId();
    const newZ = topZIndex + 1;
    setTopZIndex(newZ);
    setFollowUpDialogs((prev) => [
      ...prev,
      {
        id,
        selectedText: text,
        contextParagraph: paragraph,
        messageId,
        turns: [{ id: turnId, question: null, answer: "", citations: [], loading: true }],
        x: 160 + prev.length * 30,
        y: 100 + prev.length * 30,
        zIndex: newZ,
      },
    ]);
    await requestFollowUp({ dialogId: id, turnId, text, paragraph, messageId });
  }

  // 统一追问请求 helper：按 dialogId+turnId 回填结果
  async function requestFollowUp(params: {
    dialogId: string;
    turnId: string;
    text: string;
    paragraph: string;
    messageId: string;
    parentFollowUpId?: string;
    question?: string;
    history?: { question: string | null; answer: string }[];
  }) {
    const { dialogId, turnId, text, paragraph, messageId, parentFollowUpId, question, history } = params;
    if (!selectedCourse) return;

    const body: any = {
      selected_text: text,
      context_paragraph: paragraph,
      course_id: selectedCourse,
      conversation_id: conversationId || "",
    };
    if (parentFollowUpId) body.parent_follow_up_id = parentFollowUpId;
    else body.message_id = messageId;
    if (question) body.question = question;
    if (history && history.length > 0) body.history = history;

    try {
      const res = await fetch(`${API_BASE}/chat/follow-up`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = JSON.parse(await res.text());
      setFollowUpDialogs((prev) =>
        prev.map((d) =>
          d.id !== dialogId
            ? d
            : {
                ...d,
                turns: d.turns.map((t) =>
                  t.id === turnId
                    ? { ...t, followUpId: data.id, answer: data.answer || "(空)", citations: data.citations || [], loading: false }
                    : t
                ),
              }
        )
      );
    } catch (err) {
      console.error("追问请求失败:", err);
      setFollowUpDialogs((prev) =>
        prev.map((d) =>
          d.id !== dialogId
            ? d
            : {
                ...d,
                turns: d.turns.map((t) =>
                  t.id === turnId ? { ...t, answer: "请求失败，请检查后端服务是否启动。", loading: false } : t
                ),
              }
        )
      );
    }
  }

  // 对话框内继续提问：追加 turn，parent = 最后一条已完成 turn 的 followUpId
  function submitDialogQuestion(dialogId: string, question: string) {
    const dialog = followUpDialogs.find((d) => d.id === dialogId);
    const last = dialog?.turns[dialog.turns.length - 1];
    if (!dialog || !last?.followUpId) return; // 首条/当前条未完成前禁止继续提问
    const turnId = genId();
    const history = dialog.turns
      .filter((t) => !t.loading)
      .map((t) => ({ question: t.question, answer: t.answer }));
    setFollowUpDialogs((prev) =>
      prev.map((d) =>
        d.id !== dialogId
          ? d
          : { ...d, turns: [...d.turns, { id: turnId, question, answer: "", citations: [], loading: true }] }
      )
    );
    requestFollowUp({
      dialogId,
      turnId,
      text: dialog.selectedText,
      paragraph: dialog.contextParagraph,
      messageId: dialog.messageId,
      parentFollowUpId: last.followUpId,
      question,
      history,
    });
  }

  // 对话框内某条回答再次框选 → 新开独立单答弹窗（复用 doFollowUp，行为保持现状）
  function handleDialogInnerFollowUp(turnId: string, text: string, paragraph: string) {
    const dialog = followUpDialogs.find((d) => d.turns.some((t) => t.id === turnId));
    const turn = dialog?.turns.find((t) => t.id === turnId);
    if (!dialog || !turn?.followUpId) return;
    doFollowUp(text, paragraph, "", turn.followUpId);
  }

  function closeFollowUpDialog(id: string) {
    setFollowUpDialogs((prev) => prev.filter((d) => d.id !== id));
  }

  function bringDialogToFront(id: string) {
    const newZ = topZIndex + 1;
    setTopZIndex(newZ);
    setFollowUpDialogs((prev) => prev.map((d) => (d.id === id ? { ...d, zIndex: newZ } : d)));
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
              className={`flex items-start gap-1.5 group ${msg.role === "user" ? "justify-end" : "justify-start"}`}
            >
              {msg.id && !msg.streaming && (
                <button
                  onClick={() => deleteMessage(i)}
                  title="删除这条消息（防止错误内容污染上下文）"
                  className={`mt-3 shrink-0 text-xs font-medium px-2 py-0.5 rounded-full border transition-colors ${
                    msg.role === "user"
                      ? "order-first text-blue-200 border-blue-300/50 hover:text-red-300 hover:border-red-300"
                      : "order-last text-zinc-500 border-zinc-300 hover:text-red-500 hover:border-red-400 hover:bg-red-50"
                  }`}
                >
                  🗑 删除
                </button>
              )}
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
                    {(msg.streaming || (msg.agentTrace && msg.agentTrace.length > 0)) && (
                      <details
                        open={msg.traceOpen === undefined ? undefined : msg.traceOpen}
                        onToggle={(e) =>
                          setMessages((prev) =>
                            prev.map((m, j) => (j === i ? { ...m, traceOpen: (e.target as HTMLDetailsElement).open } : m))
                          )
                        }
                        className="mb-2 pb-2 border-b border-zinc-300"
                      >
                        <summary className="text-xs text-zinc-500 cursor-pointer hover:text-zinc-700 font-medium">
                          {msg.streaming ? (
                            msg.agentTrace && msg.agentTrace.length > 0 ? (
                              <>🤔 思考中（{thinkingSecs} 秒 · 已完成 {msg.agentTrace.length} 步）…</>
                            ) : (
                              <>🤔 思考中（{thinkingSecs} 秒）…</>
                            )
                          ) : (
                            <>🤖 思考过程（{msg.agentTrace?.length ?? 0} 步）</>
                          )}
                        </summary>
                        <ol className="mt-2 space-y-2">
                          {msg.agentTrace?.map((s, k) => (
                            <li key={k} className="bg-white rounded-lg p-2 border border-zinc-200 text-xs">
                              {s.type === "retrieval" && (
                                <div>
                                  <div className="text-zinc-400">
                                    <span>检索 </span>
                                    <span className="font-mono text-zinc-700">「{s.query}」</span>
                                    <span>
                                      {" "}· top_k={s.top_k} · 命中 {s.hits} 条
                                      {s.scores && s.scores.length > 0 && (
                                        <> · {s.scores.map((sc) => (sc * 100).toFixed(0) + "%").join(", ")}</>
                                      )}
                                    </span>
                                  </div>
                                  {s.content && (
                                    <p className="text-zinc-700 mt-1.5 whitespace-pre-wrap break-words leading-relaxed">
                                      {s.content}
                                    </p>
                                  )}
                                </div>
                              )}
                              {s.type === "tool" && (
                                <div>
                                  <div className="text-zinc-400">
                                    <span>工具 </span>
                                    <span className="font-mono text-zinc-700">{s.tool}</span>
                                    <span>
                                      {" "}· {s.ok ? "成功" : "出错"} · {s.result_chars} 字符
                                      {s.args ? ` · ${s.args}` : ""}
                                    </span>
                                  </div>
                                  {s.content && (
                                    <p className="text-zinc-700 mt-1.5 whitespace-pre-wrap break-words leading-relaxed">
                                      {s.content}
                                    </p>
                                  )}
                                </div>
                              )}
                              {s.type === "fallback" && (
                                <span className="text-amber-600">{s.note}</span>
                              )}
                            </li>
                          ))}
                        </ol>
                      </details>
                    )}

                    <div
                      className="markdown-body"
                      onMouseUp={(e) => handleMessageSelect(e, i)}
                      style={{ userSelect: "text", cursor: "text" }}>
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

          {loading && !messages.some((m) => m.role === "assistant" && m.streaming) && (
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
          {selectionData && (
            <div
              className="fixed bg-white border border-blue-400 shadow-lg rounded-lg px-3 py-2 flex items-center gap-2 animate-[fadeIn_0.15s_ease-out]"
              style={{ zIndex: topZIndex + 1, left: Math.min(selectionData.x, window.innerWidth - 120), top: selectionData.y + 20 }}
            >
              <span className="text-[11px] text-zinc-500 max-w-[200px] truncate">
                追问: "{selectionData.text.slice(0, 30)}{selectionData.text.length > 30 ? "…" : ""}"
              </span>
              <button
                onClick={(e) => { e.stopPropagation(); handleFollowUp(); }}
                className="px-2.5 py-1 text-xs bg-blue-600 text-white rounded-md hover:bg-blue-700 transition-colors shrink-0"
              >
                追问
              </button>
              <button
                onClick={(e) => { e.stopPropagation(); setSelectionData(null); }}
                className="text-zinc-300 hover:text-zinc-500 text-xs shrink-0"
              >
                ×
              </button>
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

      {/* ── 追问弹窗层（拖拽 + 多弹窗管理）── */}
      {followUpModals.map((modal) => (
        <DraggableModal
          key={modal.id}
          modal={modal}
          topZIndex={topZIndex}
          onClose={() => closeFollowUpModal(modal.id)}
          onFocus={() => bringToFront(modal.id)}
          onFollowUp={(text, paragraph, parentId) =>
            doFollowUp(text, paragraph, "", parentId)
          }
        />
      ))}

      {/* ── 智能提问对话框层 ── */}
      {followUpDialogs.map((dialog) => (
        <DraggableDialog
          key={dialog.id}
          dialog={dialog}
          topZIndex={topZIndex}
          onClose={() => closeFollowUpDialog(dialog.id)}
          onFocus={() => bringDialogToFront(dialog.id)}
          onSendQuestion={submitDialogQuestion}
          onInnerFollowUp={handleDialogInnerFollowUp}
        />
      ))}
    </div>
  );
}

// ── 共享拖拽窗口 hook（弹窗 / 对话框共用）──
function useDraggableWindow(initialX: number, initialY: number, width: number) {
  const [pos, setPos] = useState({ x: initialX, y: initialY });
  const [dragging, setDragging] = useState(false);
  const dragRef = useRef({ startX: 0, startY: 0, startLeft: 0, startTop: 0 });

  // 窗口初始位置变更时同步（多弹窗各自来自状态）
  useEffect(() => {
    setPos({ x: initialX, y: initialY });
  }, [initialX, initialY]);

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
function DraggableModal({
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
  useEffect(() => {
    setPos({ x: modal.x, y: modal.y });
  }, [modal.x, modal.y]);

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
                  追问: "{innerSelection.text.slice(0, 25)}{innerSelection.text.length > 25 ? "…" : ""}"
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
                code: ({ className, children, ...props }: any) => {
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
const dialogMarkdownComponents = {
  h1: ({ children }: any) => <h1 className="text-sm font-semibold text-zinc-800 mt-2 mb-1">{children}</h1>,
  h2: ({ children }: any) => <h2 className="text-xs font-semibold text-zinc-800 mt-2 mb-1">{children}</h2>,
  h3: ({ children }: any) => <h3 className="text-xs font-medium text-zinc-700 mt-1.5 mb-0.5">{children}</h3>,
  p: ({ children }: any) => <p className="text-xs text-zinc-700 my-1.5 leading-relaxed">{children}</p>,
  strong: ({ children }: any) => <strong className="font-semibold text-zinc-800">{children}</strong>,
  ul: ({ children }: any) => <ul className="list-disc list-inside my-1 space-y-0.5 text-xs">{children}</ul>,
  ol: ({ children }: any) => <ol className="list-decimal list-inside my-1 space-y-0.5 text-xs">{children}</ol>,
  li: ({ children }: any) => <li className="text-xs text-zinc-700">{children}</li>,
  code: ({ className, children, ...props }: any) => {
    const isInline = !className;
    return isInline
      ? <code className="bg-zinc-200 text-zinc-800 px-1 py-0.5 rounded text-[11px] font-mono">{children}</code>
      : <code className="block bg-zinc-800 text-zinc-100 text-[11px] p-2.5 rounded-lg my-1.5 overflow-x-auto font-mono whitespace-pre-wrap">{children}</code>;
  },
  pre: ({ children }: any) => <>{children}</>,
  a: ({ href, children }: any) => <a href={href} target="_blank" rel="noopener" className="text-blue-600 underline">{children}</a>,
  blockquote: ({ children }: any) => <blockquote className="border-l-3 border-blue-400 bg-blue-50 px-2.5 py-1 my-1.5 text-xs text-zinc-600 rounded-r">{children}</blockquote>,
  hr: () => <hr className="border-zinc-200 my-2" />,
  em: ({ children }: any) => <em className="italic text-zinc-600">{children}</em>,
  table: ({ children }: any) => <div className="overflow-x-auto my-1.5"><table className="w-full text-[11px] border-collapse">{children}</table></div>,
  th: ({ children }: any) => <th className="border border-zinc-300 bg-zinc-100 px-1.5 py-0.5 text-left font-medium text-zinc-700">{children}</th>,
  td: ({ children }: any) => <td className="border border-zinc-300 px-1.5 py-0.5 text-zinc-600">{children}</td>,
};

function DraggableDialog({
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
              追问: "{innerSelection.text.slice(0, 25)}{innerSelection.text.length > 25 ? "…" : ""}"
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
