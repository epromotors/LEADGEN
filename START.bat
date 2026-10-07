@echo off
title TEB Solutions LeadGen OS — Launcher
color 0B

echo.
echo  ===========================================================
echo    TEB Solutions LeadGen OS — Starting All Services
echo  ===========================================================
echo.

:: ── Step 1: Start Backend (FastAPI) in a new window ──────────────────────────
echo  [1/3]  Starting FastAPI backend on port 8001...
start "TEB Backend — FastAPI :8001" cmd /k "cd /d %~dp0backend && color 0A && title TEB Backend [FastAPI :8001] && echo. && echo  Backend starting... && echo  API Docs: http://localhost:8001/docs && echo. && python run.py"

:: ── Step 2: Wait for backend to be ready (10 seconds) ────────────────────────
echo  [2/3]  Waiting 10 seconds for backend to initialise...
timeout /t 10 /nobreak >nul

:: ── Step 3: Start Frontend (Vite) in a new window ────────────────────────────
echo  [3/3]  Starting React frontend on port 5174...
start "TEB Frontend — Vite :5174" cmd /k "cd /d %~dp0frontend && color 09 && title TEB Frontend [Vite :5174] && echo. && echo  Frontend starting... && echo  App: http://localhost:5174 && echo. && npm run dev"

:: ── Step 4: Wait for Vite to spin up, then open browser ──────────────────────
echo.
echo  Waiting 6 seconds for frontend to compile...
timeout /t 6 /nobreak >nul

echo.
echo  Opening TEB Solutions LeadGen in default browser...
start "" "http://localhost:5174"

:: ── Done ─────────────────────────────────────────────────────────────────────
echo.
echo  ===========================================================
echo    All services started!
echo.
echo    Backend  →  http://localhost:8001
echo    API Docs →  http://localhost:8001/docs
echo    Frontend →  http://localhost:5174
echo.
echo    Close the two terminal windows to stop services.
echo  ===========================================================
echo.
pause
