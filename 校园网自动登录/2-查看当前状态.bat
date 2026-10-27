@echo off
cd /d "%~dp0"
echo ============================================
echo  Check current campus network status
echo ============================================
echo.
"C:\Python314\python.exe" autologin.py --check
echo.
pause >nul
