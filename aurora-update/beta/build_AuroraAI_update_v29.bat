@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "PYTHON_CMD="
where py >nul 2>nul && set "PYTHON_CMD=py"
if not defined PYTHON_CMD where python >nul 2>nul && set "PYTHON_CMD=python"

if not defined PYTHON_CMD (
  where winget >nul 2>nul || exit /b 10
  winget install -e --id Python.Python.3.12 --silent --accept-package-agreements --accept-source-agreements
  if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set "PYTHON_CMD=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
)

if not defined PYTHON_CMD exit /b 11
if not exist "AuroraAI_v29_auto_update.pyw" exit /b 12

"%PYTHON_CMD%" -m pip install --disable-pip-version-check -q PySide6 PyInstaller
if errorlevel 1 exit /b 20

"%PYTHON_CMD%" -m PyInstaller --noconfirm --clean --onefile --windowed --name AuroraAI AuroraAI_v29_auto_update.pyw
if errorlevel 1 exit /b 30

copy /Y "dist\AuroraAI.exe" "AuroraAI.exe" >nul
if errorlevel 1 exit /b 31

exit /b 0