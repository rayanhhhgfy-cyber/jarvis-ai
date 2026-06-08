@echo off
title J.A.R.V.I.S. — Desktop Client Daemon
cd /d "%~dp0"
echo ============================================
echo    J.A.R.V.I.S. — Desktop Client Daemon
echo ============================================
echo.
echo Starting local daemon, connecting to:
echo   http://localhost:8000
echo.
echo Press Ctrl+C to stop.
echo.
python -m local_client.daemon
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERROR] The daemon exited with code %ERRORLEVEL%.
    echo Make sure the backend is running on port 8000.
    echo.
    pause
)
