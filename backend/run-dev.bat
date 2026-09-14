@echo off
REM Launches the backend dev server. Invoked by start.bat in its own window.
cd /d "%~dp0"
".venv\Scripts\python.exe" -m uvicorn main:app --reload --port 8000
