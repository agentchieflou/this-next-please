#Requires -Version 7.0
<#
.SYNOPSIS
    PowerShell 7 smoke test: every command a user types, from the shell they type it in.

.DESCRIPTION
    PowerShell 7 is the floor (epic #63). The `#Requires -Version 7.0` above is not decoration:
    CI runs this file once under Windows PowerShell 5.1 and asserts it is refused, which is the
    only 5.1 step in the workflow and exists to prove the refusal rather than to support the shell.

    PSScriptAnalyzer runs over this file with PSUseCompatibleSyntax targeting 7.x.
#>
Set-StrictMode -Version 3.0
$ErrorActionPreference = 'Continue'

$here = Split-Path -Parent $PSCommandPath
$script:Fails = 0

function Note { param([string]$Text) Write-Host "`n=== $Text" }
function Ok { param([string]$Text) Write-Host "  ok: $Text" }
function Fail { param([string]$Text) Write-Host "  FAIL: $Text"; $script:Fails++ }

Note 'ad-update --check exits 0'
ad-update --check | Out-Null
if ($LASTEXITCODE -eq 0) { Ok 'ad-update --check' } else { Fail "ad-update --check exited $LASTEXITCODE" }

Note 'ad-doctor: exit code, TOON stdout, a hint on every fail row'
$doctorOut = ad-doctor --quiet 2>$null | Out-String
$doctorRc = $LASTEXITCODE
$doctorOut | python (Join-Path $here 'check_doctor.py') --exit-code $doctorRc --shell pwsh
if ($LASTEXITCODE -eq 0) { Ok 'doctor contract' } else { Fail 'doctor contract' }

Note 'the module form works'
python -m agentdata --help | Out-Null
if ($LASTEXITCODE -ne 0) { Fail 'python -m agentdata --help' }
python -m agentdata update --check | Out-Null
if ($LASTEXITCODE -ne 0) { Fail 'python -m agentdata update --check' }
ad-help 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) { Fail 'ad-help' }

Note 'every ad-* console script answers --version'
# read from the installed distribution, never a hard-coded list
$cmds = python -c @"
import importlib.metadata as md
print(' '.join(sorted(ep.name for ep in md.distribution('agentdata').entry_points
                      if ep.group == 'console_scripts' and ep.name.startswith('ad-'))))
"@
foreach ($cmd in ($cmds -split '\s+' | Where-Object { $_ })) {
    & $cmd --version 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) { Fail "$cmd --version" }
}
Ok "checked: $cmds"

Note 'the PowerShell completion script registers without error'
$completion = ad-setup --print-completion powershell | Out-String
pwsh -NoProfile -Command $completion
if ($LASTEXITCODE -eq 0) { Ok 'completion registers' } else { Fail 'completion script failed to register' }

Note 'piped stdout carries no ANSI and equals AGENTDATA_COLOR=never'
$piped = ad-doctor --quiet 2>$null | Out-String
$env:AGENTDATA_COLOR = 'never'
$forced = ad-doctor --quiet 2>$null | Out-String
Remove-Item Env:AGENTDATA_COLOR
if ($piped -match "$([char]27)\[") { Fail 'ANSI escapes in piped stdout' } else { Ok 'no ANSI when piped' }
if ($piped -eq $forced) { Ok 'piped == AGENTDATA_COLOR=never' } else { Fail 'piped differs from AGENTDATA_COLOR=never' }

Note 'pwsh 7 writes UTF-8 without a BOM, through > and through Out-File'
# The 5.1 hazards (UTF-16 from >, a BOM from Set-Content -Encoding utf8) are gone under 7.
# CI proves it here so docs/setup.md can stop telling people to work around them.
ad-doctor --quiet > out-redirect.toon 2>$null
ad-doctor --quiet 2>$null | Out-File out-outfile.toon
foreach ($f in @('out-redirect.toon', 'out-outfile.toon')) {
    $bytes = [System.IO.File]::ReadAllBytes($f)
    if ($bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF) {
        Fail "$f has a UTF-8 BOM"
    }
    elseif ($bytes.Length -ge 2 -and (($bytes[0] -eq 0xFF -and $bytes[1] -eq 0xFE) -or ($bytes[0] -eq 0xFE -and $bytes[1] -eq 0xFF))) {
        Fail "$f is UTF-16"
    }
    else { Ok "$f is UTF-8 without a BOM" }
    python -m agentdata.toon --validate $f
    if ($LASTEXITCODE -ne 0) { Fail "$f is not TOON" }
}
Remove-Item -Force out-redirect.toon, out-outfile.toon -ErrorAction SilentlyContinue

Write-Host ''
if ($script:Fails -ne 0) {
    Write-Host "smoke.ps1: $($script:Fails) check(s) failed"
    exit 1
}
Write-Host 'smoke.ps1: all checks passed'
