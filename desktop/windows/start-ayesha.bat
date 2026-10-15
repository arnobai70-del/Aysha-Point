@echo off
setlocal EnableExtensions
title AYESHA FX scanner (advisory only, never places orders)
REM Daily start. Reads your equity from %USERPROFILE%\AyeshaFX\equity.txt (set by install.bat).
REM Restarts the scanner automatically if it stops because of a crash or a network error.
cd /d "%~dp0\.."
set PY=
where py >nul 2>nul && set PY=py -3
if not defined PY set PY=python
if not exist "%USERPROFILE%\AyeshaFX\equity.txt" (
  echo Run install.bat first.
  pause
  exit /b 1
)
set /p EQ=<"%USERPROFILE%\AyeshaFX\equity.txt"
if not defined AYESHA_OANDA_TOKEN (
  echo AYESHA_OANDA_TOKEN is not set. Run install.bat again.
  pause
  exit /b 1
)
:loop
echo %date% %time%  starting scanner, equity %EQ% USD. Close this window to stop.
%PY% -m ayesha.cli scan --feed oanda --equity %EQ% --account-type Standard --news-ff --push
echo Scanner exited. Restarting in 60 seconds (close the window to stop)...
timeout /t 60 /nobreak >nul
goto loop
