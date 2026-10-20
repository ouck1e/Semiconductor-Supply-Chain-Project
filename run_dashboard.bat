@echo off
cd /d "%~dp0"
title Agent Trading Desk (simulation)
set PY=python
where py >nul 2>nul && set PY=py
set PYTHONIOENCODING=utf-8
echo Rebuilding the dashboard data from data\agents and market.db ...
%PY% agent_report.py > nul
%PY% agent_dashboard.py
echo.
echo Opening http://localhost:8010  (close this window to stop the dashboard)
start "" http://localhost:8010
%PY% -m http.server -d dashboard 8010
