@echo off
cd /d "%~dp0"
title Phase 4-5: per-wafer usage, cost model and DCF
set PY=python
where py >nul 2>nul && set PY=py
set PYTHONIOENCODING=utf-8
%PY% phase4_wafer_usage.py > run_phase4_log.txt 2>&1
type run_phase4_log.txt
%PY% phase5_cost_dcf.py > run_phase5_log.txt 2>&1
type run_phase5_log.txt
echo.
echo Finished. You can close this window.
pause
