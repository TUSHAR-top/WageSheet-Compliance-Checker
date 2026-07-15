@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    set "PYTHON_CMD=py -3"
) else (
    where python >nul 2>nul
    if %ERRORLEVEL% EQU 0 (
        set "PYTHON_CMD=python"
    ) else (
        echo Python 3 was not found. Please install Python and ensure 'py' or 'python' is available in PATH.
        echo Then run this file again.
        pause
        exit /b 1
    )
)

echo Installing required Python packages...
%PYTHON_CMD% -m pip install --user -r requirements.txt
if errorlevel 1 (
    echo Failed to install required packages.
    pause
    exit /b 1
)

echo Starting WageSheet Compliance Checker...
echo Open http://127.0.0.1:5000 in your browser when the server starts.
%PYTHON_CMD% app.py

if errorlevel 1 (
    echo The application stopped with an error.
    pause
    exit /b 1
)
