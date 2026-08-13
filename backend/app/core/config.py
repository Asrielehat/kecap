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

    # ── 深度思考（DeepSeek thinking 模式）──
    # 开启后答案生成用思考模型流式返回推理链 reasoning_content，前端实时展示
    llm_thinking_enabled: bool = True
    llm_thinking_model: str = "deepseek-v4-flash"  # 返回 reasoning_content 的思考模型
    llm_thinking_mode: str = "thinking"            # v4 模型的 thinking_mode 参数
    llm_thinking_max_tokens: int = 8192            # 推理链较长，总 token 上限需加大

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

    # ── MCP 工具（可选增强，默认关闭）──
    # 开启后 LLM 可通过 function calling 调用外部 MCP 工具（如 fetch 抓网页）
    mcp_enabled: bool = False
    mcp_server_command: str = ""            # 留空自动：开发=sys.executable，EXE=python
    mcp_server_args: str = "-m mcp_server_fetch"   # 字符串 + shlex.split，避免 list 的 JSON env 格式
    mcp_connect_timeout: float = 15.0       # 连接就绪超时（秒）
    mcp_tool_timeout: float = 60.0          # 单次 call_tool 超时（秒）
    mcp_max_steps: int = 3                  # agent 循环最大轮数
    mcp_tool_max_tokens: int = 300          # 工具选择 LLM 调用的 max_tokens
    mcp_tool_result_max_chars: int = 8000   # 回填给模型的工具结果最大字符数

    # ── 技能系统（可选增强，默认关闭）──
    # 开启后，问题命中技能触发条件时，把技能指令注入 system prompt 影响 LLM 输出
    skills_enabled: bool = False
    skills_dir: str = "./skills"            # 技能文件目录（相对 backend/ 运行目录）
    skills_max_history_chars: int = 20000   # 完整历史注入的最大字符数（超出从最旧裁剪）

    # ── 检索智能体（可选增强，默认关闭）──
    # 开启后，检索不再是硬编码单次调用，而是 LLM 通过 function calling 自主决定
    # 检索（search_knowledge_base 工具）：查什么、查几次、结果不理想可换词重查
    agent_retrieval_enabled: bool = False
    agent_max_steps: int = 3                  # 检索决策循环最大轮数
    agent_tool_max_tokens: int = 300          # 检索决策 LLM 的 max_tokens（只决策不写答案）
    agent_tool_result_max_chars: int = 8000   # 回填给决策 LLM 的检索结果摘要上限（字符）

    # ── 检索规划（智能体流水线第 1 步）──
    # 开启后，先让 LLM 把问题拆成最多 3 个子问题，再逐个子问题检索并合并去重，
    # 覆盖问题的不同侧面；规划失败自动回退原问题单查询。
    agent_planning_enabled: bool = True

    # ── 答案自检（智能体流水线最后一步）──
    # 开启后，答案生成完再让 LLM 对照参考资料质检一遍，发现跑题/漏关键点/事实错误
    # 就重写为修正版；质检失败自动保留原答案。
    answer_selfcheck_enabled: bool = True

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


@lru_cache()
def get_settings() -> Settings:
    return Settings()
