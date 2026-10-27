@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\flash.ps1" -Mode External
set "PICO_RESULT=%ERRORLEVEL%"
pause
exit /b %PICO_RESULT%
