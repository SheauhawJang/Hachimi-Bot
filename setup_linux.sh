#!/usr/bin/env bash
set -e

echo "=========================================================="
echo " QQ Mahjong Bot - Ubuntu 24.04 / Linux Setup Script"
echo "=========================================================="

# 1. 检查并安装基础开发工具、Python 虚拟环境与 Git LFS
echo "[*] 检查系统基础包..."
sudo apt update
sudo apt install -y python3 python3-pip python3-venv git git-lfs docker.io docker-compose-v2

# 2. 检查 Docker 权限
if ! groups $USER | grep &>/dev/null 'docker'; then
    echo "[*] 将当前用户加入 docker 用户组..."
    sudo usermod -aG docker $USER || true
fi
sudo systemctl enable --now docker || true

# 3. 检查 Git LFS 并确保拉取 ONNX 大文件模型
if command -v git-lfs &> /dev/null; then
    echo "[*] 正在校验并拉取 Git LFS 模型文件..."
    git lfs install
    git lfs pull
fi

# 4. 创建并激活虚拟环境 (适配 Ubuntu 24.04 PEP 668)
if [ ! -d ".venv" ]; then
    echo "[*] 正在创建 Python 虚拟环境 (.venv)..."
    python3 -m venv .venv
fi
source .venv/bin/activate

# 5. 安装 Python 依赖
echo "[*] 正在安装 Python 依赖..."
pip install --upgrade pip
pip install -r requirements.txt

# 6. 配置文件初始化
if [ ! -f "config.json" ]; then
    echo "[*] 创建默认 config.json..."
    cp config.example.json config.json
    echo "[!] 请检查并编辑 config.json，填入你的 Gemini API Key / Proxy 地址。"
fi

echo ""
echo "=========================================================="
echo " 全部初始化完成！"
echo "=========================================================="
echo "1. 启动 NapCat (Linux Docker 容器):"
echo "   sudo docker compose up -d"
echo "   然后在浏览器打开 http://localhost:6099/webui (或 http://<虚拟机IP>:6099/webui) 扫码登录"
echo ""
echo "2. 启动麻将机器人后台:"
echo "   ./start_bot.sh"
echo "=========================================================="
