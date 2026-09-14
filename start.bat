@echo off
REM Starts the Bella Vista backend (FastAPI/uvicorn) and frontend (Vite) dev servers
REM in separate, titled windows so stop.bat can find and close them later.
REM Creates the backend venv / installs npm deps automatically if missing.

setlocal
set ROOT=%~dp0

if not exist "%ROOT%backend\.venv\Scripts\activate.bat" (
    echo [start] backend\.venv not found, creating it and installing dependencies...
    python -m venv "%ROOT%backend\.venv" || goto :error
    call "%ROOT%backend\.venv\Scripts\activate.bat" || goto :error
    pip install -r "%ROOT%backend\requirements.txt" || goto :error
) else (
    call "%ROOT%backend\.venv\Scripts\activate.bat" || goto :error
    pip install -q -r "%ROOT%backend\requirements.txt" || goto :error
)

if not exist "%ROOT%frontend\node_modules" (
    echo [start] frontend\node_modules not found, running npm install...
    pushd "%ROOT%frontend"
    call npm install || goto :error
    popd
)

echo [start] Launching backend on http://localhost:8000 ...
start "BellaVista-Backend" cmd /k "cd /d "%ROOT%backend" && call .venv\Scripts\activate.bat && uvicorn main:app --reload --port 8000"

echo [start] Launching frontend on http://localhost:5173 ...
start "BellaVista-Frontend" cmd /k "cd /d "%ROOT%frontend" && npm run dev"

echo [start] Both servers are starting in separate windows.
echo [start] Run stop.bat to shut them down.
endlocal
exit /b 0

:error
echo [start] Setup failed. See the error above.
pause
endlocal
exit /b 1
