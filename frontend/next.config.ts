import type { NextConfig } from "next";

// NEXT_EXPORT=1 时构建纯静态文件（为 EXE 打包），否则用 standalone（Docker）
const isExport = process.env.NEXT_EXPORT === "1";

const nextConfig: NextConfig = {
  output: isExport ? "export" : "standalone",
  // 静态导出不能使用 next/image 优化
  ...(isExport && { images: { unoptimized: true } }),
};

export default nextConfig;
