@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if errorlevel 1 (
  echo Python launcher^(py.exe^)를 찾지 못했습니다.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo [1/3] GUI 전용 Python 가상환경을 만듭니다.
  py -3 -m venv .venv
  if errorlevel 1 goto :error
)

echo [2/3] PyQt6와 프로세스 제어 의존성을 확인합니다.
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements-gui.txt
if errorlevel 1 goto :error

if not exist "node_modules" (
  echo [3/3] Node.js 의존성을 설치합니다.
  call npm install
  if errorlevel 1 goto :error
) else (
  echo [3/3] Node.js 의존성이 이미 설치되어 있습니다.
)

echo GUI 실행 준비가 완료되었습니다.
exit /b 0

:error
echo GUI 준비 중 오류가 발생했습니다.
pause
exit /b 1
