import { openDB } from "idb";

export type InkPoint = { x: number; y: number; pressure: number };
export type Stroke = { id: string; tool: "pen" | "highlighter"; color: string; width: number; points: InkPoint[] };
export type LocalPage = { version: number; strokes: Stroke[]; dirty: boolean };

const dbPromise = typeof window === "undefined" ? null : openDB("kecap-classroom", 1, {
  upgrade(db) {
    db.createObjectStore("pdfs");
    db.createObjectStore("pages");
  },
});

async function db() {
  if (!dbPromise) throw new Error("浏览器存储不可用");
  return dbPromise;
}

export const pageKey = (documentId: string, page: number) => `${documentId}:${page}`;
export async function getPdf(id: string): Promise<ArrayBuffer | undefined> { return (await db()).get("pdfs", id); }
export async function putPdf(id: string, data: ArrayBuffer) { await (await db()).put("pdfs", data, id); }
export async function getPage(id: string, page: number): Promise<LocalPage | undefined> { return (await db()).get("pages", pageKey(id, page)); }
export async function putPage(id: string, page: number, value: LocalPage) { await (await db()).put("pages", value, pageKey(id, page)); }
