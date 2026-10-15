@echo off
setlocal EnableExtensions
title AYESHA FX - one-time setup (advisory only, never places orders)
REM Double-click this file once. It installs the scanner, stores your OANDA token in YOUR Windows
REM user environment (never in the repository), asks your Exness equity, confirms the Exness
REM contract, pairs the phone and runs a health check. Safe to run again at any time.

cd /d "%~dp0\.."
echo.
echo === 1/7  Python ===
set PY=
where py >nul 2>nul && set PY=py -3
if not defined PY (where python >nul 2>nul && set PY=python)
if not defined PY (
  echo Python was not found. Install Python 3.12 from https://www.python.org/downloads/
  echo During setup tick "Add python.exe to PATH", then run this file again.
  pause
  exit /b 1
)
%PY% -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)"
if errorlevel 1 (
  echo Python 3.10 or newer is needed. Install Python 3.12 from https://www.python.org/downloads/
  pause
  exit /b 1
)
%PY% --version

echo.
echo === 2/7  Install AYESHA scanner ===
%PY% -m pip install --upgrade pip >nul
%PY% -m pip install -e .
if errorlevel 1 (
  echo Install failed. Check the internet connection and run this file again.
  pause
  exit /b 1
)

echo.
echo === 3/7  OANDA practice token (price data only) ===
if defined AYESHA_OANDA_TOKEN (
  echo A token is already set. Press Enter to keep it, or paste a new one.
) else (
  echo OANDA fxTrade Practice - Manage API Access - Generate. Paste the token below.
)
for /f "usebackq delims=" %%T in (`powershell -NoProfile -Command "$s = Read-Host 'Token (hidden)' -AsSecureString; [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($s))"`) do set NEWTOKEN=%%T
if defined NEWTOKEN (
  setx AYESHA_OANDA_TOKEN "%NEWTOKEN%" >nul
  set AYESHA_OANDA_TOKEN=%NEWTOKEN%
  set NEWTOKEN=
  echo Token saved in your Windows user environment.
)
if not defined AYESHA_OANDA_TOKEN (
  echo No token set. The scanner cannot read prices without it. Run this file again later.
)

echo.
echo === 4/7  Your Exness equity in USD ===
if not exist "%USERPROFILE%\AyeshaFX" mkdir "%USERPROFILE%\AyeshaFX"
set EQ=
if exist "%USERPROFILE%\AyeshaFX\equity.txt" set /p EQ=<"%USERPROFILE%\AyeshaFX\equity.txt"
if defined EQ echo Current value: %EQ%
set NEWEQ=
set /p NEWEQ=Type your Exness equity, e.g. 25 (Enter = keep): 
if defined NEWEQ set EQ=%NEWEQ%
if not defined EQ set EQ=25
%PY% -c "import sys; v=float(sys.argv[1]); sys.exit(0 if v > 0 else 1)" %EQ% 2>nul
if errorlevel 1 (
  echo "%EQ%" is not a positive number; using 25. Edit %USERPROFILE%\AyeshaFX\equity.txt later.
  set EQ=25
)
> "%USERPROFILE%\AyeshaFX\equity.txt" echo %EQ%
echo Saved equity %EQ% USD. Update it whenever your balance changes (run this file again).

echo.
echo === 5/7  Exness contract (from the Exness app: EURUSD - Specification) ===
if exist "%USERPROFILE%\AyeshaFX\broker-confirmed.json" (
  echo Already confirmed. Type Y to enter the values again, anything else to keep.
  set /p REDO=: 
) else (
  set REDO=Y
)
if /i "%REDO%"=="Y" %PY% -m ayesha.cli confirm-broker --account-type Standard

echo.
echo === 6/7  Phone pairing ===
%PY% -m ayesha.cli pair
echo Type this code in the AYESHA app: Settings - PC link - Pairing code, tick the PC link box, Save.
pause

echo.
echo === 7/7  Health check ===
%PY% -m ayesha.cli doctor

echo.
set AUTO=
set /p AUTO=Start the scanner automatically when you log on to Windows? (Y/N): 
if /i "%AUTO%"=="Y" (
  copy /y "%~dp0start-ayesha.bat" "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\AYESHA FX scanner.bat" >nul
  echo Added to Startup. Remove it from the Startup folder to stop that.
)
echo.
echo Done. Start scanning now with start-ayesha.bat (in this folder).
pause
