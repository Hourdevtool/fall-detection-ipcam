@echo off
title Remove Fall Guard Autostart
echo ===================================================
echo   Remove Fall Guard from Windows Startup
echo ===================================================

set "SHORTCUT_PATH=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\FallGuard.lnk"

if exist "%SHORTCUT_PATH%" (
    del "%SHORTCUT_PATH%"
    echo [SUCCESS] ยกเลิกการเปิดโปรแกรมอัตโนมัติเรียบร้อยแล้ว
) else (
    echo [INFO] ไม่พบไฟล์ Startup Shortcut
)

echo ===================================================
pause
