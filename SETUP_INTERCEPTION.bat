@echo off
call "%~dp0Start-Interception.cmd" -VerifyOnly
exit /b %ERRORLEVEL%
