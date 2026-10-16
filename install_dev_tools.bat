@echo off
cd /d "%~dp0"
title Install Git and GitHub CLI
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install_dev_tools.ps1"
echo.
pause
