@echo off
setlocal
cd /d "%~dp0"
echo ============================================
echo   ATT Platform - Chemical Trading Engine
echo ============================================

REM --- Python venv ---
if not exist venv\Scripts\python.exe (
    echo Creating Python virtual environment...
    where py >nul 2>nul && (py -m venv venv) || (python -m venv venv)
)
echo Installing Python dependencies...
venv\Scripts\python -m pip install -q -r requirements.txt

REM --- Frontend build (only if dist missing) ---
if not exist frontend\dist\index.html (
    echo Building frontend...
    pushd frontend
    call npm install
    call npm run build
    popd
) else (
    echo Frontend already built - skipping. Delete frontend\dist to force rebuild.
)

REM --- Print LAN IP ---
echo.
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /c:"IPv4 Address"') do (
    for /f "tokens=* delims= " %%b in ("%%a") do echo   Open http://%%b:8000 on any device on this wifi
)
echo   (or http://localhost:8000 on this machine)
echo.
echo   Teammates: share ATT_Platform_Client_Setup.bat with them -
echo   it adds an "ATT Platform" icon to their Desktop/Start Menu.
echo.

REM --- Serve with auto-restart on crash ---
:serve
venv\Scripts\python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000
echo.
echo Server exited (code %errorlevel%). Restarting in 5 seconds... Press Ctrl+C to stop.
timeout /t 5 /nobreak >nul
goto serve
endlocal
