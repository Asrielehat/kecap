"""应用配置 —— 所有环境变量统一管理"""

from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # ── 应用基础 ──
    app_name: str = "课答 - RAG 学业辅导智能体"
    debug: bool = True
    secret_key: str = "change-me-in-production"

    # ── 数据库（SQLite 本地文件，免 Docker）──
    sqlite_path: str = "./data/kecap.db"

    @property
    def database_url(self) -> str:
        return f"sqlite+aiosqlite:///{self.sqlite_path}"

    # ── Qdrant（本地文件模式，免 Docker）──
    qdrant_path: str = "./data/qdrant"
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

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


@lru_cache()
def get_settings() -> Settings:
    return Settings()
