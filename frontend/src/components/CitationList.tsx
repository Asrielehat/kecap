"use client";
import { useState } from "react";
import type { Citation } from "../lib/types";
import { API_BASE, apiJson } from "../lib/api";

type Source = { content: string; filename: string; page?: number; page_end?: number; source_url: string };
export function CitationList({ citations }: { citations: Citation[] }) {
  const [source, setSource] = useState<Source | null>(null);
  const [error, setError] = useState("");
  async function open(citation: Citation) {
    setError("");
    setSource(null);
    try { setSource(await apiJson<Source>(`/documents/chunks/${citation.chunk_id}`)); }
    catch (error) { setError(error instanceof Error ? error.message : "原文加载失败"); }
  }
  if (!citations.length) return null;
  return <details className="mt-3 border-t border-zinc-200 pt-2">
    <summary className="cursor-pointer text-xs text-zinc-600">参考来源（{citations.length} 条）</summary>
    <div className="space-y-2 mt-2">{citations.map((citation, index) => <button key={citation.chunk_id || index}
      className="block w-full rounded-lg border border-zinc-200 bg-white p-2 text-left text-xs"
      onClick={() => open(citation)}>
      <span className="text-blue-700">[{index + 1}] {citation.document_name}{citation.page ? ` · 第 ${citation.page} 页` : ""} · 查看原文</span>
      <span className="block text-zinc-600 line-clamp-3 mt-1">{citation.text}</span>
    </button>)}</div>
    {error && <p role="alert" className="text-sm text-red-600">{error}</p>}
    {source && <div className="mt-3 rounded-lg bg-zinc-50 border p-3 text-sm">
      <button className="float-right" aria-label="关闭原文" onClick={() => setSource(null)}>×</button>
      <p className="font-medium">{source.filename}</p>
      <p className="whitespace-pre-wrap my-2">{source.content}</p>
      <a className="text-blue-700" target="_blank" rel="noreferrer"
        href={`${API_BASE}${source.source_url.replace(/^\/api/, "")}#page=${source.page || 1}`}>打开原文件</a>
    </div>}
  </details>;
}
