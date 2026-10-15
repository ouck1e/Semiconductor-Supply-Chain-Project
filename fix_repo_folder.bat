@echo off
cd /d "%~dp0"
title Fix repository folder
set "SUB=Semiconductor Supply Chain Project"
if exist ".git" (echo This folder is already a git repository. Nothing to do. & pause & exit /b)
if not exist "%SUB%\.git" (echo Could not find "%SUB%\.git". & pause & exit /b)
attrib -h "%SUB%\.git"
move "%SUB%\.git" ".git"
if errorlevel 1 (echo Move failed. Close GitHub Desktop and try again. & pause & exit /b)
attrib +h ".git"
if exist "%SUB%\.gitattributes" move "%SUB%\.gitattributes" ".gitattributes"
rmdir "%SUB%"
echo.
echo Done. This folder is now your GitHub repository.
echo In GitHub Desktop: click "Locate..." and choose this folder, then commit and push.
pause
