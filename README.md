# 📚 课答 —— RAG 增强的 AI 学业辅导智能体

> 2026 年广东省"元智新潮"大学生智能体应用创新大赛 · 教育智能体赛道

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

> **适合评委 / 非技术人员** —— 无需安装 Python、Node.js、Docker，下载即用。

### 1. 准备

确保你的电脑能正常访问互联网（需要调用云端 AI API）。

### 2. 获取 API Key

| 服务 | 地址 | 费用 |
|------|------|------|
| DeepSeek（LLM） | https://platform.deepseek.com | 新用户送 500 万 token |
| SiliconFlow（Embedding） | https://siliconflow.cn | 新用户送 2000 万 token |

注册后在对应平台创建 API Key，复制备用。

### 3. 配置并启动

```
dist/                    ← 把这个文件夹复制给别人
├── 课答.exe             ← 双击启动
├── .env                 ← 配置文件（API Key 写在这里）
├── data/                ← 自动生成（数据库、向量索引）
└── uploads/             ← 自动生成（上传的文件）
```

**接收方操作步骤：**

1. 将整个 `dist` 文件夹拷贝到任意位置
2. 用记事本编辑 `dist/.env`，填入自己的 API Key：
   ```
   LLM_API_KEY=sk-你的deepseek-key
   EMBEDDING_API_KEY=sk-你的siliconflow-key
   ```
3. 双击 `课答.exe`
4. 等待控制台显示"前端页面: http://localhost:8000"
5. 浏览器会自动打开，即可使用

> ⚠️ **注意**：分发时请删除 `.env` 中的个人 API Key，接收方需自行配置。`.env` 中只保留空模板即可。

### 4. 关闭

直接关闭控制台黑窗口即可。

---

## 开发者部署（完整环境）

> 适合开发、调试、Docker 部署。

### 1. 前置条件

- Python ≥ 3.10
- Node.js ≥ 18
- Docker Desktop

### 2. 注册 API Key

| 服务 | 地址 | 费用 |
|------|------|------|
| DeepSeek（LLM） | https://platform.deepseek.com | ¥1/百万 token |
| SiliconFlow（Embedding） | https://siliconflow.cn | 新用户送 2000 万 token |

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
