@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist .venv\Scripts\pythonw.exe (
 echo Hay chay setup.bat truoc.
 pause
 exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" "web_app.py" --open
