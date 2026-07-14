# ── 前端容器：Next.js ──

# 阶段 1：构建
FROM node:20-alpine AS builder
WORKDIR /app

# 接收 build-time 环境变量（Next.js 会在构建时内联 NEXT_PUBLIC_*）
ARG NEXT_PUBLIC_API_URL=http://localhost:8000/api
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL

# 先复制依赖文件（利用缓存）
COPY package.json package-lock.json* ./
RUN npm ci

# 复制源码并构建
COPY . .
RUN npm run build

# 阶段 2：运行（只保留生产文件）
FROM node:20-alpine AS runner
WORKDIR /app

ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1

# 只复制运行时需要的东西
COPY --from=builder /app/public ./public
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static

EXPOSE 3000

CMD ["node", "server.js"]
