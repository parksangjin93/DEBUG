@echo off
REM ============================================================
REM  QA Automation - launcher
REM    run.bat                 : show registered products
REM    run.bat XVM508          : monitor one product
REM    run.bat XVM508,KP2S     : monitor multiple products
REM    run.bat --check         : diagnose configuration
REM  Edit config\products.ini to register products.
REM ============================================================
setlocal
chcp 65001 > nul
cd /d "%~dp0"

REM ---- locate python (prefer the py launcher) ----
set "PY="
where python >nul 2>&1 && set "PY=python"
where py     >nul 2>&1 && set "PY=py"

if not defined PY (
    echo.
    echo [ERROR] Python not found in PATH.
    echo         Install Python 3.10+ and tick "Add python.exe to PATH".
    echo.
    pause
    exit /b 1
)

REM ---- check dependency ----
%PY% -c "import openpyxl" >nul 2>&1
if errorlevel 1 (
    echo [INFO] installing openpyxl ...
    %PY% -m pip install openpyxl
    if errorlevel 1 (
        echo [ERROR] pip install failed. Run manually:  %PY% -m pip install openpyxl
        pause
        exit /b 1
    )
)

REM ---- no argument : show product list ----
if "%~1"=="" (
    %PY% main.py --products
    echo.
    echo  Usage:  run.bat PRODUCT
    echo  Example:  run.bat XVM508
    echo            run.bat XVM508,KP2S
    echo            run.bat --check
    echo.
    pause
    exit /b 0
)

REM ---- diagnostics ----
if "%~1"=="--check" (
    %PY% main.py --check
    pause
    exit /b 0
)

REM %* keeps the comma intact ( %1 would cut at the comma )
%PY% main.py -p %*
echo.
echo [exit code %errorlevel%]
pause
