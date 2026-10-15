@echo off
cd /d "%~dp0"
title Comtrade: more importers + Taiwan mirror data
set PY=python
where py >nul 2>nul && set PY=py
set PYTHONUNBUFFERED=1
set PYTHONIOENCODING=utf-8
echo Pulling extra Comtrade data (about 5-8 minutes). Each line is one request.
%PY% fetch_trade_extra.py 2>&1 | %PY% -c "import sys; f=open('trade_extra_log.txt','w',encoding='utf-8'); [ (sys.stdout.write(l), f.write(l), f.flush()) for l in sys.stdin ]"
echo.
echo Finished. You can close this window.
pause
