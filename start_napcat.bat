@echo off
chcp 65001 >nul
cd /d "C:\Users\Sheauhaw\NapCat\NapCat.52230.Shell"
echo ============================================================
echo 正在启动 NapCatQQ...
echo 启动后请使用手机 QQ 扫描窗口中出现的二维码登录。
echo WebUI 后台地址: http://127.0.0.1:6099/webui (Token: 123456)
echo ============================================================
call napcat.bat
pause
