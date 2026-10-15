@echo off
setlocal EnableExtensions
title AYESHA FX - local backtest (your token stays on this PC)
REM Builds the multi-year validation report on THIS PC with the token saved by install.bat.
REM Nothing is uploaded: price data and the report stay in %USERPROFILE%\AyeshaFX\backtest\.
REM Optional arguments are passed through, e.g.:  backtest-local.bat --pairs EURUSD,GBPUSD --days 730
cd /d "%~dp0\.."
if not defined AYESHA_HOME set "AYESHA_HOME=%USERPROFILE%\AyeshaFX"
if not exist "%AYESHA_HOME%\python-path.txt" (
  echo Run install.bat first.
  if not defined AYESHA_NONINTERACTIVE pause
  exit /b 1
)
set /p PYEXE=<"%AYESHA_HOME%\python-path.txt"
echo Downloading history from OANDA and replaying it. This can take several minutes...
"%PYEXE%" -m ayesha.cli backtest-run %*
set "RC=%ERRORLEVEL%"
if "%RC%"=="0" (
  echo Opening the report folder...
  if not defined AYESHA_NONINTERACTIVE start "" "%AYESHA_HOME%\backtest"
)
if not defined AYESHA_NONINTERACTIVE pause
exit /b %RC%
