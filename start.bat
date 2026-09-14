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
set LOG_FILE=%ROOT%start.log

call :log "===== start.bat run ====="

if not exist "%VENV_PY%" (
    call :log "backend\.venv not found, creating it and installing dependencies..."
    python -m venv "%ROOT%backend\.venv" || goto :error
    call :log "venv created, installing backend requirements..."
    "%VENV_PY%" -m pip install -r "%ROOT%backend\requirements.txt" || goto :error
    call :log "backend dependencies installed."
) else (
    call :log "backend\.venv found, refreshing dependencies..."
    "%VENV_PY%" -m pip install -q -r "%ROOT%backend\requirements.txt" || goto :error
    call :log "backend dependencies up to date."
)

if not exist "%ROOT%frontend\node_modules" (
    call :log "frontend\node_modules not found, running npm install..."
    pushd "%ROOT%frontend"
    call npm install || goto :error
    popd
    call :log "frontend dependencies installed."
) else (
    call :log "frontend\node_modules found, skipping npm install."
)

call :log "Launching backend on http://localhost:8000 (window: BellaVista-Backend) ..."
start "BellaVista-Backend" cmd /k call "%ROOT%backend\run-dev.bat"

call :log "Launching frontend on http://localhost:5173 (window: BellaVista-Frontend) ..."
start "BellaVista-Frontend" cmd /k call "%ROOT%frontend\run-dev.bat"

call :log "Both servers are starting in separate windows. Run stop.bat to shut them down."
call :log "Full log: %LOG_FILE%"
endlocal
exit /b 0

:error
call :log "ERROR: setup failed, see the output above and %LOG_FILE%."
pause
endlocal
exit /b 1

:log
set MSG=%~1
echo [start %DATE% %TIME%] %MSG%
echo [start %DATE% %TIME%] %MSG% >> "%LOG_FILE%"
exit /b 0
