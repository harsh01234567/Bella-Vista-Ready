@echo off
REM Stops the Bella Vista backend and frontend dev servers started by start.bat,
REM by closing the titled console windows they run in.

setlocal
set ROOT=%~dp0
set LOG_FILE=%ROOT%stop.log

call :log "===== stop.bat run ====="

call :log "Closing backend window (BellaVista-Backend) ..."
taskkill /FI "WINDOWTITLE eq BellaVista-Backend*" /T /F >nul 2>&1
if %ERRORLEVEL%==0 (
    call :log "Backend window closed."
) else (
    call :log "No backend window found (already closed?)."
)

call :log "Closing frontend window (BellaVista-Frontend) ..."
taskkill /FI "WINDOWTITLE eq BellaVista-Frontend*" /T /F >nul 2>&1
if %ERRORLEVEL%==0 (
    call :log "Frontend window closed."
) else (
    call :log "No frontend window found (already closed?)."
)

REM Fallback: free the ports in case the console windows were closed manually
REM but the underlying uvicorn/node processes are still listening.
set FOUND_8000=0
for /f "tokens=5" %%P in ('netstat -ano ^| findstr ":8000" ^| findstr "LISTENING"') do (
    set FOUND_8000=1
    call :log "Killing process on port 8000 (PID %%P) ..."
    taskkill /PID %%P /F >nul 2>&1
)
if "%FOUND_8000%"=="0" call :log "Nothing listening on port 8000."

set FOUND_5173=0
for /f "tokens=5" %%P in ('netstat -ano ^| findstr ":5173" ^| findstr "LISTENING"') do (
    set FOUND_5173=1
    call :log "Killing process on port 5173 (PID %%P) ..."
    taskkill /PID %%P /F >nul 2>&1
)
if "%FOUND_5173%"=="0" call :log "Nothing listening on port 5173."

call :log "Done. Full log: %LOG_FILE%"
endlocal
exit /b 0

:log
set MSG=%~1
echo [stop %DATE% %TIME%] %MSG%
echo [stop %DATE% %TIME%] %MSG% >> "%LOG_FILE%"
exit /b 0
