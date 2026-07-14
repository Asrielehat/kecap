# ── 后端容器：FastAPI + RAG ──
FROM python:3.11-slim

WORKDIR /app

# 系统依赖（PyMuPDF 解析 PDF 需要）
RUN apt-get update && apt-get install -y --no-install-recommends \
    libmupdf-dev \
    && rm -rf /var/lib/apt/lists/*

# 先复制依赖文件（利用 Docker 缓存层，代码改了不用重装）
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 再复制代码
COPY . .

# 创建数据目录
RUN mkdir -p /app/data /app/uploads

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
