@echo off
setlocal EnableExtensions
title AYESHA FX - create the Android release signing key (once)
REM Creates %USERPROFILE%\AyeshaFX\signing\ayesha-release.p12 and a text file with the four GitHub
REM secret values. Run ONCE. Keep the .p12 file and its password offline (USB stick); losing them
REM means the next app update needs an uninstall. Never commit or share them.
cd /d "%~dp0\.."
if not defined AYESHA_HOME set "AYESHA_HOME=%USERPROFILE%\AyeshaFX"
if not exist "%AYESHA_HOME%\python-path.txt" (
  echo Run install.bat first.
  if not defined AYESHA_NONINTERACTIVE pause
  exit /b 1
)
set /p PYEXE=<"%AYESHA_HOME%\python-path.txt"
"%PYEXE%" -m pip install --disable-pip-version-check -q -e ".[signing]"
"%PYEXE%" -m ayesha.cli make-signing-key
set "RC=%ERRORLEVEL%"
if "%RC%"=="0" if not defined AYESHA_NONINTERACTIVE start "" "%AYESHA_HOME%\signing"
if not defined AYESHA_NONINTERACTIVE pause
exit /b %RC%
