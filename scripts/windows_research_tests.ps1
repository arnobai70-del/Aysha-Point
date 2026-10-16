# Windows CI: the research launchers (start-research.bat, backup-research.bat) end to end, with a throwaway
# AYESHA_HOME. No token is used. The live scripts are tested separately by windows_script_tests.ps1.
$ErrorActionPreference = "Stop"
$env:AYESHA_NONINTERACTIVE = "1"
$env:AYESHA_HOME = Join-Path $env:RUNNER_TEMP "ayesha-research-test"
Remove-Item Env:AYESHA_OANDA_TOKEN -ErrorAction SilentlyContinue
if (Test-Path $env:AYESHA_HOME) { Remove-Item -Recurse -Force $env:AYESHA_HOME }
$win = (Resolve-Path (Join-Path $PSScriptRoot "..\desktop\windows")).Path
$script:failed = 0

function Run([string]$bat, [string]$argLine) {
  $out = cmd /d /c "`"$win\$bat`" $argLine < NUL 2>&1"
  return @{ code = $LASTEXITCODE; out = ($out -join "`n") }
}

function Expect([string]$name, $r, [int]$code, [string[]]$texts) {
  Write-Host "----- $name (exit $($r.code)) -----"
  Write-Host $r.out
  $ok = ($r.code -eq $code)
  foreach ($t in $texts) { if (-not $r.out.Contains($t)) { $ok = $false; Write-Host "MISSING: $t" } }
  if ($ok) { Write-Host "PASS: $name" } else { Write-Host "FAIL: $name (wanted exit $code)"; $script:failed++ }
}

Expect "research dashboard before install" (Run "start-research.bat" "--check") 1 @("Run install.bat first")
Expect "research backup before install" (Run "backup-research.bat" "") 1 @("Run install.bat first")

New-Item -ItemType Directory -Force -Path $env:AYESHA_HOME | Out-Null
$py = (Get-Command python).Source
Set-Content (Join-Path $env:AYESHA_HOME "python-path.txt") $py

Expect "research check with research off" (Run "start-research.bat" "--check") 0 @("OFF (legacy_only)", "All research checks passed", "Dashboard security self-test passed", "Research checks passed")
Expect "research backup with no data" (Run "backup-research.bat" "") 0 @("No research data yet")

& $py -m ayesha.cli research enable | Out-Host
& $py -m ayesha.cli research selftest ok | Out-Host
Expect "research backup" (Run "backup-research.bat" "") 0 @("integrity ok")
Expect "research check with research on" (Run "start-research.bat" "--check") 0 @("ON (research-only)", "audit trail", "Research checks passed")
& $py -m ayesha.cli research disable | Out-Host
if (-not (Test-Path (Join-Path $env:AYESHA_HOME "research\research.db"))) { Write-Host "FAIL: research data was not kept"; $script:failed++ } else { Write-Host "PASS: research data kept after disable" }
if (Test-Path (Join-Path $env:AYESHA_HOME "ayesha.db")) { Write-Host "FAIL: research created the live registry"; $script:failed++ } else { Write-Host "PASS: the live registry was not created by research" }

$pp = Join-Path $env:AYESHA_HOME "python-path.txt"
Set-Content $pp "C:\nowhere\python.exe"
Expect "moved Python is reported" (Run "start-research.bat" "--check") 1 @("Run install.bat again")
Set-Content $pp $py

if ($script:failed -gt 0) { Write-Host "$script:failed research scenario(s) failed"; exit 1 }
Write-Host "All Windows research script scenarios passed."
exit 0
