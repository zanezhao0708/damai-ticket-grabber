#!/bin/bash
# 大麦网抢票工具 Web版 一键启动（Mac/Linux）
# 仅个人学习用途
cd "$(dirname "$0")"

echo "============================================"
echo "  大麦网抢票工具 Web版（仅个人学习用途）"
echo "============================================"

# 检查Python
if ! command -v python3 &> /dev/null; then
    echo "[错误] 未找到 python3，请先安装 Python 3.9+"
    exit 1
fi

# 首次运行安装依赖
if [ ! -f ".deps_installed" ]; then
    echo "[首次运行] 正在安装依赖，请稍候..."
    python3 -m pip install -r requirements.txt -q || {
        echo "[错误] 依赖安装失败，请检查网络后重试"
        exit 1
    }
    touch .deps_installed
    echo "[完成] 依赖安装完成"
fi

# 延迟3秒后自动打开浏览器
( sleep 3
  if command -v open &> /dev/null; then open http://localhost:8787
  elif command -v xdg-open &> /dev/null; then xdg-open http://localhost:8787
  fi ) &

echo "启动服务中... 浏览器将自动打开 http://localhost:8787"
echo "按 Ctrl+C 停止服务"
python3 app.py
