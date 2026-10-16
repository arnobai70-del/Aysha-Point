@echo off
setlocal EnableExtensions
title AYESHA FX research dashboard (research-only, this PC only)
REM Research plane (0.9.0, Strategy Lab 1.0.0): a read-only dashboard on 127.0.0.1 for frozen datasets and research runs.
REM Research never sends READY or phone alerts and never places orders. It does not start, stop or change the
REM scanner (start-ayesha.bat keeps working exactly as before, with or without research).
REM   start-research.bat           show the research status and open the dashboard in your browser
REM   start-research.bat --check   status, research doctor and the dashboard security self-test, then exit
REM   exit codes: 0 OK, 1 not set up or a check failed.
cd /d "%~dp0\.."
if not defined AYESHA_HOME set "AYESHA_HOME=%USERPROFILE%\AyeshaFX"
if not exist "%AYESHA_HOME%\python-path.txt" (
  echo Run install.bat first.
  if not defined AYESHA_NONINTERACTIVE pause
  exit /b 1
)
set /p PYEXE=<"%AYESHA_HOME%\python-path.txt"
if not exist "%PYEXE%" (
  echo Python was moved or removed: "%PYEXE%". Run install.bat again.
  if not defined AYESHA_NONINTERACTIVE pause
  exit /b 1
)
"%PYEXE%" -m ayesha.cli research status
if /i "%~1"=="--check" goto check
echo.
echo Starting the research dashboard. Close this window to stop it.
"%PYEXE%" -m ayesha.cli research dashboard
set "RC=%ERRORLEVEL%"
if not defined AYESHA_NONINTERACTIVE pause
exit /b %RC%

:check
"%PYEXE%" -m ayesha.cli research doctor
if errorlevel 1 (
  echo RESEARCH DOCTOR FAILED. The live scanner is not affected.
  exit /b 1
)
"%PYEXE%" -m ayesha.cli research dashboard --check
if errorlevel 1 exit /b 1
echo Research checks passed.
exit /b 0
