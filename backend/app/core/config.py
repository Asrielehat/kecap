"""应用配置 —— 所有环境变量统一管理

本地开发：SQLite + Qdrant 本地文件模式（无需 Docker）
Docker 部署：PostgreSQL + Qdrant 容器模式（一条命令全启动）
"""

from pathlib import Path
from pydantic_settings import BaseSettings
from functools import lru_cache


# 项目根目录 = backend/app/core/config.py 的上一级×4（kecap/）
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent


class Settings(BaseSettings):
    # ── 应用基础 ──
    app_name: str = "课答 - RAG 学业辅导智能体"
    debug: bool = True
    secret_key: str = "change-me-in-production"

    # ── 数据库 ──
    # SQLite 模式（本地开发默认）
    sqlite_path: str = "./data/kecap.db"
    # 如果设置了 DATABASE_URL 则直接用（Docker 下自动切 PostgreSQL）
    database_url_override: str = ""

    @property
    def database_url(self) -> str:
        if self.database_url_override:
            return self.database_url_override
        return f"sqlite+aiosqlite:///{self.sqlite_path}"

    # ── Qdrant 向量数据库 ──
    # 本地文件模式（开发默认）
    qdrant_path: str = "./data/qdrant"
    # 如果设置了 QDRANT_URL 则连接容器（Docker 下自动切）
    qdrant_url: str = ""
    qdrant_collection: str = "course_materials"

    # ── LLM (DeepSeek, 兼容 OpenAI SDK) ──
    llm_api_key: str = ""
    llm_base_url: str = "https://api.deepseek.com"
    llm_model: str = "deepseek-chat"
    llm_temperature: float = 0.3
    llm_max_tokens: int = 2048

    # ── Embedding（硅基流动 BGE-M3）──
    embedding_api_key: str = ""
    embedding_base_url: str = "https://api.siliconflow.cn/v1"
    embedding_model: str = "BAAI/bge-m3"
    embedding_dim: int = 1024  # BGE-M3: 1024

    # ── 文件上传 ──
    upload_dir: str = "./uploads"
    max_upload_size_mb: int = 50
    allowed_extensions: list[str] = ["pdf", "ppt", "pptx", "doc", "docx", "md", "txt"]

    # ── 内置技能（Skills）──
    # 默认指向项目根目录的 skills/，不受启动目录影响；可用 SKILLS_DIR 覆盖（EXE 模式自动设置）
    skills_dir: str = str(_PROJECT_ROOT / "skills")
    # 学习模式强制使用的主学习 skill 名（学生说"我想学XX"时列大纲 + checklist 并持续推进）。
    # 该 skill 必须声明 mode: learning；未加载到时自动回退到第一个 mode: learning 的技能。
    learning_skill: str = "费曼学习计划"

    # ── 智能体（Agent）──
    # Plan-and-Execute：回答前由 LLM 自主产出执行计划（意图/检索关键词/技能/是否澄清）
    agent_enabled: bool = True          # False = 完全回退现有硬编码管线
    agent_planner_model: str = ""       # 空则用 llm_model
    agent_planner_temperature: float = 0.1
    agent_planner_max_tokens: int = 500

    # ── RAG 参数 ──
    chunk_size: int = 800
    chunk_overlap: int = 150
    retrieval_top_k: int = 10          # 粗召回条数
    rerank_top_k: int = 3              # 动态阈值最少保留条数（最高分的 50% 以上都保留，上限 8 条）
    retrieval_score_threshold: float = 0.35

    # ── 模式预设（学习模式 vs 询问模式）──
    rag_mode_presets: dict = {
        "learning": {
            "chunk_size": 400,
            "chunk_overlap": 80,
            "retrieval_top_k": 10,
            "rerank_min": 5,
            "score_threshold": 0.25,
            "temperature": 0.15,
            "max_tokens": 3072,
        },
        "query": {
            "chunk_size": 800,
            "chunk_overlap": 150,
            "retrieval_top_k": 10,
            "rerank_min": 3,
            "score_threshold": 0.35,
            "temperature": 0.3,
            "max_tokens": 2048,
        },
    }

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


@lru_cache()
def get_settings() -> Settings:
    return Settings()
