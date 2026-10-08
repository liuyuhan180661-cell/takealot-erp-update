# Takealot ERP v3 - bootstrap updater (Windows)
#
# Why this exists: machines installed BEFORE today have no `erp update` command yet
# (chicken-and-egg). This script only does: download the new package -> verify sha256
# -> hand off to the NEW package's own setup (which stops the service, swaps files,
# restarts and self-checks). Afterwards the machine has `erp update` and can self-update.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File update.ps1
#   $env:ERP_UPDATE_CHANNEL="file://C:\chan\"; powershell -File update.ps1     # local channel (self-test)
#
# Red line: if the sha256 does not match, it EXITS without touching anything on disk.
#
# NOTE: pure ASCII on purpose (cmd.exe / PowerShell 5.1 code pages mangle non-ASCII).

[CmdletBinding()]
param(
  [string]$Channel = "",
  [string]$ErpHome = ""
)

$ErrorActionPreference = "Stop"

if (-not $Channel) { $Channel = $env:ERP_UPDATE_CHANNEL }
$candidates = @()
if ($Channel) {
  $candidates = @($Channel)
} else {
  # Multi-channel fallback: raw.githubusercontent is often DNS-blocked in CN (getaddrinfo failed),
  # and both raw and jsDelivr can serve a CDN-cached copy of a just-published update for hours.
  # gh-proxy / ghfast are live reverse proxies: reachable from CN and never stale.
  $candidates = @(
    "https://raw.githubusercontent.com/liuyuhan180661-cell/takealot-erp-update/main/",
    "https://gh-proxy.com/https://raw.githubusercontent.com/liuyuhan180661-cell/takealot-erp-update/main/",
    "https://ghfast.top/https://raw.githubusercontent.com/liuyuhan180661-cell/takealot-erp-update/main/",
    "https://cdn.jsdelivr.net/gh/liuyuhan180661-cell/takealot-erp-update@main/"
  )
}

if (-not $ErpHome) {
  $ErpHome = Join-Path $env:LOCALAPPDATA "TakealotERP"
}

$tmp = Join-Path $env:TEMP ("erp-update-" + [guid]::NewGuid().ToString("N").Substring(0, 8))
New-Item -ItemType Directory -Path $tmp | Out-Null

function Get-Text([string]$url) {
  if ($url.StartsWith("file://")) {
    return [System.IO.File]::ReadAllText($url.Substring(7))
  }
  return (Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 30).Content
}

Write-Host "== Takealot ERP update =="

