# 📚 Kecap — RAG-Powered AI Study Assistant

**[English](#english) | [中文](#中文)**

---

<a id="english"></a>

## Introduction

Students upload course materials (textbooks, slides, notes), and the assistant provides **accurate, traceable** AI Q&A and adaptive practice based on RAG (Retrieval-Augmented Generation).

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | Next.js 14 + Tailwind CSS |
| Backend | Python FastAPI |
| LLM | DeepSeek V3 API |
| Embedding | SiliconFlow BGE-M3 |
| Vector Database | Qdrant |
| Database | PostgreSQL |
| Voice TTS | GPT-SoVITS (optional) |

## 🚀 Quick Start (Standalone EXE)

### 1. Download

👉 **[Download Kecap v1.0.0 (Windows 64-bit, 65.5 MB)](https://github.com/Asrielehat/kecap/releases/download/v1.0.0/Kecap-v1.0.0-win64.zip)**

Or visit the [Releases page](https://github.com/Asrielehat/kecap/releases) for the latest version.

### 2. Requirements

An internet connection (cloud AI APIs are called at runtime).

### 3. Get API Keys

| Service | Website |
|---------|---------|
| DeepSeek (LLM) | https://platform.deepseek.com |
| SiliconFlow (Embedding) | https://siliconflow.cn |

Sign up on each platform, create an API key, and keep them handy.

### 4. Configure & Run

Unzip the archive. The folder contains:

```
课答Kecap/
├── 课答.exe            ← Double-click to launch
├── .env.example        ← Config template (copy and rename to .env)
├── 使用说明.txt         ← Usage instructions
├── data/               ← Auto-generated (database, vector index)
└── uploads/            ← Auto-generated (uploaded files)
```

**Steps:**

1. Unzip to any location
2. Copy `.env.example` and rename the copy to `.env`
3. Open `.env` in Notepad and fill in your API keys:
   ```
   LLM_API_KEY=sk-your-deepseek-key
   EMBEDDING_API_KEY=sk-your-siliconflow-key
   ```
4. Double-click `课答.exe`
5. Your browser opens http://localhost:8000 automatically — start using it

### 5. Quit

Just close the console window.

---

## Developer Setup (Full Environment)

> For development, debugging, and Docker deployment.

### 1. Prerequisites

- Python ≥ 3.10
- Node.js ≥ 18
- Docker Desktop

### 2. Register API Keys

| Service | Website |
|---------|---------|
| DeepSeek (LLM) | https://platform.deepseek.com |
| SiliconFlow (Embedding) | https://siliconflow.cn |

### 3. Configure Environment Variables

Edit `backend/.env` and fill in your API keys:

```env
LLM_API_KEY=sk-your-deepseek-key
EMBEDDING_API_KEY=sk-your-siliconflow-key
```

### 4. Start Infrastructure

```bash
docker compose up -d
```

### 5. Start Backend

```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Visit http://localhost:8000/docs for the API documentation.

### 6. Start Frontend

```bash
cd frontend
npm install
npm run dev
```

Visit http://localhost:3000

## Project Structure

```
kecap/
├── docker-compose.yml        # Qdrant + PostgreSQL
├── backend/
│   ├── app/
│   │   ├── main.py           # FastAPI entry point
│   │   ├── core/
│   │   │   ├── config.py     # Configuration management
│   │   │   └── database.py   # Database connection
│   │   ├── models/
│   │   │   ├── db_models.py  # SQLAlchemy models
│   │   │   └── schemas.py    # Pydantic request/response
│   │   ├── api/
│   │   │   ├── upload.py     # Document upload API
│   │   │   ├── chat.py       # RAG Q&A API
│   │   │   └── courses.py    # Course management API
│   │   └── rag/
│   │       ├── document_processor.py  # Document parsing + chunking
│   │       ├── vector_store.py        # Qdrant vector store
│   │       ├── retriever.py           # Hybrid retrieval + reranking
│   │       └── generator.py           # LLM answer generation
│   ├── requirements.txt
│   ├── Dockerfile
│   └── .env
└── frontend/
    └── src/app/
        └── page.tsx          # Main chat interface
```

## API Overview

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/courses/` | Create a course |
| GET | `/api/courses/` | List courses |
| POST | `/api/documents/upload` | Upload a document (auto parse + vectorize) |
| POST | `/api/chat/ask` | RAG Q&A (returns answer + citations) |
| POST | `/api/chat/ask/stream` | Streaming RAG Q&A (SSE) |

## RAG Pipeline

```
User question → Query expansion → Vector retrieval (BM25 + semantic) → Top-10 recall
→ Cross-encoder reranking → Top-3 → LLM answer generation
→ Sentence-level citation annotation → Response
```

---
---

<a id="中文"></a>

# 📚 课答 —— RAG 增强的 AI 学业辅导智能体

## 项目简介

学生上传课程资料（教材、课件、笔记），智能体基于 RAG 技术提供**精准、可溯源**的 AI 答疑与自适应练习。

## 技术栈

| 层级 | 技术 |
|------|------|
| 前端 | Next.js 14 + Tailwind CSS |
| 后端 | Python FastAPI |
| LLM | DeepSeek V3 API |
| Embedding | 硅基流动 BGE-M3 |
| 向量数据库 | Qdrant |
| 业务数据库 | PostgreSQL |
| 语音 TTS | GPT-SoVITS（可选） |

## 🚀 快速使用（EXE 一键版）


### 1. 下载

👉 **[点击下载 课答 Kecap v1.0.0（Windows 64 位，65.5 MB）](https://github.com/Asrielehat/kecap/releases/download/v1.0.0/Kecap-v1.0.0-win64.zip)**

或前往 [Releases 页面](https://github.com/Asrielehat/kecap/releases) 选择最新版本。

### 2. 准备

确保你的电脑能正常访问互联网（需要调用云端 AI API）。

### 3. 获取 API Key

| 服务 | 地址 |
|------|------|
| DeepSeek（LLM） | https://platform.deepseek.com |
| SiliconFlow（Embedding） | https://siliconflow.cn |

注册后在对应平台创建 API Key，复制备用。

### 4. 配置并启动

解压下载的 zip，文件夹内容如下：

```
课答Kecap/
├── 课答.exe            ← 双击启动
├── .env.example        ← 配置模板（复制一份改名为 .env）
├── 使用说明.txt
├── data/               ← 自动生成（数据库、向量索引）
└── uploads/            ← 自动生成（上传的文件）
```

**操作步骤：**

1. 解压 zip 到任意位置
2. 把 `.env.example` 复制一份，重命名为 `.env`
3. 用记事本编辑 `.env`，填入自己的 API Key：
   ```
   LLM_API_KEY=sk-你的deepseek-key
   EMBEDDING_API_KEY=sk-你的siliconflow-key
   ```
4. 双击 `课答.exe`
5. 浏览器会自动打开 http://localhost:8000，即可使用

### 5. 关闭

直接关闭控制台黑窗口即可。

---

## 开发者部署（完整环境）

> 适合开发、调试、Docker 部署。

### 1. 前置条件

- Python ≥ 3.10
- Node.js ≥ 18
- Docker Desktop

### 2. 注册 API Key

| 服务 | 地址 |
|------|------|
| DeepSeek（LLM） | https://platform.deepseek.com |
| SiliconFlow（Embedding） | https://siliconflow.cn |

### 3. 配置环境变量

编辑 `backend/.env`，填入你的 API Key：

```env
LLM_API_KEY=sk-your-deepseek-key
EMBEDDING_API_KEY=sk-your-siliconflow-key
```

### 4. 启动基础设施

```bash
docker compose up -d
```

### 5. 启动后端

```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

访问 http://localhost:8000/docs 查看 API 文档。

### 6. 启动前端

```bash
cd frontend
npm install
npm run dev
```

访问 http://localhost:3000

## 项目结构

```
kecap/
├── docker-compose.yml        # Qdrant + PostgreSQL
├── backend/
│   ├── app/
│   │   ├── main.py           # FastAPI 入口
│   │   ├── core/
│   │   │   ├── config.py     # 配置管理
│   │   │   └── database.py   # 数据库连接
│   │   ├── models/
│   │   │   ├── db_models.py  # SQLAlchemy 模型
│   │   │   └── schemas.py    # Pydantic 请求/响应
│   │   ├── api/
│   │   │   ├── upload.py     # 文档上传 API
│   │   │   ├── chat.py       # RAG 答疑 API
│   │   │   └── courses.py    # 课程管理 API
│   │   └── rag/
│   │       ├── document_processor.py  # 文档解析 + 分块
│   │       ├── vector_store.py        # Qdrant 向量存储
│   │       ├── retriever.py           # 混合检索 + 重排序
│   │       └── generator.py           # LLM 答案生成
│   ├── requirements.txt
│   ├── Dockerfile
│   └── .env
└── frontend/
    └── src/app/
        └── page.tsx          # 主聊天界面
```

## API 概览

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/courses/` | 创建课程 |
| GET | `/api/courses/` | 课程列表 |
| POST | `/api/documents/upload` | 上传文档（自动解析+向量化） |
| POST | `/api/chat/ask` | RAG 答疑（返回答案+引文） |
| POST | `/api/chat/ask/stream` | 流式 RAG 答疑（SSE） |

## RAG 链路

```
用户提问 → Query扩展 → 向量检索(BM25+语义) → 召回Top-10
→ Cross-encoder Reranker 精排 → Top-3 → LLM生成答案
→ 逐句标注引用来源 → 返回给用户
```
