@echo off
chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
title FreeCR // by hardovere
cd /d "%~dp0"

if exist ".venv\Scripts\pythonw.exe" (
    start "" ".venv\Scripts\pythonw.exe" main.py
    exit /b
)

if exist "C:\Users\%USERNAME%\AppData\Local\Python\pythoncore-3.15-64\pythonw.exe" (
    start "" "C:\Users\%USERNAME%\AppData\Local\Python\pythoncore-3.15-64\pythonw.exe" main.py
    exit /b
)

where pythonw >nul 2>nul
if %errorlevel%==0 (
    start "" pythonw main.py
    exit /b
)

python main.py
