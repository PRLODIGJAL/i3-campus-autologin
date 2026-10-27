@echo off
cd /d "%~dp0"
echo ============================================
echo  Grab auth parameters (run this WHEN OFFLINE)
echo  It writes queryString into config.ini
echo ============================================
echo.
"C:\Python314\python.exe" autologin.py --grab
echo.
echo If it says "not captured", make sure:
echo   1) You are offline right now
echo   2) Open http://connect.rom.miui.com/generate_204
echo      in browser once, then run this again
echo.
pause >nul
