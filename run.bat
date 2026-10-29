@echo off
REM ===== NVR Viewer launcher (Windows) =====
cd /d "%~dp0"

REM สร้าง virtualenv ครั้งแรก + ติดตั้ง dependencies
if not exist ".venv" (
  echo ==^> Creating virtualenv and installing dependencies...
  py -m venv .venv 2>NUL || python -m venv .venv
  .venv\Scripts\python -m pip install -q --upgrade pip
  .venv\Scripts\pip install -q -r requirements.txt
)

if "%HOST%"=="" set HOST=0.0.0.0
if "%PORT%"=="" set PORT=2318

echo ==^> Open http://localhost:%PORT%  (other LAN devices: use this PC's IP)
.venv\Scripts\uvicorn app:app --host %HOST% --port %PORT%
