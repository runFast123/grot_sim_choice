@echo off
rem Builds dist\GROT Simulator.exe - the desktop version of the simulator.
rem The web app (server.py on Vercel) is not affected by this build.
rem A clean virtual environment is used so only the app's own dependencies
rem end up inside the .exe.
cd /d "%~dp0"

if not exist "build\venv\Scripts\python.exe" (
    echo Creating clean build environment...
    python -m venv build\venv
    if %ERRORLEVEL% NEQ 0 goto :fail
)

echo Installing dependencies into the build environment...
build\venv\Scripts\python.exe -m pip install --disable-pip-version-check -q -r requirements.txt pyinstaller
if %ERRORLEVEL% NEQ 0 goto :fail

echo Building GROT Simulator.exe ...
build\venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --onefile --windowed ^
  --name "GROT Simulator" ^
  --add-data "index.html;." ^
  --collect-submodules choice_api ^
  --exclude-module PyQt5 --exclude-module PyQt6 --exclude-module PySide2 --exclude-module PySide6 ^
  --exclude-module matplotlib --exclude-module IPython --exclude-module scipy ^
  desktop_app.py
if %ERRORLEVEL% NEQ 0 goto :fail

echo.
echo Done: dist\GROT Simulator.exe
goto :eof

:fail
echo.
echo Build failed.
exit /b 1
