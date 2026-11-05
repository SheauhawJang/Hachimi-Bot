@echo off
setlocal
set "NAPCAT_WORKDIR=C:\Users\Sheauhaw\NapCat\NapCat.52230.Shell"
set "NAPCAT_QUICK_ACCOUNT=2681496244"
cd /d "C:\Users\Sheauhaw\NapCat\NapCat.52230.Shell\versions\9.9.33-52230\resources\app\napcat"
echo ========================================================
echo Starting NapCat for 2681496244...
echo ========================================================
call launcher-win10-user.bat -q 2681496244
pause
