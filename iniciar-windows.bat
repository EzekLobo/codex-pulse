@echo off
cd /d "%~dp0"
where py >nul 2>nul
if %ERRORLEVEL% EQU 0 (
  py codex_pulse.py
) else (
  python codex_pulse.py
)
pause
