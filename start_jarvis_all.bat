@echo off
cd /d "C:\Users\Lenovo\Downloads\jarvis-ai-master (2)\jarvis-ai-master"
echo ============================================
echo   J.A.R.V.I.S. OMEGA — Server Startup Suite
echo ============================================
echo.
echo Starting Backend (uvicorn on port 8000)...
start "JARVIS Backend" cmd /c "python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000"
timeout /t 3 /nobreak > nul
echo Starting Frontend (npm run dev on port 3000)...
start "JARVIS Frontend" cmd /c "cd frontend && npm run dev"
timeout /t 5 /nobreak > nul
echo Opening browser to http://localhost:3000...
start http://localhost:3000
echo.
echo Both servers have been launched in separate windows.
echo You can close this window now.
