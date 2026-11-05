@echo off
cd /d "%~dp0"
echo Starting Antigravity Proxy (0.0.0.0:8877)...
python antigravity_proxy.py --host 0.0.0.0 --port 8877 --web-search
pause
