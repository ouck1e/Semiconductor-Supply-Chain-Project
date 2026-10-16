@echo off
cd /d "%~dp0"
title Phase 8 baseline (simulation)
set PY=python
where py >nul 2>nul && set PY=py
set PYTHONIOENCODING=utf-8
%PY% -m pip install scipy > phase8_install_log.txt 2>&1
%PY% phase8_baseline.py > run_phase8_baseline_log.txt 2>&1
type run_phase8_baseline_log.txt
echo.
echo Finished. You can close this window.
pause
