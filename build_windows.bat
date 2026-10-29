@echo off
setlocal
cd /d "%~dp0"
echo === Tracker: Windows build ===
where py >nul 2>nul
if %errorlevel%==0 (set "PY=py -3") else (set "PY=python")
%PY% -m venv .buildenv
if errorlevel 1 goto :fail
call .buildenv\Scripts\activate.bat
python -m pip install --upgrade pip
if errorlevel 1 goto :fail
python -m pip install -r requirements.txt pyinstaller
if errorlevel 1 goto :fail
python -c "import flask, flask_sqlalchemy, flask_login, werkzeug, docx, reportlab, segno, openpyxl" || goto :fail
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
pyinstaller --noconfirm --clean --windowed --name Tracker --collect-all flask --collect-all flask_sqlalchemy --collect-all flask_login --collect-all segno --collect-all reportlab --collect-all openpyxl launcher.py
if errorlevel 1 goto :fail
if not exist dist\Tracker\Tracker.exe goto :fail
echo.
echo READY: dist\Tracker\Tracker.exe
goto :end
:fail
echo BUILD FAILED.
exit /b 1
:end
endlocal
