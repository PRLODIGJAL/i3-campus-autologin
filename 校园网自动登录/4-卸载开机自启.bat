@echo off
cd /d "%~dp0"
echo ============================================
echo  Uninstall auto-start task
echo ============================================
echo.
powershell -NoProfile -ExecutionPolicy Bypass -Command "try { Unregister-ScheduledTask -TaskName 'DGUT_AutoLogin' -Confirm:$false -ErrorAction Stop; Write-Host '[OK] Task removed.' } catch { Write-Host '[INFO] Task not found or already removed.' }"
echo.
pause >nul
