@echo off
cd /d "%~dp0"
title Phase 8 step 3: supply exposure
set PY=python
where py >nul 2>nul && set PY=py
set PYTHONIOENCODING=utf-8
%PY% exposure_model.py > run_exposure_log.txt 2>&1
type run_exposure_log.txt
echo.
echo Finished. You can close this window.
pause
