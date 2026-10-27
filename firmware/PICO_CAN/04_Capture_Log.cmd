@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\capture.ps1"
set "PICO_RESULT=%ERRORLEVEL%"
pause
exit /b %PICO_RESULT%
