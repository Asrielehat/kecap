import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "课答 - RAG 增强 AI 学业辅导",
  description: "上传课程资料，获取精准可溯源的 AI 答疑",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN" className="h-full">
      <body className="h-full antialiased">{children}</body>
    </html>
  );
}
