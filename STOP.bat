@echo off
title TEB Solutions — Stop All Services
color 0C

echo.
echo  ===========================================================
echo    TEB Solutions LeadGen OS — Stopping All Services
echo  ===========================================================
echo.

echo  Stopping Python (FastAPI/Uvicorn)...
taskkill /F /IM python.exe >nul 2>&1
echo  Done.

echo  Stopping Node.js (Vite frontend)...
taskkill /F /IM node.exe >nul 2>&1
echo  Done.

echo.
echo  All services stopped.
echo  ===========================================================
echo.
pause
