@echo off
chcp 65001 >nul
echo ========================================
echo   课答 Kecap — EXE 打包构建脚本
echo ========================================
echo.

cd /d "%~dp0"

:: ── 1. 构建前端（静态导出）──
echo [1/3] 构建前端静态文件...
cd frontend
set NEXT_EXPORT=1
:: 不再设置 NEXT_PUBLIC_API_URL：EXE 模式下前端自动用相对路径 /api
:: （在 Git Bash 中设为 /api 会被 MSYS 误转成 E:/Git/api，导致前端请求全挂）
call npx next build --webpack
if %ERRORLEVEL% NEQ 0 (
    echo ❌ 前端构建失败！
    pause
    exit /b 1
)
echo ✅ 前端静态文件构建完成
cd ..

:: ── 2. 安装 PyInstaller ──
echo.
echo [2/3] 检查 PyInstaller...
pip show pyinstaller >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo 安装 PyInstaller...
    pip install pyinstaller
)

:: ── 3. 打包 ──
echo.
echo [3/3] PyInstaller 打包...
cd backend
pyinstaller kecap.spec --distpath=..\dist --workpath=..\build\pyinstaller --clean
if %ERRORLEVEL% NEQ 0 (
    echo ❌ 打包失败！
    pause
    exit /b 1
)
cd ..

echo.
echo ========================================
echo   ✅ 打包完成！
echo   EXE 位置: dist\课答.exe
echo   大小:
dir /s dist\课答.exe 2>nul | findstr 课答.exe
echo.
echo   交付时请将 .env 文件放在课答.exe 同级目录
echo ========================================
pause
