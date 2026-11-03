@echo off
cd /d "%~dp0"
echo Starting Antigravity Proxy (Port 8877)...
python antigravity_proxy.py --port 8877 --web-search
pause
