@echo off
cd /d "%~dp0"
echo ============================================
echo  Install auto-start task (run at logon)
echo ============================================
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install_task.ps1"
echo.
pause >nul
