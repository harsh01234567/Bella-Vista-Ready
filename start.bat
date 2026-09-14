@echo off
REM Starts the Bella Vista backend (FastAPI/uvicorn) and frontend (Vite) dev servers
REM in separate, titled windows so stop.bat can find and close them later.
REM Creates the backend venv / installs npm deps automatically if missing.
REM
REM NOTE: always invoke pip/uvicorn via "python.exe -m ..." rather than the
REM generated Scripts\pip.exe / Scripts\uvicorn.exe stubs. Those stubs are
REM unsigned, and locked-down machines (Device Guard / WDAC) block them from
REM running even though the signed python.exe itself is allowed.

setlocal
set ROOT=%~dp0
set VENV_PY=%ROOT%backend\.venv\Scripts\python.exe

if not exist "%VENV_PY%" (
    echo [start] backend\.venv not found, creating it and installing dependencies...
    python -m venv "%ROOT%backend\.venv" || goto :error
    "%VENV_PY%" -m pip install -r "%ROOT%backend\requirements.txt" || goto :error
) else (
    "%VENV_PY%" -m pip install -q -r "%ROOT%backend\requirements.txt" || goto :error
)

if not exist "%ROOT%frontend\node_modules" (
    echo [start] frontend\node_modules not found, running npm install...
    pushd "%ROOT%frontend"
    call npm install || goto :error
    popd
)

echo [start] Launching backend on http://localhost:8000 ...
start "BellaVista-Backend" cmd /k call "%ROOT%backend\run-dev.bat"

echo [start] Launching frontend on http://localhost:5173 ...
start "BellaVista-Frontend" cmd /k call "%ROOT%frontend\run-dev.bat"

echo [start] Both servers are starting in separate windows.
echo [start] Run stop.bat to shut them down.
endlocal
exit /b 0

:error
echo [start] Setup failed. See the error above.
pause
endlocal
exit /b 1
