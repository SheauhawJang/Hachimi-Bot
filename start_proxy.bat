@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================================
echo 正在启动 Antigravity 隔离反向代理 (Port 8877)...
echo ============================================================
python antigravity_proxy.py --port 8877 --web-search
pause
