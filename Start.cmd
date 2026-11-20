@echo off
setlocal
cd /d "%~dp0"
set "PYTHONUTF8=1"
set "PYTHONDONTWRITEBYTECODE=1"

py -3 -c "import sys, sqlite3; assert sys.version_info >= (3,11); assert sqlite3.sqlite_version_info >= (3,37)" >nul 2>nul
if not errorlevel 1 (
    py -3 app.py --open %*
    goto finished
)

set "EDUCATION_PY=%LOCALAPPDATA%\Python\bin\python.exe"
if exist "%EDUCATION_PY%" (
    "%EDUCATION_PY%" -c "import sys, sqlite3; assert sys.version_info >= (3,11); assert sqlite3.sqlite_version_info >= (3,37)" >nul 2>nul
    if not errorlevel 1 (
        "%EDUCATION_PY%" app.py --open %*
        goto finished
    )
)

python -c "import sys, sqlite3; assert sys.version_info >= (3,11); assert sqlite3.sqlite_version_info >= (3,37)" >nul 2>nul
if not errorlevel 1 (
    python app.py --open %*
    goto finished
)

echo Install Python 3.11 or newer from https://www.python.org/downloads/
echo Enable the Python launcher or Add python.exe to PATH during installation.
echo Then close this window and run Start.cmd again.
pause
exit /b 1

:finished
if errorlevel 1 (
    echo Application failed. Read the message above.
    pause
    exit /b 1
)
exit /b 0
