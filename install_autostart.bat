@echo off
title Install Fall Guard Autostart
cd /d "%~dp0"

echo ===================================================
echo   Setup Fall Guard Autostart on Windows Boot
echo ===================================================

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$WshShell = New-Object -ComObject WScript.Shell; " ^
    "$StartupFolder = [Environment]::GetFolderPath('Startup'); " ^
    "$ShortcutPath = Join-Path $StartupFolder 'FallGuard.lnk'; " ^
    "$Shortcut = $WshShell.CreateShortcut($ShortcutPath); " ^
    "$Shortcut.TargetPath = (Join-Path '%~dp0' 'start_app.bat'); " ^
    "$Shortcut.WorkingDirectory = '%~dp0'; " ^
    "$Shortcut.Description = 'Fall Guard Fall Detection System'; " ^
    "$Shortcut.WindowStyle = 1; " ^
    "$Shortcut.Save(); " ^
    "Write-Host '[SUCCESS] Created Startup shortcut successfully!' -ForegroundColor Green"

echo.
echo ===================================================
echo เรียบร้อย! ระบบจะเปิดทำงานอัตโนมัติเมื่อเปิดเครื่อง (เข้าสู่ Windows)
echo หากต้องการยกเลิก สามารถดับเบิลคลิกไฟล์ 'uninstall_autostart.bat'
echo ===================================================
pause
