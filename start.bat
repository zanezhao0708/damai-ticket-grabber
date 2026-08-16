@echo off
chcp 65001 >nul
title 大麦网抢票工具 Web版
cd /d "%~dp0"

echo ============================================
echo   大麦网抢票工具 Web版（仅个人学习用途）
echo ============================================
echo.

REM 检查Python
where python >nul 2>nul
if errorlevel 1 (
    echo [错误] 未找到 Python，请先安装 Python 3.9+
    echo 下载: https://www.python.org/downloads/
    pause
    exit /b 1
)

REM 首次运行安装依赖
if not exist ".deps_installed" (
    echo [首次运行] 正在安装依赖，请稍候...
    python -m pip install -r requirements.txt -q
    if errorlevel 1 (
        echo [错误] 依赖安装失败，请检查网络后重试
        pause
        exit /b 1
    )
    echo ok > .deps_installed
    echo [完成] 依赖安装完成
    echo.
)

REM 延迟3秒后自动打开浏览器
start "" cmd /c "timeout /t 3 /nobreak >nul && start http://localhost:8787"

echo 启动服务中... 浏览器将自动打开 http://localhost:8787
echo 关闭本窗口即停止服务
echo.
python app.py
pause
