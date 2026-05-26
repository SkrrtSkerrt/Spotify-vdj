@echo off
setlocal enabledelayedexpansion
REM Build a standalone Windows .exe for Spotify VDJ
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    py -3 -m venv .venv
)

call ".venv\Scripts\activate.bat"
python -m pip install --upgrade pip
python -m pip install -r requirements.txt pyinstaller

if not exist "icon.ico" (
    echo Missing icon.ico. Put the icon file in the project root before building.
    exit /b 1
)

set DATA_ARGS=--add-data "icon.ico;."
if exist "ffmpeg.exe" (
    set DATA_ARGS=!DATA_ARGS! --add-data "ffmpeg.exe;."
)

pyinstaller --noconfirm --clean --onefile --windowed --name "SpotifyVDJ" --icon=icon.ico !DATA_ARGS! main.py

echo Done. Check dist\SpotifyVDJ.exe
