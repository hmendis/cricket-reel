@echo off
rem Cricket Reel - starts the local backend and opens the app in your browser.
setlocal
cd /d "%~dp0"
set PORT=8000

if not exist ".venv\Scripts\python.exe" (
  echo First run: setting up Python environment...
  where py >nul 2>nul && (py -3 -m venv .venv) || (python -m venv .venv)
  if errorlevel 1 goto :nopython
  ".venv\Scripts\python.exe" -m pip install --upgrade pip -q
  ".venv\Scripts\python.exe" -m pip install -r requirements.lock -q
  if errorlevel 1 goto :piperror
  ".venv\Scripts\python.exe" tools\get_fonts.py
)

if not exist ".env" (
  echo.
  echo  NOTE: no Claude API key in a .env file. Paste your key in the app's Settings instead
  echo        (stored encrypted for your Windows user). Spawtz score sheet links work without one.
  echo.
)

where ffprobe >nul 2>nul || echo  NOTE: FFmpeg not found. Install it with:  winget install -e --id Gyan.FFmpeg

echo Starting Cricket Reel on http://127.0.0.1:%PORT%  (close this window to stop it)
start "" /b cmd /c "timeout /t 2 >nul & start http://127.0.0.1:%PORT%/"
".venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port %PORT%
goto :eof

:nopython
echo Python 3.11+ is required. Install it with:  winget install -e --id Python.Python.3.12
pause
goto :eof

:piperror
echo Installing Python packages failed. Check your internet connection and run start.bat again.
rmdir /s /q .venv
pause
