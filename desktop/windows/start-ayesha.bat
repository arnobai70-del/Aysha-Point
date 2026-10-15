@echo off
setlocal EnableExtensions EnableDelayedExpansion
title AYESHA FX scanner (advisory only, never places orders)
REM Daily start (set up once with install.bat). Restarts the scanner after a crash or a network
REM failure. Stops for good on problems a restart cannot fix: missing setup or a rejected token.
REM Optional argument: maximum number of restarts (default: unlimited).
REM   exit codes: 0 stopped normally, 1 not set up, 2 config error, 3 token rejected, 4+ gave up.
cd /d "%~dp0\.."
if not defined AYESHA_HOME set "AYESHA_HOME=%USERPROFILE%\AyeshaFX"
if not defined AYESHA_RESTART_DELAY set "AYESHA_RESTART_DELAY=60"
set "MAX=%~1"
if not exist "%AYESHA_HOME%\python-path.txt" goto notsetup
if not exist "%AYESHA_HOME%\equity.txt" goto notsetup
set /p PYEXE=<"%AYESHA_HOME%\python-path.txt"
set /p EQ=<"%AYESHA_HOME%\equity.txt"
if not exist "%PYEXE%" (
  echo Python was moved or removed: "%PYEXE%". Run install.bat again.
  if not defined AYESHA_NONINTERACTIVE pause
  exit /b 1
)
set /a RESTARTS=0
:loop
echo %date% %time%  starting scanner, equity %EQ% USD. Close this window to stop.
"%PYEXE%" -m ayesha.cli scan --feed oanda --equity %EQ% --account-type Standard --news-ff --push
set "RC=!ERRORLEVEL!"
if "!RC!"=="0" (
  echo Scanner stopped.
  exit /b 0
)
if "!RC!"=="2" (
  echo CONFIG PROBLEM: run install.bat again ^(token, equity^). Not restarting.
  if not defined AYESHA_NONINTERACTIVE pause
  exit /b 2
)
if "!RC!"=="3" (
  echo OANDA REJECTED THE TOKEN: create a new token and run install.bat again. Not restarting.
  if not defined AYESHA_NONINTERACTIVE pause
  exit /b 3
)
set /a RESTARTS+=1
if defined MAX if !RESTARTS! GTR %MAX% (
  echo Gave up after %MAX% restarts ^(last exit code !RC!^).
  exit /b 4
)
echo Scanner exited with code !RC! ^(network or data problem^). Restart !RESTARTS! in %AYESHA_RESTART_DELAY% seconds...
set /a WAIT=%AYESHA_RESTART_DELAY%+1
ping -n !WAIT! 127.0.0.1 >nul
goto loop

:notsetup
echo Run install.bat first.
if not defined AYESHA_NONINTERACTIVE pause
exit /b 1
