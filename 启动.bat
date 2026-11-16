@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================================
echo   Smart Arena  -  Multi-game Referee ^& Smart Venue
echo ============================================================
set "PY=py"
where py >nul 2>nul || set "PY=python"
%PY% --version
if errorlevel 1 (
  echo [ERROR] Python not found. Install Python 3.8+ first.
  pause
  exit /b 1
)
echo.
echo Starting smart-venue server : 3 tables, autoplay demo
echo Please open the LAN address printed below on a phone.
echo Press Ctrl+C to stop.
echo.
%PY% run.py serve --tables 3 --autoplay
echo.
echo Server stopped.
pause