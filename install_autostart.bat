@echo off
REM Registers the ATT Platform to start automatically when this machine boots
REM (via Windows Task Scheduler, runs hidden in the background).
REM Run this file AS ADMINISTRATOR on the always-on office PC.
cd /d "%~dp0"

schtasks /Create /F /TN "ATT Platform" ^
  /TR "\"%~dp0start.bat\"" ^
  /SC ONSTART /RU SYSTEM /RL HIGHEST

if %errorlevel%==0 (
    echo.
    echo Done. The ATT Platform will start automatically on boot.
    echo Starting it now...
    schtasks /Run /TN "ATT Platform"
    echo Open http://localhost:8000 to verify.
) else (
    echo.
    echo FAILED - make sure you ran this as Administrator.
)
pause
