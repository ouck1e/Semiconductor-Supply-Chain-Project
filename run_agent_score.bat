@echo off
cd /d "%~dp0"
title AI agent team: score a run (simulation)
set PY=python
where py >nul 2>nul && set PY=py
set PYTHONIOENCODING=utf-8
echo Save the Boss's reply as boss.txt in the run's folder first.
set /p RUN=Run id (for example run-20261016-093000-a1b2):
%PY% agent_score.py %RUN%
echo.
pause
