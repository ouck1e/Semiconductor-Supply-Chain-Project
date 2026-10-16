@echo off
cd /d "%~dp0"
title AI agent team: new packet (simulation)
set PY=python
where py >nul 2>nul && set PY=py
set PYTHONIOENCODING=utf-8
echo Makes one blind packet from a random stock and date in the dev years (2018-2022).
echo For a chosen stock and date, run:  python agent_packets.py --ticker 2330.TW --date 2022-03-15
echo.
%PY% agent_packets.py --sample 1 --split dev
echo.
echo Open the folder above and follow 00_HOW_TO_RUN.txt.
pause
