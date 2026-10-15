# Windows CI: run the owner-facing .bat scripts end to end, including failures and recovery.
# Uses a throwaway AYESHA_HOME and a fake token; cleans the token from the registry at the end.
$ErrorActionPreference = "Stop"
$env:AYESHA_NONINTERACTIVE = "1"
$env:AYESHA_HOME = Join-Path $env:RUNNER_TEMP "ayesha-home-test"
$env:AYESHA_RESTART_DELAY = "1"
Remove-Item Env:AYESHA_OANDA_TOKEN -ErrorAction SilentlyContinue
if (Test-Path $env:AYESHA_HOME) { Remove-Item -Recurse -Force $env:AYESHA_HOME }
$win = (Resolve-Path (Join-Path $PSScriptRoot "..\desktop\windows")).Path
$tok = "TESTTOKEN-not-real-0123456789-abcdefghijklmnop"
$script:failed = 0

function Run([string]$bat, [string]$argLine, [string]$stdin) {
  $in = Join-Path $env:RUNNER_TEMP "stdin.txt"
  [IO.File]::WriteAllText($in, $stdin)
  $out = cmd /d /c "`"$win\$bat`" $argLine < `"$in`" 2>&1"
  return @{ code = $LASTEXITCODE; out = ($out -join "`n") }
}

function Expect([string]$name, $r, [int]$code, [string[]]$texts) {
  Write-Host "----- $name (exit $($r.code)) -----"
  Write-Host $r.out
  $ok = ($r.code -eq $code)
  foreach ($t in $texts) { if (-not $r.out.Contains($t)) { $ok = $false; Write-Host "MISSING: $t" } }
  if ($r.out.Contains($tok)) { $ok = $false; Write-Host "TOKEN LEAKED INTO OUTPUT" }
  if ($ok) { Write-Host "PASS: $name" } else { Write-Host "FAIL: $name (wanted exit $code)"; $script:failed++ }
}

Expect "start before install" (Run "start-ayesha.bat" "" "") 1 @("Run install.bat first")
Expect "local backtest before install" (Run "backtest-local.bat" "" "") 1 @("Run install.bat first")

# token, equity, 4 Exness contract values, Startup? N
$answers = "$tok`r`n25`r`n100000`r`n0.01`r`n0.01`r`n200`r`nN`r`n"
Expect "first install" (Run "install.bat" "--no-publish" $answers) 0 @("Token saved", "Saved equity 25 USD", "Pairing code:", "Setup finished")
$reg = (Get-ItemProperty HKCU:\Environment -ErrorAction SilentlyContinue).AYESHA_OANDA_TOKEN
if ($reg -ne $tok) { Write-Host "FAIL: token not in HKCU\Environment"; $script:failed++ } else { Write-Host "PASS: token stored in the user environment" }
if (-not (Test-Path (Join-Path $env:AYESHA_HOME "python-path.txt"))) { Write-Host "FAIL: python-path.txt"; $script:failed++ }

Expect "re-run install keeps values" (Run "install.bat" "--no-publish" "`r`n`r`n`r`nN`r`n") 0 @("Kept the current token", "Saved equity 25 USD")

Expect "rejected token stops the restart loop" (Run "start-ayesha.bat" "3" "") 3 @("TOKEN REJECTED", "OANDA REJECTED THE TOKEN")

$env:HTTPS_PROXY = "http://127.0.0.1:9"
Expect "network down: restarts, then gives up when capped" (Run "start-ayesha.bat" "2" "") 4 @("will retry", "Restart 1", "Restart 2", "Gave up after 2 restarts")
Remove-Item Env:HTTPS_PROXY

$eq = Join-Path $env:AYESHA_HOME "equity.txt"
Set-Content $eq "abc"
Expect "corrupt equity file is a config error" (Run "start-ayesha.bat" "2" "") 2 @("CONFIG PROBLEM")
Set-Content $eq "25"

Expect "local backtest rejects a pair outside the allowlist" (Run "backtest-local.bat" "--pairs XAUUSD" "") 2 @("INVALID INPUT")
Expect "local backtest rejects bad days" (Run "backtest-local.bat" "--days 5" "") 2 @("INVALID INPUT")

$pp = Join-Path $env:AYESHA_HOME "python-path.txt"
$saved = Get-Content $pp
Set-Content $pp "C:\nowhere\python.exe"
Expect "moved Python is reported" (Run "start-ayesha.bat" "" "") 1 @("Run install.bat again")
Set-Content $pp $saved

& $saved -m ayesha.cli set-token --remove | Out-Host
$reg = (Get-ItemProperty HKCU:\Environment -ErrorAction SilentlyContinue).AYESHA_OANDA_TOKEN
if ($reg) { Write-Host "FAIL: token still in registry"; $script:failed++ } else { Write-Host "PASS: token removed" }
Expect "after token removal the scanner stops with a config error" (Run "start-ayesha.bat" "2" "") 2 @("CONFIG PROBLEM")

if ($script:failed -gt 0) { Write-Host "$script:failed scenario(s) failed"; exit 1 }
Write-Host "All Windows script scenarios passed."
