@echo off
cd /d "%~dp0"
where pyw >nul 2>nul
if %errorlevel% equ 0 (
    start "Codex Pulse Flutuante" pyw overlay.py
) else (
    where pythonw >nul 2>nul
    if %errorlevel% equ 0 (
        start "Codex Pulse Flutuante" pythonw overlay.py
    ) else (
        echo Python 3.10+ com Tkinter e necessario.
        echo Execute: py overlay.py
        pause
    )
)
