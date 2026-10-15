@echo off
cd /d "%~dp0"
title Install GitHub scheduled jobs
if not exist "_github\workflows" (echo Nothing to install: the _github folder is missing. & pause & exit /b)
xcopy "_github" ".github" /E /I /Y
if errorlevel 1 (echo Copy failed. & pause & exit /b)
rmdir /S /Q "_github"
echo.
echo Installed the scheduled jobs into the .github folder.
echo Next: publish this folder with GitHub Desktop (see README, "Put it on GitHub").
pause
