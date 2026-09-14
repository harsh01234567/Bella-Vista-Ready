@echo off
REM Stops the Bella Vista backend and frontend dev servers started by start.bat,
REM by closing the titled console windows they run in.

setlocal
echo [stop %TIME%] ===== stop.bat run =====

echo [stop %TIME%] Closing backend window BellaVista-Backend ...
taskkill /FI "WINDOWTITLE eq BellaVista-Backend*" /T /F >nul 2>&1

echo [stop %TIME%] Closing frontend window BellaVista-Frontend ...
taskkill /FI "WINDOWTITLE eq BellaVista-Frontend*" /T /F >nul 2>&1

REM Fallback: free the ports in case the console windows were closed manually
REM but the underlying uvicorn/node processes are still listening.
echo [stop %TIME%] Checking port 8000 ...
for /f "tokens=5" %%P in ('netstat -ano ^| findstr ":8000" ^| findstr "LISTENING"') do (
    echo [stop %TIME%] Killing process on port 8000, PID %%P ...
    taskkill /PID %%P /F >nul 2>&1
)

echo [stop %TIME%] Checking port 5173 ...
for /f "tokens=5" %%P in ('netstat -ano ^| findstr ":5173" ^| findstr "LISTENING"') do (
    echo [stop %TIME%] Killing process on port 5173, PID %%P ...
    taskkill /PID %%P /F >nul 2>&1
)

echo [stop %TIME%] Done.
endlocal
