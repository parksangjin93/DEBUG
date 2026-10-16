@echo off
REM ============================================================
REM  QA Automation - GUI launcher  (double-click this file)
REM ============================================================
setlocal
chcp 65001 > nul
cd /d "%~dp0"

set "PY="
where python  >nul 2>&1 && set "PY=python"
where py      >nul 2>&1 && set "PY=py"
REM pythonw = no black console window
set "PYW="
where pythonw >nul 2>&1 && set "PYW=pythonw"
where pyw     >nul 2>&1 && set "PYW=pyw"

if not defined PY (
    echo.
    echo [ERROR] Python not found in PATH.
    echo         Install Python 3.10+ and tick "Add python.exe to PATH".
    echo.
    pause
    exit /b 1
)

%PY% -c "import tkinter" >nul 2>&1
if errorlevel 1 (
    echo [ERROR] tkinter is missing from this Python installation.
    echo         Re-run the Python installer and enable "tcl/tk and IDLE".
    pause
    exit /b 1
)

%PY% -c "import openpyxl" >nul 2>&1
if errorlevel 1 (
    echo [INFO] installing openpyxl ...
    %PY% -m pip install openpyxl
    if errorlevel 1 (
        echo [ERROR] pip install failed. Run:  %PY% -m pip install openpyxl
        pause
        exit /b 1
    )
)

if defined PYW (
    start "" %PYW% qa_gui.py
) else (
    %PY% qa_gui.py
    if errorlevel 1 pause
)
