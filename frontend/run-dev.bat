@echo off
REM Launches the frontend dev server. Invoked by start.bat in its own window.
cd /d "%~dp0"
call npm run dev
