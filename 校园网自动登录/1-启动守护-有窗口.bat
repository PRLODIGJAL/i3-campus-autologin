@echo off
cd /d "%~dp0"
echo ============================================
echo  DGUT Auto Login - Watch Mode (window)
echo  Close this window to stop.
echo ============================================
echo.
"C:\Python314\python.exe" autologin.py --watch
echo.
echo Stopped. Press any key to close.
pause >nul
