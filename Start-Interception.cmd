@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" goto ready
py -3.13 -c "import sys" >nul 2>&1
if not errorlevel 1 (
  py -3.13 -m venv .venv
  goto checkvenv
)
py -3.11 -c "import sys" >nul 2>&1
if not errorlevel 1 (
  py -3.11 -m venv .venv
  goto checkvenv
)
py -3.12 -c "import sys" >nul 2>&1
if not errorlevel 1 (
  py -3.12 -m venv .venv
  goto checkvenv
)
echo Install CPython 3.13 or 3.11 from python.org with the Python Launcher and Tcl/Tk enabled.
pause
exit /b 1
:checkvenv
if not exist ".venv\Scripts\python.exe" goto failed
:ready
.venv\Scripts\python.exe -c "import interception, jsonschema, tkinter" >nul 2>&1
if not errorlevel 1 goto launch
.venv\Scripts\python.exe -m pip --isolated install --index-url https://pypi.org/simple -e .
if errorlevel 1 goto failed
:launch
.venv\Scripts\python.exe -m interception desktop
if errorlevel 1 goto failed
exit /b 0
:failed
echo Setup or launch failed. The error above explains what needs attention.
pause
exit /b 1
