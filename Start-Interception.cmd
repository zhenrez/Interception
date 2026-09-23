@echo off
setlocal
cd /d "%~dp0"
title Interception One-Click Launcher

rem Prefer Windows' own PowerShell by absolute path so unrelated PATH entries
rem cannot redirect the launcher into Conda/NVIDIA/other toolchains.
set "INTERCEPTION_PS="
if exist "%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" (
  set "INTERCEPTION_PS=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"
)
if not defined INTERCEPTION_PS if exist "%ProgramFiles%\PowerShell\7\pwsh.exe" (
  set "INTERCEPTION_PS=%ProgramFiles%\PowerShell\7\pwsh.exe"
)
if not defined INTERCEPTION_PS (
  where powershell.exe >nul 2>nul
  if not errorlevel 1 set "INTERCEPTION_PS=powershell.exe"
)
if not defined INTERCEPTION_PS (
  where pwsh.exe >nul 2>nul
  if not errorlevel 1 set "INTERCEPTION_PS=pwsh.exe"
)

if not defined INTERCEPTION_PS (
  echo.
  echo Interception could not find PowerShell.
  echo Windows 11 normally includes Windows PowerShell.
  echo No system settings were changed.
  pause
  exit /b 1
)

"%INTERCEPTION_PS%" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start-windows.ps1" %*
set "INTERCEPTION_EXIT=%ERRORLEVEL%"
if not "%INTERCEPTION_EXIT%"=="0" pause
exit /b %INTERCEPTION_EXIT%
