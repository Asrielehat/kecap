"""应用配置 —— 所有环境变量统一管理

本地开发：SQLite + Qdrant 本地文件模式（无需 Docker）
Docker 部署：PostgreSQL + Qdrant 容器模式（一条命令全启动）
"""

from pydantic_settings import BaseSettings
from functools import lru_cache


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

    # ── RAG 参数 ──
    chunk_size: int = 800
    chunk_overlap: int = 150
    retrieval_top_k: int = 10
    rerank_top_k: int = 3
    retrieval_score_threshold: float = 0.35

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


@lru_cache()
def get_settings() -> Settings:
    return Settings()
