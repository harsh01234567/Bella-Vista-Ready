@echo off
REM Starts the Bella Vista backend (FastAPI/uvicorn) and frontend (Vite) dev servers
REM in separate, titled windows so stop.bat can find and close them later.

setlocal
set ROOT=%~dp0

if not exist "%ROOT%backend\.venv\Scripts\activate.bat" (
    echo [start] backend\.venv not found. Create it first:
    echo         python -m venv .venv
    echo         .venv\Scripts\Activate.ps1
    echo         pip install -r requirements.txt
    pause
    exit /b 1
)

echo [start] Launching backend on http://localhost:8000 ...
start "BellaVista-Backend" cmd /k "cd /d "%ROOT%backend" && call .venv\Scripts\activate.bat && uvicorn main:app --reload --port 8000"

echo [start] Launching frontend on http://localhost:5173 ...
start "BellaVista-Frontend" cmd /k "cd /d "%ROOT%frontend" && npm run dev"

echo [start] Both servers are starting in separate windows.
echo [start] Run stop.bat to shut them down.
endlocal
