@echo off
setlocal
cd /d "%~dp0"

echo ==========================================
echo Equipment Tracker - setup and UI tests
echo ==========================================
echo.

where py >nul 2>nul
if errorlevel 1 (
    echo ERROR: Python launcher "py" not found. Install Python 3.12 and enable the launcher.
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo [1/6] Creating virtual environment...
    py -3.12 -m venv .venv
    if errorlevel 1 goto :error
) else (
    echo [1/6] Virtual environment already exists; skipping creation.
)

echo.
echo [2/6] Installing UI test dependencies...
".venv\Scripts\python.exe" -m pip install -r requirements-ui.txt
if errorlevel 1 goto :error

echo.
echo [3/6] Installing application dependencies...
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :error

echo.
echo [4/6] Installing Playwright Chromium...
".venv\Scripts\python.exe" -m playwright install chromium
if errorlevel 1 goto :error

echo.
echo [5/6] Setting UI test configuration...
set "UI_BASE_URL=http://127.0.0.1:5000"
set "UI_USERNAME=admin"
set "UI_PASSWORD=12345678"

echo.
echo Starting the app in a separate window...
start "Equipment Tracker app.py" cmd /k ""%CD%\.venv\Scripts\python.exe" "%CD%\app.py""

echo Waiting 5 seconds for the app to start...
timeout /t 5 /nobreak >nul

echo.
echo [6/6] Running UI tests...
".venv\Scripts\python.exe" -m unittest discover -s tests\ui -v
set "TEST_EXIT=%ERRORLEVEL%"

echo.
if "%TEST_EXIT%"=="0" (
    echo UI tests completed successfully.
    echo Check test-results\ui\ for screenshots and layout-report.txt.
) else (
    echo UI tests failed. Review the error output above.
)

echo.
echo The app is still running in the separate window.
echo Close that window when finished.
echo.
pause
exit /b %TEST_EXIT%

:error
echo.
echo ERROR: A setup command failed. Review the output above.
pause
exit /b 1
