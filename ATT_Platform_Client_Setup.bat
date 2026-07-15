@echo off
setlocal
title ATT Platform - Client Setup
echo  ==================================================
echo    ATT Platform - Client Setup   (MiniMines)
echo  ==================================================
echo.
echo  This adds "ATT Platform" to your Desktop and Start
echo  Menu with the app icon. You only run this once.
echo.
echo  You need the server address - it is printed when the
echo  host machine runs start.bat (e.g. 192.168.1.50:8000).
echo.
set "SERVER="
set /p SERVER=Enter server address [ip:port]:
if "%SERVER%"=="" (
    echo No address entered - aborting.
    pause
    exit /b 1
)
set "URL=http://%SERVER%"

echo.
echo  Checking %URL% ...
powershell -NoProfile -Command "try { Invoke-WebRequest -UseBasicParsing -TimeoutSec 5 '%URL%/api/runs' | Out-Null; exit 0 } catch { exit 1 }" >nul 2>&1
if errorlevel 1 (
    echo  WARNING: could not reach %URL%
    echo  The shortcut will be created anyway - make sure the
    echo  server is running and you are on the office wifi.
) else (
    echo  Server is reachable.
)

REM --- fetch the app icon from the server ---
set "ICONDIR=%LOCALAPPDATA%\ATTPlatform"
if not exist "%ICONDIR%" mkdir "%ICONDIR%"
powershell -NoProfile -Command "try { Invoke-WebRequest -UseBasicParsing -TimeoutSec 5 '%URL%/att-icon.ico' -OutFile '%ICONDIR%\att-icon.ico' } catch {}" >nul 2>&1

REM --- Desktop + Start Menu shortcuts ---
call :writeshortcut "%USERPROFILE%\Desktop\ATT Platform.url"
call :writeshortcut "%APPDATA%\Microsoft\Windows\Start Menu\Programs\ATT Platform.url"

echo.
echo  Done! "ATT Platform" is on your Desktop and in the
echo  Start Menu. Opening it now...
start "" "%URL%"
pause
exit /b 0

:writeshortcut
>  "%~1" echo [InternetShortcut]
>> "%~1" echo URL=%URL%
if exist "%ICONDIR%\att-icon.ico" (
    >> "%~1" echo IconFile=%ICONDIR%\att-icon.ico
    >> "%~1" echo IconIndex=0
)
exit /b
