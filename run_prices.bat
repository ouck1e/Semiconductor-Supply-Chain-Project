@echo off
cd /d "%~dp0"
title Chip stock prices
set PY=python
where py >nul 2>nul && set PY=py
echo Checking Python packages (first run installs yfinance)...
%PY% -m pip install yfinance requests pandas matplotlib > prices_install_log.txt 2>&1
set PYTHONIOENCODING=utf-8
%PY% fetch_prices.py
echo.
echo Finished. You can close this window.
pause
