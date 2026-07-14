"""课答 EXE 启动入口

PyInstaller 打包后双击课答.exe 运行此文件。
同时提供 API 服务和前端静态页面，浏览器自动打开。
"""

import os
import sys
import webbrowser
import threading
from pathlib import Path


# ═══════════════════════════════════════════
# 必须在导入 app 之前设置环境变量
# ═══════════════════════════════════════════

if getattr(sys, "frozen", False):
    # PyInstaller 打包后运行：EXE 所在目录作为数据根目录
    BASE_DIR = Path(sys.executable).parent
    # 前端静态文件打包在 sys._MEIPASS 中
    FRONTEND_DIR = Path(sys._MEIPASS) / "frontend"
else:
    # 开发环境直接运行 python main_exe.py
    BASE_DIR = Path(__file__).resolve().parent.parent.parent
    FRONTEND_DIR = BASE_DIR.parent / "frontend" / "out"

# 加载 .env 文件（从 EXE 同级目录）
env_file = BASE_DIR / ".env"
if env_file.exists():
    from dotenv import load_dotenv
    load_dotenv(env_file)
    print(f"[Kecap] 已加载配置: {env_file}")
else:
    print(f"[Kecap] 未找到 .env 文件: {env_file}")

# 数据目录：SQLite 数据库、Qdrant 文件存储、上传文件
DATA_DIR = BASE_DIR / "data"
UPLOAD_DIR = BASE_DIR / "uploads"
DATA_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# 设置环境变量（在 config.py 加载前生效，仅覆盖未设置的）
os.environ.setdefault("SQLITE_PATH", str(DATA_DIR / "kecap.db"))
os.environ.setdefault("QDRANT_PATH", str(DATA_DIR / "qdrant"))
os.environ.setdefault("UPLOAD_DIR", str(UPLOAD_DIR))


# ═══════════════════════════════════════════
# 导入 FastAPI app
# ═══════════════════════════════════════════

from app.main import app
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse


# ═══════════════════════════════════════════
# 挂载前端静态文件
# ═══════════════════════════════════════════

if FRONTEND_DIR.exists():
    # 移除 main.py 中的 JSON 根路由（否则浏览器打开 / 会看到 JSON 而非前端页面）
    app.router.routes = [
        route for route in app.router.routes
        if not (hasattr(route, "path") and route.path == "/")
    ]

    # 挂载静态资源（JS / CSS / 图片等）
    app.mount("/_next", StaticFiles(directory=str(FRONTEND_DIR / "_next")), name="next")

    # 根路径返回前端页面
    @app.get("/")
    async def serve_index():
        index_path = FRONTEND_DIR / "index.html"
        return FileResponse(index_path) if index_path.exists() else FileResponse(FRONTEND_DIR / "404.html")

    @app.get("/{full_path:path}")
    async def serve_frontend(full_path: str):
        """SPA 兜底：所有非 API 请求返回 index.html"""
        # API 路由不拦截（已注册的 API 路由优先于 catch-all）
        if full_path.startswith("api/") or full_path.startswith("docs") or full_path.startswith("openapi"):
            from fastapi.responses import JSONResponse
            return JSONResponse({"detail": "Not Found"}, status_code=404)

        file_path = FRONTEND_DIR / full_path
        if file_path.is_file():
            return FileResponse(file_path)

        # SPA fallback
        index_path = FRONTEND_DIR / "index.html"
        if index_path.exists():
            return FileResponse(index_path)

        return FileResponse(FRONTEND_DIR / "404.html") if (FRONTEND_DIR / "404.html").exists() else JSONResponse(
            {"detail": "Not Found"}, status_code=404
        )

    print(f"[Kecap] 前端静态文件挂载: {FRONTEND_DIR}")
else:
    print(f"[Kecap] 前端目录不存在: {FRONTEND_DIR}，仅提供 API 服务")


# ═══════════════════════════════════════════
# 自动打开浏览器
# ═══════════════════════════════════════════

def open_browser():
    """延迟 1 秒后打开浏览器"""
    import time
    time.sleep(1)
    webbrowser.open("http://localhost:8000")
    print("[Kecap] 浏览器已打开: http://localhost:8000")

threading.Thread(target=open_browser, daemon=True).start()


# ═══════════════════════════════════════════
# 启动服务
# ═══════════════════════════════════════════

if __name__ == "__main__":
    import uvicorn

    print("=" * 50)
    print("  课答 Kecap — RAG 增强 AI 学业辅导智能体")
    print("=" * 50)
    print(f"  数据目录: {DATA_DIR}")
    print(f"  上传目录: {UPLOAD_DIR}")
    print(f"  前端页面: http://localhost:8000")
    print(f"  API 文档: http://localhost:8000/docs")
    print("=" * 50)
    print("  关闭此窗口即可退出程序")
    print("=" * 50)

    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
