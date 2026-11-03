@echo off
cd /d "%~dp0"
echo [1/3] Starting Antigravity Proxy (Port 8877)...
start "Antigravity-Proxy" cmd /k "cd /d %~dp0 && python antigravity_proxy.py --port 8877 --web-search"
timeout /t 2 >nul

echo [2/3] Starting QQ Bot Backend (Port 8080)...
start "QQ-Bot-Backend" cmd /k "cd /d %~dp0 && python main.py"
timeout /t 2 >nul

echo [3/3] Starting NapCatQQ...
start "NapCatQQ" cmd /k "cd /d C:\Users\Sheauhaw\NapCat\NapCat.52230.Shell && NapCatWinBootMain.exe"

echo.
echo ========================================================
echo All 3 services have been launched in separate windows!
echo WebUI: http://127.0.0.1:6099/webui (Token: 123456)
echo ========================================================
pause
