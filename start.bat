@echo off
cd /d "%~dp0"
python -m pip install -q -r requirements.txt >nul 2>&1
python gbd.py
