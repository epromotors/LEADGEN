@echo off
title TEB Solutions — Stop All Services
color 0C

echo.
echo  ===========================================================
echo    TEB Solutions LeadGen OS — Stopping All Services
echo  ===========================================================
echo.

echo  Stopping Python (FastAPI/Uvicorn on port 8001)...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr :8001 ^| findstr LISTENING') do taskkill /F /T /PID %%a >nul 2>&1
echo  Done.

echo  Stopping Node.js (Vite frontend on port 5174)...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr :5174 ^| findstr LISTENING') do taskkill /F /T /PID %%a >nul 2>&1
echo  Done.

echo.
echo  All services stopped.
echo  ===========================================================
echo.
pause
