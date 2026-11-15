@echo off
rem Builds the Cricket Reel desktop app into dist\Cricket Reel (portable folder + installer).
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Run start.bat once first to set up the Python environment.
  exit /b 1
)
where ffmpeg >nul 2>nul || (echo FFmpeg not found. Install it with: winget install -e --id Gyan.FFmpeg & exit /b 1)

echo [1/4] Build tools...
".venv\Scripts\python.exe" -m pip install -q -r requirements.lock || exit /b 1
echo [2/4] Fonts and icon...
".venv\Scripts\python.exe" tools\get_fonts.py || exit /b 1
".venv\Scripts\python.exe" tools\make_icon.py || exit /b 1
echo [3/4] Packaging (a few minutes)...
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --log-level WARN cricket_reel.spec || exit /b 1
echo [4/4] Installer files...
copy /y "installer\install.ps1" "dist\Cricket Reel\" >nul
copy /y "installer\uninstall.ps1" "dist\Cricket Reel\" >nul
copy /y "installer\Install Cricket Reel.cmd" "dist\Cricket Reel\" >nul

echo.
echo Built: dist\Cricket Reel
echo   - Run "Cricket Reel.exe" directly (portable), or
echo   - Double-click "Install Cricket Reel.cmd" for a Start menu entry and desktop shortcut.
