@echo off
cd /d "%~dp0"
echo.
echo ==========================================
echo   PURPLE PAPER - TRADING SIMULATOR
echo ==========================================
echo.
if not exist .env copy .env.example .env >nul
python -m pip install -r requirements.txt
if errorlevel 1 pause & exit /b 1
start "" http://127.0.0.1:8787
python -m uvicorn app:app --host 0.0.0.0 --port 8787
pause
