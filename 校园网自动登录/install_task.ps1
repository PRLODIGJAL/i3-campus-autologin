# Install DGUT_AutoLogin scheduled task (runs at logon, background, no window)
$ErrorActionPreference = "Stop"

$dir = Split-Path -Parent $MyInvocation.MyCommand.Path
$pyScript = Join-Path $dir "autologin.py"

$py = "C:\Python314\pythonw.exe"
if (-not (Test-Path $py)) { $py = "C:\Python314\python.exe" }
if (-not (Test-Path $py)) { Write-Host "[ERROR] Python not found at C:\Python314"; exit 1 }
if (-not (Test-Path $pyScript)) { Write-Host "[ERROR] autologin.py not found in: $dir"; exit 1 }

Write-Host "Python  : $py"
Write-Host "Script  : $pyScript"
Write-Host "WorkDir : $dir"
Write-Host ""

$action = New-ScheduledTaskAction -Execute $py -Argument ('"' + $pyScript + '" --watch') -WorkingDirectory $dir
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero)

$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName "DGUT_AutoLogin" -Action $action -Trigger $trigger `
    -Settings $settings -Principal $principal -Force | Out-Null

Write-Host "[OK] Scheduled task 'DGUT_AutoLogin' installed."

Start-ScheduledTask -TaskName "DGUT_AutoLogin"
Write-Host "[OK] Task started in background (no window)."

Start-Sleep -Seconds 2
$info = Get-ScheduledTask -TaskName "DGUT_AutoLogin"
Write-Host ("State   : " + $info.State)
Write-Host ""
Write-Host "Log file: $dir\login.log"
