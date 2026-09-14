@echo off
REM Stops the Bella Vista backend and frontend dev servers started by start.bat,
REM by closing the titled console windows they run in.

setlocal
echo [stop %TIME%] ===== stop.bat run =====

echo [stop %TIME%] Closing backend window (BellaVista-Backend) ...
taskkill /FI "WINDOWTITLE eq BellaVista-Backend*" /T /F >nul 2>&1
if %ERRORLEVEL%==0 (
    echo [stop %TIME%] Backend window closed.
) else (
    echo [stop %TIME%] No backend window found (already closed?).
)

echo [stop %TIME%] Closing frontend window (BellaVista-Frontend) ...
taskkill /FI "WINDOWTITLE eq BellaVista-Frontend*" /T /F >nul 2>&1
if %ERRORLEVEL%==0 (
    echo [stop %TIME%] Frontend window closed.
) else (
    echo [stop %TIME%] No frontend window found (already closed?).
)

REM Fallback: free the ports in case the console windows were closed manually
REM but the underlying uvicorn/node processes are still listening.
set FOUND_8000=0
for /f "tokens=5" %%P in ('netstat -ano ^| findstr ":8000" ^| findstr "LISTENING"') do (
    set FOUND_8000=1
    echo [stop %TIME%] Killing process on port 8000 (PID %%P) ...
    taskkill /PID %%P /F >nul 2>&1
)
if "%FOUND_8000%"=="0" echo [stop %TIME%] Nothing listening on port 8000.

set FOUND_5173=0
for /f "tokens=5" %%P in ('netstat -ano ^| findstr ":5173" ^| findstr "LISTENING"') do (
    set FOUND_5173=1
    echo [stop %TIME%] Killing process on port 5173 (PID %%P) ...
    taskkill /PID %%P /F >nul 2>&1
)
if "%FOUND_5173%"=="0" echo [stop %TIME%] Nothing listening on port 5173.

echo [stop %TIME%] Done.
endlocal
