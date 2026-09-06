import type { NextConfig } from "next";

// NEXT_EXPORT=1 时构建纯静态文件（为 EXE 打包），否则用 standalone（Docker）
const isExport = process.env.NEXT_EXPORT === "1";

const nextConfig: NextConfig = {
  output: isExport ? "export" : "standalone",
  // 静态导出不能使用 next/image 优化
  ...(isExport && { images: { unoptimized: true } }),
  ...(!isExport && {
    async rewrites() {
      return [{ source: "/api/:path*", destination: `${process.env.BACKEND_INTERNAL_URL || "http://127.0.0.1:8000"}/api/:path*` }];
    },
  }),
};

export default nextConfig;
