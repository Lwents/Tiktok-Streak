@echo off
chcp 65001 >nul
cd /d "%~dp0"
py -3 -m venv .venv
if errorlevel 1 goto fail
.venv\Scripts\python.exe -m pip install -r requirements-windows.txt
if errorlevel 1 goto fail
if not exist config.json copy config.example.json config.json >nul
echo Hoan tat. Chay start-windows.bat de mo app TikTok Streak.
pause
exit /b 0
:fail
echo Cai dat that bai. Kiem tra Python 3.10+ va ket noi mang.
pause
exit /b 1
