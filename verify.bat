@echo off
chcp 65001 >nul
cd /d "%~dp0"
python campus_login.py verify
pause
