@echo off
REM Removes the auto-start registration created by install_autostart.bat.
REM Run AS ADMINISTRATOR.
schtasks /End /TN "ATT Platform" 2>nul
schtasks /Delete /F /TN "ATT Platform"
pause
