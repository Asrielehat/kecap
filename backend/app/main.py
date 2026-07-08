"""课答 —— RAG 增强 AI 学业辅导智能体 —— FastAPI 主入口"""

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import get_settings
from app.core.database import init_db
from app.rag.vector_store import ensure_collection

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用启动/关闭生命周期"""
    print(f"\n[Kecap] {settings.app_name} 启动中...")
    await init_db()
    print("[Kecap] 数据库表初始化完成 (SQLite)")
    ensure_collection()
    print("[Kecap] Qdrant 集合就绪 (本地模式)")
    print(f"[Kecap] API 文档: http://localhost:8000/docs\n")
    yield
    print("[Kecap] 应用关闭")


app = FastAPI(
    title=settings.app_name,
    description="基于 RAG 技术的 AI 学业辅导智能体 —— 可溯源答疑、自适应练习、学情分析",
    version="0.1.0",
    lifespan=lifespan,
)

# ── CORS 配置 ──
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 开发阶段允许所有来源，上线后收紧
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── 注册路由 ──
from app.api.upload import router as upload_router
from app.api.chat import router as chat_router
from app.api.courses import router as courses_router
from app.api.conversations import router as conversations_router
from app.api.feedback import router as feedback_router

app.include_router(upload_router)
app.include_router(chat_router)
app.include_router(courses_router)
app.include_router(conversations_router)
app.include_router(feedback_router)


@app.get("/")
async def root():
    return {
        "name": settings.app_name,
        "version": "0.1.0",
        "docs": "/docs",
        "status": "running",
    }


@app.get("/health")
async def health():
    return {"status": "ok"}
