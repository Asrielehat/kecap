"use client";

import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { API_BASE, apiJson } from "../../../lib/api";
import { getPage, getPdf, putPage, putPdf, type LocalPage, type Stroke } from "../../../lib/classroom-store";
import "pdfjs-dist/web/pdf_viewer.css";

type PdfDocument = import("pdfjs-dist").PDFDocumentProxy;
type Mode = "read" | "select" | "write";
type Status = "本地已保存" | "同步中" | "已同步" | "同步失败";
type ChatTurn = { role: "user" | "assistant"; content: string };

function ClassroomReader() {
  const id = useSearchParams().get("id") || "";
  const [pdf, setPdf] = useState<PdfDocument | null>(null);
  const [pageNumber, setPageNumber] = useState(1);
  const [scale, setScale] = useState(1);
  const [size, setSize] = useState({ width: 600, height: 800 });
  const [mode, setMode] = useState<Mode>("read");
  const [tool, setTool] = useState<"pen" | "highlighter" | "eraser">("pen");
  const [color, setColor] = useState("#2255cc");
  const [width, setWidth] = useState(3);
  const [strokes, setStrokes] = useState<Stroke[]>([]);
  const [redo, setRedo] = useState<Stroke[]>([]);
  const [draft, setDraft] = useState<Stroke | null>(null);
  const [status, setStatus] = useState<Status>("本地已保存");
  const [error, setError] = useState("");
  const [selectedText, setSelectedText] = useState("");
  const [context, setContext] = useState("");
  const [chatOpen, setChatOpen] = useState(false);
  const [chat, setChat] = useState<ChatTurn[]>([]);
  const [question, setQuestion] = useState("");
  const [asking, setAsking] = useState(false);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [courseId, setCourseId] = useState("");
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const textRef = useRef<HTMLDivElement>(null);
  const overlayRef = useRef<SVGSVGElement>(null);
  const stateRef = useRef<LocalPage>({ version: 0, strokes: [], dirty: false });
  const busyRef = useRef(false);
  const penAtRef = useRef(0);
  const loadKeyRef = useRef("");

  useEffect(() => {
    if (!id) return;
    let cancelled = false;
    async function openPdf() {
      try {
        const pdfjs = await import("pdfjs-dist");
        pdfjs.GlobalWorkerOptions.workerSrc = new URL("pdfjs-dist/build/pdf.worker.min.mjs", import.meta.url).toString();
        let data: ArrayBuffer | undefined;
        if (navigator.onLine) {
          try {
            const response = await fetch(`${API_BASE}/documents/${id}/file`);
            if (!response.ok) throw new Error(`PDF 下载失败 (${response.status})`);
            data = await response.arrayBuffer();
            try { await putPdf(id, data.slice(0)); }
            catch { setError("PDF 可阅读，但离线缓存失败；请检查浏览器空间。"); }
          } catch { data = await getPdf(id); }
        } else data = await getPdf(id);
        if (!data) throw new Error("PDF 未缓存，需要联网打开一次");
        const loaded = await pdfjs.getDocument({ data: new Uint8Array(data) }).promise;
        if (!cancelled) setPdf(loaded);
      } catch (e) { if (!cancelled) setError(String(e)); }
    }
    void openPdf();
    const loadCourse = () => {
      void apiJson<Array<{ id: string; course_id: string }>>("/classroom/documents")
        .then(items => { if (!cancelled) setCourseId(items.find(item => item.id === id)?.course_id || ""); }).catch(() => undefined);
    };
    loadCourse();
    window.addEventListener("online", loadCourse);
    return () => { cancelled = true; window.removeEventListener("online", loadCourse); };
  }, [id]);

  useEffect(() => {
    if (!pdf) return;
    let cancelled = false;
    const key = `${id}:${pageNumber}`;
    loadKeyRef.current = key;
    setStrokes([]);
    setRedo([]);
    setDraft(null);
    async function load() {
      try {
        const local = await getPage(id, pageNumber);
        let chosen = local;
        if (!local?.dirty && navigator.onLine) {
          try {
            const remote = await apiJson<LocalPage>(`/classroom/documents/${id}/pages/${pageNumber}`);
            chosen = { version: remote.version, strokes: remote.strokes, dirty: false };
            await putPage(id, pageNumber, chosen);
          } catch { /* cached annotations remain usable offline */ }
        }
        if (cancelled || loadKeyRef.current !== key) return;
        stateRef.current = chosen || { version: 0, strokes: [], dirty: false };
        setStrokes(stateRef.current.strokes);
        setStatus(stateRef.current.dirty ? "本地已保存" : "已同步");
      } catch (e) { if (!cancelled) setError(`笔迹读取失败：${e}`); }
    }
    void load();
    return () => { cancelled = true; };
  }, [id, pageNumber, pdf]);

  useEffect(() => {
    if (!pdf || !canvasRef.current || !textRef.current) return;
    let cancelled = false;
    let render: { cancel: () => void; promise: Promise<void> } | undefined;
    async function draw() {
      const pdfjs = await import("pdfjs-dist");
      const page = await pdf!.getPage(pageNumber);
      const viewport = page.getViewport({ scale: scale * 1.2 });
      const canvas = canvasRef.current;
      const layer = textRef.current;
      if (!canvas || !layer || cancelled) return;
      const ratio = window.devicePixelRatio || 1;
      canvas.width = Math.floor(viewport.width * ratio);
      canvas.height = Math.floor(viewport.height * ratio);
      canvas.style.width = `${viewport.width}px`;
      canvas.style.height = `${viewport.height}px`;
      layer.style.width = `${viewport.width}px`;
      layer.style.height = `${viewport.height}px`;
      setSize({ width: viewport.width, height: viewport.height });
      const ctx = canvas.getContext("2d");
      if (!ctx) return;
      render = page.render({ canvasContext: ctx, canvas, viewport, transform: [ratio, 0, 0, ratio, 0, 0] });
      await render.promise;
      if (cancelled) return;
      layer.replaceChildren();
      const textContent = await page.getTextContent();
      if (cancelled) return;
      setContext(textContent.items.map(item => "str" in item ? item.str : "").join(" ").slice(0, 1800));
      const textLayer = new pdfjs.TextLayer({ textContentSource: textContent, container: layer, viewport });
      await textLayer.render();
    }
    void draw().catch(e => { if (!cancelled && e?.name !== "RenderingCancelledException") setError(String(e)); });
    return () => { cancelled = true; render?.cancel(); };
  }, [pdf, pageNumber, scale]);

  const sync = useCallback(async () => {
    const key = `${id}:${pageNumber}`;
    if (loadKeyRef.current !== key || busyRef.current || !navigator.onLine || !stateRef.current.dirty) return;
    busyRef.current = true;
    setStatus("同步中");
    const snapshot = stateRef.current;
    try {
      const result = await apiJson<{ version: number }>(`/classroom/documents/${id}/pages/${pageNumber}`, {
        method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ base_version: snapshot.version, strokes: snapshot.strokes }),
      });
      if (loadKeyRef.current !== key) return;
      const current = stateRef.current;
      const next = { version: result.version, strokes: current.strokes, dirty: current !== snapshot };
      stateRef.current = next;
      await putPage(id, pageNumber, next);
      setStatus(next.dirty ? "本地已保存" : "已同步");
    } catch (e) { if (loadKeyRef.current === key) { setStatus("同步失败"); setError(`同步失败：${e}。本地笔迹仍在此浏览器中。`); } }
    finally { busyRef.current = false; }
  }, [id, pageNumber]);

  useEffect(() => {
    const timer = window.setInterval(() => { void sync(); }, 2500);
    const online = () => { void sync(); };
    window.addEventListener("online", online);
    return () => { window.clearInterval(timer); window.removeEventListener("online", online); };
  }, [sync]);

  async function save(nextStrokes: Stroke[]) {
    const next = { ...stateRef.current, strokes: nextStrokes, dirty: true };
    stateRef.current = next;
    setStrokes(nextStrokes);
    try { await putPage(id, pageNumber, next); setStatus("本地已保存"); void sync(); }
    catch (e) { setStatus("同步失败"); setError(`本地保存失败：${e}`); }
  }
  function undo() {
    const last = strokes.at(-1);
    if (!last) return;
    setRedo(old => [...old, last]);
    void save(strokes.slice(0, -1));
  }
  function redoStroke() {
    const last = redo.at(-1);
    if (!last) return;
    setRedo(old => old.slice(0, -1));
    void save([...strokes, last]);
  }

  function point(e: React.PointerEvent<SVGSVGElement>) {
    const r = overlayRef.current!.getBoundingClientRect();
    return { x: Math.min(1, Math.max(0, (e.clientX - r.left) / r.width)),
      y: Math.min(1, Math.max(0, (e.clientY - r.top) / r.height)),
      pressure: e.pressure || 0.5 };
  }
  function pointerDown(e: React.PointerEvent<SVGSVGElement>) {
    if (mode !== "write" || e.pointerType === "touch") return;
    if (e.pointerType === "pen") penAtRef.current = Date.now();
    if (e.pointerType !== "pen" && Date.now() - penAtRef.current < 800) return;
    e.preventDefault();
    e.currentTarget.setPointerCapture(e.pointerId);
    const p = point(e);
    if (tool === "eraser") {
      const hit = [...strokes].reverse().find(s => s.points.some(q => Math.hypot(q.x - p.x, q.y - p.y) < 0.025));
      if (hit) { setRedo([]); void save(strokes.filter(s => s.id !== hit.id)); }
      return;
    }
    setDraft({ id: crypto.randomUUID(), tool, color, width, points: [p] });
  }
  function pointerMove(e: React.PointerEvent<SVGSVGElement>) {
    if (!draft || !e.currentTarget.hasPointerCapture(e.pointerId)) return;
    e.preventDefault();
    const p = point(e);
    setDraft(s => s && s.points.length < 10000 ? { ...s, points: [...s.points, p] } : s);
  }
  function pointerUp(e: React.PointerEvent<SVGSVGElement>) {
    if (!draft) return;
    if (e.currentTarget.hasPointerCapture(e.pointerId)) e.currentTarget.releasePointerCapture(e.pointerId);
    setRedo([]);
    void save([...strokes, draft]);
    setDraft(null);
  }
  async function ask(text: string) {
    if (!courseId || asking || !text.trim()) return;
    setChatOpen(true);
    setAsking(true);
    setChat(old => [...old, { role: "user", content: text }]);
    try {
      const response = await apiJson<{ answer: string; conversation_id: string }>("/chat/ask", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ course_id: courseId, conversation_id: conversationId,
          question: text, evidence_mode: "supplement" }),
      });
      setConversationId(response.conversation_id);
      setChat(old => [...old, { role: "assistant", content: response.answer }]);
    } catch (e) { setChat(old => [...old, { role: "assistant", content: `提问失败：${e}` }]); }
    finally { setAsking(false); }
  }
  function askSelection() {
    const text = window.getSelection()?.toString().trim().slice(0, 800) || selectedText;
    if (!text) return;
    setSelectedText(text);
    void ask(`请解释这段 PDF 原文（文档 ID: ${id}，第 ${pageNumber} 页）：「${text}」。页面上下文：${context.slice(0, 900)}`);
  }
  function strokeSvg(s: Stroke) {
    const points = s.points.map(p => `${p.x * size.width},${p.y * size.height}`).join(" ");
    return <polyline key={s.id} points={points} fill="none" stroke={s.color}
      strokeWidth={s.width} strokeLinecap="round" strokeLinejoin="round"
      opacity={s.tool === "highlighter" ? 0.35 : 1} />;
  }

  return <main className="h-dvh flex flex-col bg-zinc-100 text-zinc-800">
    <header className="flex flex-wrap items-center gap-2 px-3 py-2 bg-white border-b border-zinc-200">
      <Link href="/classroom" className="text-blue-700 mr-2">← 文档</Link>
      <strong className="mr-auto">上课模式</strong>
      <span role="status" className="text-xs text-zinc-600">{status}</span>
      <button onClick={() => setChatOpen(v => !v)} className="px-2 py-1 border rounded">AI {chatOpen ? "收起" : "打开"}</button>
    </header>
    <div className="flex flex-1 min-h-0 relative">
      <section className="flex-1 min-w-0 flex flex-col">
        <div className="flex flex-wrap gap-2 items-center px-3 py-2 bg-white border-b">
          {(["read", "select", "write"] as const).map((m, i) => <button key={m} onClick={() => setMode(m)}
            className={`px-2 py-1 rounded ${mode === m ? "bg-blue-700 text-white" : "border"}`}>{["阅读", "选择", "书写"][i]}</button>)}
          {mode === "write" && <>
            <select aria-label="笔迹工具" value={tool} onChange={e => setTool(e.target.value as typeof tool)} className="border rounded p-1">
              <option value="pen">画笔</option><option value="highlighter">荧光笔</option><option value="eraser">橡皮擦</option>
            </select>
            <input aria-label="颜色" type="color" value={color} onChange={e => setColor(e.target.value)} />
            <input aria-label="粗细" type="range" min="1" max="16" value={width} onChange={e => setWidth(Number(e.target.value))} />
            <button className="border rounded px-2" disabled={!strokes.length} onClick={undo}>撤销</button>
            <button className="border rounded px-2" disabled={!redo.length} onClick={redoStroke}>重做</button>
          </>}
          {mode === "select" && <button onClick={askSelection} disabled={asking} className="px-2 py-1 rounded bg-blue-700 text-white disabled:opacity-50">询问 AI</button>}
          <span className="ml-auto flex items-center gap-2">
            <button onClick={() => setPageNumber(Math.max(1, pageNumber - 1))} disabled={pageNumber <= 1}>上一页</button>
            {pageNumber}/{pdf?.numPages || "…"}
            <button onClick={() => setPageNumber(Math.min(pdf?.numPages || 1, pageNumber + 1))} disabled={pageNumber >= (pdf?.numPages || 1)}>下一页</button>
            <button onClick={() => setScale(s => Math.max(0.6, s - 0.2))}>−</button>
            <button onClick={() => setScale(s => Math.min(2.5, s + 0.2))}>＋</button>
          </span>
        </div>
        {error && <div role="alert" className="bg-amber-50 text-amber-900 px-3 py-2 text-sm">{error}</div>}
        <div className="flex-1 overflow-auto p-4" style={{ touchAction: "pan-x pan-y pinch-zoom" }}>
          <div className="relative mx-auto shadow bg-white" style={{ width: size.width, height: size.height }}>
            <canvas ref={canvasRef} className="absolute inset-0" />
            <div ref={textRef} className="textLayer absolute inset-0"
              style={{ userSelect: mode === "select" ? "text" : "none", pointerEvents: mode === "select" ? "auto" : "none" }}
              onPointerUp={() => setSelectedText(window.getSelection()?.toString().trim() || "")} />
            <svg ref={overlayRef} className="absolute inset-0" width={size.width} height={size.height}
              style={{ pointerEvents: mode === "write" ? "auto" : "none", touchAction: "pan-x pan-y pinch-zoom" }}
              onPointerDown={pointerDown} onPointerMove={pointerMove} onPointerUp={pointerUp} onPointerCancel={pointerUp}>
              {strokes.map(strokeSvg)}{draft && strokeSvg(draft)}
            </svg>
          </div>
        </div>
      </section>
      {chatOpen && <aside className="absolute inset-y-0 right-0 z-10 w-full sm:w-96 lg:relative lg:w-96 bg-white border-l shadow-lg flex flex-col">
        <div className="p-3 border-b flex justify-between"><strong>课堂 AI</strong><button onClick={() => setChatOpen(false)}>关闭</button></div>
        <div className="flex-1 overflow-auto p-3 space-y-3 text-sm">{chat.map((turn, index) => <div key={index} className={`p-3 rounded ${turn.role === "user" ? "bg-blue-50" : "bg-zinc-100"}`}>{turn.content}</div>)}{asking && <p>正在回答…</p>}</div>
        <form className="p-3 border-t flex gap-2" onSubmit={e => { e.preventDefault(); void ask(question); setQuestion(""); }}>
          <input aria-label="继续提问" className="border rounded p-2 flex-1 min-w-0" value={question} onChange={e => setQuestion(e.target.value)} placeholder="继续提问" />
          <button disabled={asking || !question.trim()} className="bg-blue-700 text-white rounded px-3 disabled:opacity-50">发送</button>
        </form>
      </aside>}
    </div>
  </main>;
}

export default function ReaderPage() {
  return <Suspense fallback={<p>正在打开 PDF…</p>}><ClassroomReader /></Suspense>;
}
