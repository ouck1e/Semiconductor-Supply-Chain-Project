@echo off
cd /d "%~dp0"
title Semiconductor Risk Engine - Phase 1 data pull
set PY=python
where py >/dev/null 2>/dev/null && set PY=py
(echo Using: %PY% & where python & where py & %PY% --version & %PY% -c "import sys; print(sys.executable)") > install_log.txt 2>&1
echo [1/2] Installing packages...
%PY% -m pip install -r requirements.txt >> install_log.txt 2>&1
type install_log.txt
echo.
echo [2/2] Pulling UN Comtrade data (about 5 minutes)...
set PYTHONUNBUFFERED=1
set PYTHONIOENCODING=utf-8
%PY% fetch_trade.py > run_log.txt 2>&1
type run_log.txt
echo.
echo Finished. Logs saved to install_log.txt and run_log.txt
pause
