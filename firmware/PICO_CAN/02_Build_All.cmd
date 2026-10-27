@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\build.ps1" -Mode All
set "PICO_RESULT=%ERRORLEVEL%"
pause
exit /b %PICO_RESULT%
