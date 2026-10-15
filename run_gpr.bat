@echo off
cd /d "%~dp0"
title Geopolitical Risk Index download
set PY=python
where py >nul 2>nul && set PY=py
%PY% -m pip install requests xlrd openpyxl > gpr_install_log.txt 2>&1
set PYTHONIOENCODING=utf-8
%PY% fetch_gpr.py > gpr_log.txt 2>&1
type gpr_log.txt
echo.
echo Finished. You can close this window.
pause
