"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { apiJson } from "../../lib/api";

type Document = { id: string; course_id: string; course_name: string; filename: string; file_size: number };

export default function ClassroomList() {
  const [documents, setDocuments] = useState<Document[]>([]);
  const [error, setError] = useState("");
  useEffect(() => {
    apiJson<Document[]>("/classroom/documents").then(setDocuments).catch(e => setError(String(e)));
  }, []);
  return <main className="min-h-full bg-zinc-50 p-6 sm:p-10 text-zinc-800">
    <div className="max-w-3xl mx-auto">
      <Link href="/" className="text-blue-700">← 返回 Chat</Link>
      <h1 className="text-2xl font-bold mt-5 mb-2">上课模式</h1>
      <p className="text-sm text-zinc-500 mb-6">选择已上传的 PDF。原文件只读，笔迹单独保存。</p>
      {error && <p role="alert" className="text-red-700">无法获取文档：{error}</p>}
      {!error && documents.length === 0 && <p>暂无 PDF，请先在 Chat 中上传。</p>}
      <div className="space-y-3">{documents.map(doc => <Link key={doc.id} href={`/classroom/reader?id=${encodeURIComponent(doc.id)}`}
        className="block p-4 rounded-xl bg-white border border-zinc-200 hover:border-blue-400">
        <div className="font-medium break-all">{doc.filename}</div>
        <div className="text-sm text-zinc-500 mt-1">{doc.course_name} · {(doc.file_size / 1024 / 1024).toFixed(1)} MB</div>
      </Link>)}</div>
    </div>
  </main>;
}
