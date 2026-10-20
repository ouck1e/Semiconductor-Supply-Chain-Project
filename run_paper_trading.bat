@echo off
cd /d "%~dp0"
title Agent paper trading (simulation)
set PY=python
where py >nul 2>nul && set PY=py
set PYTHONIOENCODING=utf-8
echo Simulation only: the agents decide paper trades; nothing is ever bought or sold.
echo The GitHub job does this every weekday. Use this for a manual day, after a git pull.
echo.
echo Downloading the latest prices ...
%PY% fetch_prices.py
%PY% exposure_model.py > nul
echo Closing paper trades whose prices have arrived ...
%PY% agent_score.py --update
echo Running the agent team on the watchlist (needs the ANTHROPIC_API_KEY environment variable) ...
%PY% agent_daily.py
%PY% agent_report.py > nul
%PY% agent_dashboard.py
echo.
echo Open the dashboard with run_dashboard.bat.
pause
