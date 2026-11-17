@echo off
chcp 65001 >nul
title Build FreeCR.exe
cd /d "%~dp0"

python -m pip install --upgrade pyinstaller
python -m PyInstaller --noconfirm --onefile --windowed --uac-admin ^
  --name "FreeCR" ^
  --icon "assets\icon.ico" ^
  --add-data "assets;assets" ^
  main.py

pause
