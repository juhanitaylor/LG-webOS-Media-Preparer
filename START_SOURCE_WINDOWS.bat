@echo off
cd /d "%~dp0"
where py >nul 2>&1
if %ERRORLEVEL% EQU 0 (
  py -3 run_gui.py
) else (
  python run_gui.py
)
if errorlevel 1 pause
