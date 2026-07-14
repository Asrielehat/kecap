# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置 —— 课答 Kecap"""

import os
from pathlib import Path

# 前端静态文件路径（SPECPATH 是 PyInstaller 提供的 spec 文件所在目录）
frontend_out = Path(SPECPATH).parent / "frontend" / "out"

datas = []
if frontend_out.exists():
    # 将前端构建产物打包进 EXE
    datas.append((str(frontend_out), "frontend"))

a = Analysis(
    ["app/main_exe.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=[
        # Pydantic / Settings
        "pydantic_settings",
        "pydantic",
        # SQLAlchemy
        "sqlalchemy",
        "aiosqlite",
        # FastAPI / Starlette / Uvicorn
        "fastapi",
        "starlette",
        "uvicorn",
        "uvicorn.logging",
        "uvicorn.loops",
        "uvicorn.loops.auto",
        "uvicorn.protocols",
        "uvicorn.protocols.http",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.websockets",
        "uvicorn.protocols.websockets.auto",
        "uvicorn.lifespan",
        "uvicorn.lifespan.on",
        # WebSocket (uvicorn standard)
        "websockets",
        "websockets.legacy",
        "websockets.legacy.http",
        # Qdrant
        "qdrant_client",
        "qdrant_client.http",
        "qdrant_client.grpc",
        # Document parsing
        "fitz",  # PyMuPDF
        "pptx",
        "docx",
        "markdown",
        # OpenAI / HTTP
        "openai",
        "httpx",
        "httpcore",
        "tiktoken",
        "tiktoken_ext",
        "tiktoken_ext.openai_public",
        # Auth
        "jose",
        "passlib",
        "cryptography",
        # Others
        "dotenv",
        "multipart",
        "PIL",
        "yaml",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter",
        "unittest",
        "pydoc",
        "distutils",
        "setuptools",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=None,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=None)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="课答",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,           # 显示控制台窗口（用户可以看到日志和 URL）
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,              # 如需图标：icon="app/static/icon.ico"
)
