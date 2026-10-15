@echo off
REM AYESHA FX: start the advisory scanner without MT5 (OANDA data feed). Never places orders.
REM Edit EQUITY to your Exness equity in USD. AYESHA_OANDA_TOKEN must be set once with:
REM   setx AYESHA_OANDA_TOKEN "your-oanda-practice-token"
REM Task Scheduler: run this file "At log on" (or daily before London open) to scan automatically.
set EQUITY=25
cd /d "%~dp0\.."
if not defined AYESHA_OANDA_TOKEN (
  echo AYESHA_OANDA_TOKEN is not set. See docs\08-pc-scanner-no-mt5.md
  pause
  exit /b 1
)
python -m ayesha.cli scan --feed oanda --equity %EQUITY% --account-type Standard --news-ff --push
pause
