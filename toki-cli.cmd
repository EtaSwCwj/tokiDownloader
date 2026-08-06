@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  call setup-gui.cmd
  if errorlevel 1 exit /b 1
)

".venv\Scripts\python.exe" "%~dp0toki_app.py" %*
exit /b %errorlevel%
