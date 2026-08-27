@echo off
setlocal
cd /d "%~dp0"
title Purple Paper Network Server
where python >nul 2>&1 || (echo Python 3.11+ is required.& pause & exit /b 1)
if not exist ".venv\Scripts\python.exe" python -m venv .venv
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r requirements.txt
if not exist ".env" copy /y ".env.example" ".env" >nul
echo.
echo Purple Paper Network starting on this computer...
echo Local: http://127.0.0.1:8787
echo LAN:   http://YOUR-PC-IP:8787
echo.
echo For public Internet hosting, deploy the included Dockerfile to a cloud host and set HOSTED_MODE=1, COOKIE_SECURE=1, DATABASE_PATH, and OWNER_SETUP_CODE.
echo.
".venv\Scripts\python.exe" -m uvicorn app:app --host 0.0.0.0 --port 8787
pause
