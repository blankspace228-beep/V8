@echo off
setlocal
cd /d "%~dp0"
title Purple Paper - Windows Setup

where python >nul 2>&1
if errorlevel 1 (
  echo.
  echo [Purple Paper] Python 3.11 or newer is required.
  echo Install Python from python.org and check "Add Python to PATH", then run this again.
  echo.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo [1/4] Creating Purple Paper local environment...
  python -m venv .venv || goto :fail
)

echo [2/4] Checking app dependencies...
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r requirements.txt || goto :fail
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q "pywebview>=5.0" || goto :fail

if not exist ".env" (
  echo [3/4] Creating market-data settings file...
  copy /y ".env.example" ".env" >nul
  echo.
  echo IMPORTANT: To receive live stocks and 24/7 crypto, open Purple Paper and use MARKET DATA setup.
  echo Purple Paper itself still uses fake funds only.
  echo.
) else (
  echo [3/4] Settings ready.
)

echo [4/4] Launching Purple Paper V8 Network...
start "" ".venv\Scripts\pythonw.exe" "%~dp0desktop.py"
exit /b 0

:fail
echo.
echo Purple Paper setup failed. The error is above.
pause
exit /b 1
