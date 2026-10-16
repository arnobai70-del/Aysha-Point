@echo off
setlocal EnableExtensions
title AYESHA FX research backup
REM Verified copy of the research registry into %AYESHA_HOME%\research\backups (older research backups rotate).
REM Only research backups are ever rotated; your capital file, journal and the live ayesha.db are not touched.
REM   exit codes: 0 OK (or nothing to back up yet), 1 not set up, 75 a research job is running (try again later).
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
"%PYEXE%" -m ayesha.cli research backup
set "RC=%ERRORLEVEL%"
if not defined AYESHA_NONINTERACTIVE pause
exit /b %RC%
