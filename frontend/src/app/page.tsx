"use client";

import { useState, useRef, useEffect } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import type { Message, AgentTraceStep, Course, ConversationItem, FollowUpModalState, FollowUpDialogState } from "../lib/types";
import { API_BASE, apiJson } from "../lib/api";
import { consumeStream } from "../lib/chat-stream";
import { CitationList } from "../components/CitationList";
import { UploadProgress } from "../components/UploadProgress";
import { DraggableModal, DraggableDialog } from "../components/FollowUpWindows";

function genId(): string {
  try { return crypto.randomUUID ? crypto.randomUUID() : String(Date.now()); }
  catch { return String(Date.now()) + "-" + Math.random().toString(36).slice(2, 10); }
}

export default function Home() {
  const activeRequest = useRef<AbortController | null>(null);
  const viewEpoch = useRef(0);
  const [generationStatus, setGenerationStatus] = useState("");
  const [evidenceMode, setEvidenceMode] = useState<"strict" | "supplement">("supplement");
  const [uploadLabel, setUploadLabel] = useState("");
  function stopGeneration() {
    activeRequest.current?.abort();
    activeRequest.current = null;
    viewEpoch.current++;
    setMessages(prev => prev.map(m => m.streaming ? {...m, streaming: false, status: "interrupted", error: "已停止生成，可重新提问"} : m));
    setLoading(false);
    setGenerationStatus("");
  }
  useEffect(() => () => { activeRequest.current?.abort(); }, []);
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
  const [deletingCourse, setDeletingCourse] = useState<string | null>(null);
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
      const interval = setInterval(() => {
        setThinkingStep((prev) => (prev + 1) % 4);
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
    stopGeneration();
    const epoch = viewEpoch.current;
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/conversations/${convId}/messages`);
      const data = await res.json();
      if (epoch !== viewEpoch.current) return;
      setConversationId(data.conversation_id);
      setSelectedCourse(data.course_id);
      setMessages(
        data.messages.map((m: Message) => ({
          id: m.id,
          role: m.role,
          content: m.content,
          citations: m.citations,
          status: m.status,
          error: m.status && m.status !== "complete" ? "此回答未完成，可重新提问" : undefined,
        }))
      );
    } catch (e) {
      console.error("加载对话失败", e);
    } finally {
      if (epoch === viewEpoch.current) setLoading(false);
    }
  }

  function startNewConversation() {
    stopGeneration();
    setMessages([]);
    setConversationId(null);
  }

  async function deleteConversation(convId: string) {
    stopGeneration();
    setDeletingId(convId);
    try {
      await apiJson(`/conversations/${convId}`, { method: "DELETE" });
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

  // 删除课程（连同文档、向量、对话、追问和上传文件，不可恢复）
  async function deleteCourse(courseId: string) {
    stopGeneration();
    if (!window.confirm("删除此课程？\n课程、文档、对话和向量数据都会被移除，且不可恢复。")) return;
    setDeletingCourse(courseId);
    try {
      const res = await fetch(`${API_BASE}/courses/${courseId}`, { method: "DELETE" });
      if (!res.ok) {
        console.error("删除课程失败", res.status);
        return;
      }
      await fetchCourses();
      if (selectedCourse === courseId) {
        setSelectedCourse("");
        setMessages([]);
        setConversationId(null);
        setConversations([]);
      }
    } catch (e) {
      console.error("删除课程失败", e);
    } finally {
      setDeletingCourse(null);
    }
  }

  // 删除单条消息（用户输错 / LLM 答偏时，防止污染后续上下文）
  async function deleteMessage(msgIndex: number) {
    stopGeneration();
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
    if (uploading) return;
    setUploading(courseId);
    const uploadId = crypto.randomUUID();
    setUploadLabel("正在上传 " + file.name);
    const labels: Record<string, string> = {uploading: "上传中", parsing: "解析中", indexing: "建立索引", saving: "保存中", success: "完成", failed: "失败", cleanup_pending: "清理中"};
    const timer = setInterval(() => {
      void apiJson<{status: string; progress: number}>(`/documents/jobs/${uploadId}`).then(job => setUploadLabel(`${file.name} · ${labels[job.status] || job.status} ${job.progress}%`)).catch(() => undefined);
    }, 1000);
    try {
      const formData = new FormData();
      formData.append("file", file);
      formData.append("course_id", courseId);
      formData.append("upload_id", uploadId);
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
    } catch (e) {
      alert(`上传出错: ${e instanceof Error ? e.message : "网络错误，请确认后端已启动"}`);
      console.error("上传失败", e);
    } finally {
      clearInterval(timer);
      setUploadLabel("");
      setUploading(null);
    }
  }

  async function handleSend() {
    if (!input.trim() || !selectedCourse || loading) return;
    const question = input.trim();
    const course = selectedCourse;
    const epoch = ++viewEpoch.current;
    const controller = new AbortController();
    activeRequest.current = controller;
    const userId = genId(), assistantId = genId();
    const current = () => viewEpoch.current === epoch && !controller.signal.aborted;
    const patch = (id: string, value: Partial<Message>) => {
      if (current()) setMessages(prev => prev.map(m => m.clientId === id ? {...m, ...value} : m));
    };
    setInput(""); setThinkingStep(0); setThinkingSecs(0); setLoading(true); setGenerationStatus("正在连接");
    setMessages(prev => [...prev, {clientId: userId, role: "user", content: question},
      {clientId: assistantId, role: "assistant", content: "", streaming: true, citations: []}]);
    let answer = "", reasoning = "", savedId = "", failure = "";
    let trace: AgentTraceStep[] = [];
    try {
      const response = await fetch(API_BASE + "/chat/ask/stream", {
        method: "POST", headers: {"Content-Type": "application/json"}, signal: controller.signal,
        body: JSON.stringify({course_id: course, question, conversation_id: conversationId, evidence_mode: evidenceMode}),
      });
      if (!response.ok || !response.body) throw new Error("请求失败 (" + response.status + ")");
      await consumeStream(response.body, event => {
        if (!current()) return;
        if (event.type === "session") {
          setConversationId(event.conversation_id); patch(userId, {id: event.user_message_id});
        } else if (event.type === "token") { answer += event.data; patch(assistantId, {content: answer}); }
        else if (event.type === "reasoning") { reasoning += event.data; patch(assistantId, {reasoning}); }
        else if (event.type === "trace") { trace = [...trace, event.data]; patch(assistantId, {agentTrace: trace}); }
        else if (event.type === "citations") patch(assistantId, {citations: event.data});
        else if (event.type === "status") setGenerationStatus(event.data);
        else if (event.type === "error") { failure = event.data; patch(assistantId, {error: failure, status: "failed"}); }
        else if (event.type === "done") {
          savedId = event.data.assistant_message_id;
          patch(assistantId, {id: savedId || undefined, status: event.data.status});
          if (event.data.status !== "complete" && !failure) failure = "回答未完成或保存失败，请重试";
        }
      });
    } catch (error) {
      failure = error instanceof Error ? error.message : "网络错误，请重试";
    } finally {
      if (current()) {
        patch(assistantId, {id: savedId || undefined, streaming: false, error: failure || undefined});
        setLoading(false); setGenerationStatus(""); activeRequest.current = null;
        void fetchConversations(course);
      }
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

      const messageId = msg.id || "";

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
    const body: Record<string, unknown> = {
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

    const body: Record<string, unknown> = {
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
                    className={`group mb-1 rounded-lg transition-colors ${
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
                    <div className="flex items-center">
                      <button
                        onClick={() => {
                          stopGeneration();
                          setSelectedCourse(c.id);
                          setMessages([]);
                          setConversationId(null);
                        }}
                        className="flex-1 text-left px-3 py-2 rounded-lg text-sm hover:bg-zinc-200 text-zinc-700 transition-colors"
                      >
                        <div className="truncate">{c.name}</div>
                        <div className="text-xs text-zinc-400">{c.document_count} 份文档</div>
                      </button>
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          deleteCourse(c.id);
                        }}
                        disabled={deletingCourse === c.id}
                        className="px-2 mr-1 py-1 text-zinc-400 hover:text-red-500 opacity-0 group-hover:opacity-100 transition-opacity text-sm shrink-0"
                        title="删除课程"
                      >
                        {deletingCourse === c.id ? "..." : "🗑"}
                      </button>
                    </div>
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
                  stopGeneration();
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
                                      {" "}
                                      {s.top_k != null && <>· top_k={s.top_k} </>}
                                      · 命中 {s.hits ?? 0} 条
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
                              {s.type === "plan" && (
                                <div>
                                  <div className="text-zinc-400">
                                    <span>规划 </span>
                                    {s.sub_questions && s.sub_questions.length > 0 ? (
                                      <span className="font-mono text-zinc-700">
                                        {s.sub_questions.join(" ｜ ")}
                                      </span>
                                    ) : (
                                      s.note
                                    )}
                                  </div>
                                  {s.note && s.sub_questions && s.sub_questions.length > 0 && (
                                    <p className="text-zinc-700 mt-1">{s.note}</p>
                                  )}
                                </div>
                              )}
                              {s.type === "selfcheck" && (
                                <div>
                                  <div className="text-zinc-400">
                                    <span>质检 </span>
                                    <span className="text-zinc-700">{s.note}</span>
                                  </div>
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

                    {msg.reasoning != null && msg.reasoning.length > 0 && (
                      <details
                        open={msg.reasoningOpen === undefined ? msg.streaming : msg.reasoningOpen}
                        onToggle={(e) =>
                          setMessages((prev) =>
                            prev.map((m, j) => (j === i ? { ...m, reasoningOpen: (e.target as HTMLDetailsElement).open } : m))
                          )
                        }
                        className="mb-2 pb-2 border-b border-zinc-200"
                      >
                        <summary className="text-xs text-zinc-500 cursor-pointer hover:text-zinc-700 font-medium">
                          💭 深度思考
                        </summary>
                        <p className="mt-2 whitespace-pre-wrap break-words leading-relaxed text-sm text-zinc-500 italic">
                          {msg.reasoning}
                        </p>
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
                          code: ({ className, children }) => {
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

                    {msg.error && <div role="alert" className="text-sm text-red-600 mt-2">{msg.error}
                      <button className="ml-3 underline" onClick={() => setInput(messages.slice(0, i).reverse().find(m => m.role === "user")?.content || "")}>重新提问</button>
                    </div>}
                    <CitationList citations={msg.citations || []} />
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
                追问: &quot;{selectionData.text.slice(0, 30)}{selectionData.text.length > 30 ? "…" : ""}&quot;
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

        <UploadProgress label={uploadLabel} />
        {/* 输入区域 */}
        <div className="px-6 py-4 border-t border-zinc-200 bg-white shrink-0">
          <div className="max-w-4xl mx-auto mb-2 flex gap-3 text-sm">
            <select aria-label="回答依据" value={evidenceMode} onChange={e => setEvidenceMode(e.target.value as "strict" | "supplement")} disabled={loading}>
              <option value="supplement">资料优先，标明补充知识</option><option value="strict">严格依据资料</option>
            </select>
            {loading && <button onClick={stopGeneration} className="text-red-600">停止生成</button>}
            <span role="status">{generationStatus}</span>
          </div>
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
            引用可查看原文 · 补充知识单独标明 · 未完成的回答不会进入后续上下文
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
