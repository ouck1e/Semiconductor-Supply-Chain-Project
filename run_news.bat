@echo off
cd /d "%~dp0"
title Semiconductor news collector
set PY=python
where py >nul 2>nul && set PY=py
echo Checking Python packages...
%PY% -m pip install requests > news_install_log.txt 2>&1
set PYTHONIOENCODING=utf-8
%PY% news_collector.py
%PY% build_globe_news.py
echo.
echo Finished. You can close this window.
pause
