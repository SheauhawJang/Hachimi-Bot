#!/usr/bin/env bash
cd "$(dirname "$0")"

# 检查并释放可能占用的 8080 端口旧进程
pkill -f "python3.*main\.py" 2>/dev/null || true
sleep 1

# 激活虚拟环境
source .venv/bin/activate

# 启动主服务
exec python3 main.py

