#!/usr/bin/env bash
set -e

echo "=========================================================="
echo " QQ Mahjong Bot - Linux VM Setup Script"
echo "=========================================================="

# 1. 检查 Python 3
if ! command -v python3 &> /dev/null; then
    echo "[!] Python 3 未安装，正在通过 apt 安装..."
    sudo apt update && sudo apt install -y python3 python3-pip python3-venv git-lfs
fi

# 2. 检查 Git LFS 并拉取 ONNX 大文件模型
if command -v git-lfs &> /dev/null; then
    echo "[*] 正在拉取 Git LFS 模型文件..."
    git lfs install
    git lfs pull
fi

# 3. 创建并激活虚拟环境
if [ ! -d ".venv" ]; then
    echo "[*] 正在创建 Python 虚拟环境 (.venv)..."
    python3 -m venv .venv
fi
source .venv/bin/activate

# 4. 安装依赖
echo "[*] 正在安装 Python 依赖..."
pip install --upgrade pip
pip install -r requirements.txt

# 5. 配置文件初始化
if [ ! -f "config.json" ]; then
    echo "[*] 创建默认 config.json..."
    cp config.example.json config.json
    echo "[!] 请检查并编辑 config.json，填入你的 Gemini API Key / Proxy 地址。"
fi

echo ""
echo "=========================================================="
echo " 安装完成！"
echo "=========================================================="
echo "1. 启动 NapCat (Docker 容器):"
echo "   docker compose up -d"
echo "   然后在浏览器打开 http://<VM-IP>:6099/webui 扫码登录 QQ"
echo ""
echo "2. 启动麻将机器人后台:"
echo "   source .venv/bin/activate"
echo "   python3 main.py"
echo "=========================================================="
