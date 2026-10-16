@echo off
title Install Git and GitHub CLI
echo Installing Git for Windows and the GitHub CLI with winget.
echo Windows may ask "Do you want to allow this app to make changes" - click Yes.
echo.
where winget >NUL 2>NUL || (echo winget is not available on this PC. Install "App Installer" from the Microsoft Store, then run this again. & pause & exit /b)
winget install --id Git.Git -e --source winget --accept-package-agreements --accept-source-agreements
winget install --id GitHub.cli -e --source winget --accept-package-agreements --accept-source-agreements
echo.
set "GH=%ProgramFiles%\GitHub CLI\gh.exe"
if not exist "%GH%" set "GH=gh"
echo Now signing the GitHub CLI in to your GitHub account.
echo It will show a one-time code and open github.com in your browser: paste the code there and click Authorize.
echo.
"%GH%" auth login --hostname github.com --git-protocol https --web
echo.
"%GH%" auth status
echo.
echo Done. Close this window, then restart the Claude desktop app so Claude Code can find git and gh.
pause
