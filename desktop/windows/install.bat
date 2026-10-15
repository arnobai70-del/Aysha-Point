@echo off
setlocal EnableExtensions
title AYESHA FX - one-time setup (advisory only, never places orders)
REM Double-click once. Installs the scanner and runs `ayesha setup`: OANDA token (typed hidden,
REM saved in YOUR Windows user settings through the registry API, never in the repository or on a
REM command line), Exness equity, Exness contract values, phone pairing, health check, optional
REM Startup entry. Safe to run again: Enter keeps each value.
REM Optional argument: --no-publish (skip the phone relay test).

cd /d "%~dp0\.."
if not defined AYESHA_HOME set "AYESHA_HOME=%USERPROFILE%\AyeshaFX"
echo.
echo === Python ===
set "PY="
python -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>nul && set "PY=python"
if not defined PY (
  py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>nul && set "PY=py -3"
)
if not defined PY (
  echo Python 3.11 or newer was not found.
  echo Install Python 3.12 from https://www.python.org/downloads/ and tick "Add python.exe to PATH",
  echo then run this file again.
  if not defined AYESHA_NONINTERACTIVE pause
  exit /b 10
)
%PY% --version

echo.
echo === Install AYESHA scanner ===
%PY% -m pip install --disable-pip-version-check -q -e .
if errorlevel 1 (
  echo Install failed. Check the internet connection and run this file again.
  if not defined AYESHA_NONINTERACTIVE pause
  exit /b 11
)
set "PYEXE="
for /f "usebackq delims=" %%P in (`%PY% -c "import sys; print(sys.executable)"`) do set "PYEXE=%%P"
if not exist "%AYESHA_HOME%" mkdir "%AYESHA_HOME%"
> "%AYESHA_HOME%\python-path.txt" echo %PYEXE%

"%PYEXE%" -m ayesha.cli setup --startup-script "%~dp0start-ayesha.bat" %*
set "RC=%ERRORLEVEL%"
echo.
echo Start scanning with start-ayesha.bat (in this folder). Local backtest: backtest-local.bat
if not defined AYESHA_NONINTERACTIVE pause
exit /b %RC%
