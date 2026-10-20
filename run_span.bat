@echo off
cd /d "%~dp0"
title Agent team: time-span simulation
set PY=python
where py >nul 2>nul && set PY=py
set PYTHONIOENCODING=utf-8
echo Let the six-agent team trade one stock through a period (simulation only).
echo Stocks: 2330.TW TSMC, MU Micron, ASML.AS ASML, 2454.TW MediaTek, NVDA Nvidia, AMAT ... (see dashboard)
set /p TICKER=Ticker (for example MU):
set /p START=Start date (YYYY-MM-DD):
set /p END=End date (YYYY-MM-DD):
echo.
%PY% agent_span.py --ticker %TICKER% --start %START% --end %END%
echo.
echo Type  run  to run it with the Claude API (spends the amount above),
echo       demo  for a free demo with a simple rule instead of the agents,
set /p GO=or anything else to stop:
if /i "%GO%"=="run" %PY% agent_span.py --ticker %TICKER% --start %START% --end %END% --yes
if /i "%GO%"=="demo" %PY% agent_span.py --ticker %TICKER% --start %START% --end %END% --demo
if /i "%GO%"=="run" goto rebuild
if /i "%GO%"=="demo" goto rebuild
goto end
:rebuild
%PY% agent_report.py > nul
%PY% agent_dashboard.py
echo Open the dashboard with run_dashboard.bat, Simulations tab.
:end
pause