try {
  # 0) pick the first channel that answers
  $picked = ""
  foreach ($cand in $candidates) {
    $c = $cand
    if (-not $c.EndsWith("/")) { $c = $c + "/" }
    try {
      Get-Text ($c + "update.json") | Out-Null
      $picked = $c
      Write-Host "   channel: $picked"
      break
    } catch {
      Write-Host "   channel unavailable, trying next: $c" -ForegroundColor DarkYellow
    }
  }
  if (-not $picked) { throw "no channel served update.json - aborted, nothing installed" }
  $Channel = $picked

  # 1) manifest
  $manifestText = Get-Text ($Channel + "update.json")
  $manifest = $manifestText | ConvertFrom-Json
  $name = $manifest.payload.name
  $wantSha = $manifest.payload.sha256
  $remote = $manifest.version
  if (-not $name) { throw "update.json has no payload.name" }
  Write-Host "   package: $name ($remote)"

  # 2) download the body.
  #    Manifest and body pick their channel SEPARATELY: on CN networks raw often serves the
  #    small update.json fine while the ~8 MB body stalls at 0 bytes forever (measured on a
  #    Win10 box: raw body = no data, gh-proxy = 1.4 MB/s). One channel for both = the
  #    upgrade hangs until timeout. Try every channel in order; accept the first body that
  #    downloads completely AND matches sha256; fail closed if none does.
  #    Per-channel budget is 120s so a stalled channel hands over quickly instead of
  #    keeping the user waiting ~15 minutes.
  $BodyTimeout = 120
  $curlExe = Join-Path $env:SystemRoot "System32\curl.exe"
  $bodyCandidates = @($Channel)
  foreach ($cand in $candidates) {
    $c = $cand
    if (-not $c.EndsWith("/")) { $c = $c + "/" }
    if ($c -ne $Channel) { $bodyCandidates += $c }
  }
  $zipPath = Join-Path $tmp $name
  $bodyUsed = ""
  $mismatch = ""
  foreach ($cand in $bodyCandidates) {
    if (Test-Path $zipPath) { Remove-Item -Force $zipPath }
    # PS 5.1 trap: with $ErrorActionPreference='Stop', a native exe that writes to stderr
    # (curl does when it fails) is raised as a TERMINATING NativeCommandError that bypasses
    # the catch below - measured on a real box: raw stalled at 3.9/8.5 MB, curl exited 28,
    # and the whole bootstrap died instead of falling through to the next channel.
    # So run native tools with EAP='Continue' and judge by exit code only.
    $eap = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
      if ($cand.StartsWith("file://")) {
        Copy-Item ($cand.Substring(7) + $name) $zipPath -ErrorAction Stop
        $rc = 0
      } elseif (Test-Path $curlExe) {
        & $curlExe -fsSL --max-time $BodyTimeout ($cand + $name) -o $zipPath 2>&1 | Out-Null
        $rc = $LASTEXITCODE
      } else {
        Invoke-WebRequest -Uri ($cand + $name) -OutFile $zipPath -UseBasicParsing -TimeoutSec $BodyTimeout -ErrorAction Stop
        $rc = 0
      }
    } catch {
      $rc = -1
    } finally {
      $ErrorActionPreference = $eap
    }
    if ($rc -ne 0) {
      Write-Host "   body channel failed (exit $rc), trying next: $cand" -ForegroundColor DarkYellow
      continue
    }
    try { $gotSha = (Get-FileHash -Algorithm SHA256 -Path $zipPath -ErrorAction Stop).Hash.ToLower() }
    catch { Write-Host "   no bytes from this channel, trying next: $cand" -ForegroundColor DarkYellow; continue }
    if ($wantSha -and ($gotSha -ne $wantSha.ToLower())) {
      $mismatch = "want $wantSha got $gotSha"
      Write-Host "   sha256 mismatch from this channel, trying next: $cand" -ForegroundColor DarkYellow
      continue
    }
    $bodyUsed = $cand
    break
  }

  # 3) verify (fail closed)
  if (-not $bodyUsed) {
    if ($mismatch) {
      Write-Host "   SHA256 MISMATCH on every channel - aborted, nothing was installed" -ForegroundColor Red
      Write-Host "   $mismatch" -ForegroundColor Red
    } else {
      Write-Host "   no channel delivered the package - aborted, nothing was installed" -ForegroundColor Red
    }
    exit 1
  }
  Write-Host "   body: $bodyUsed"
  Write-Host "   sha256: OK"

  # 4) extract
  $ex = Join-Path $tmp "x"
  Expand-Archive -Path $zipPath -DestinationPath $ex -Force
  $cli = Get-ChildItem -Path $ex -Recurse -Filter "cli.py" |
         Where-Object { $_.FullName -like "*payload*server*" } | Select-Object -First 1
  if (-not $cli) { throw "package layout unexpected: payload/server/cli.py not found" }
  $payload = Split-Path (Split-Path $cli.FullName -Parent) -Parent

  # 5) hand off to the new package's setup (idempotent: stops service, swaps files, restarts, self-checks)
  $runner = Join-Path $ErpHome "venv\Scripts\python.exe"
  if (-not (Test-Path $runner)) {
    $runner = (Get-Command python -ErrorAction SilentlyContinue).Source
  }
  if (-not $runner) { throw "no python found (install Python 3.10+ or point ERP_HOME at an existing install)" }

  Write-Host "== installing into $ErpHome =="
  # same PS 5.1 trap as above: cli.py writes progress to stderr, and a native command's
  # stderr under EAP='Stop' would abort us before we can read the exit code.
  $eap2 = $ErrorActionPreference
  $ErrorActionPreference = "Continue"
  & $runner $cli.FullName setup --source $payload --erp-home $ErpHome --offline
  $rc = $LASTEXITCODE
  $ErrorActionPreference = $eap2

  Write-Host ""
  if ($rc -eq 0) {
    Write-Host "Done. Future updates:" -ForegroundColor Green
    Write-Host "  & `"$ErpHome\venv\Scripts\python.exe`" `"$ErpHome\server\cli.py`" update --check"
  } else {
    Write-Host "Install step failed (exit $rc). Send back the lines above." -ForegroundColor Yellow
  }
  exit $rc
} finally {
  Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue
}
