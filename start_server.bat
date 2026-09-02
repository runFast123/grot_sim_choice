@echo off
title GROT Scalper - Choice OpenAPI Simulator Server
cd /d "%~dp0"
echo ========================================================
echo   GROT Scalper Dynamic Ladder Simulator (Choice OpenAPI)
echo ========================================================
echo.
echo Checking & installing Python dependencies...
python -m pip install -r requirements.txt
echo.
echo Starting Python Local Server on http://localhost:5000 ...
start http://localhost:5000
python server.py
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo Trying fallback Python executable...
    "C:\Users\%USERNAME%\AppData\Local\Python\pythoncore-3.14-64\python.exe" server.py
)
pause
