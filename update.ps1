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
if (-not $Channel) { $Channel = "https://raw.githubusercontent.com/liuyuhan180661-cell/takealot-erp-update/main/" }
if (-not $Channel.EndsWith("/")) { $Channel = $Channel + "/" }

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
Write-Host "   channel: $Channel"

try {
  # 1) manifest
  $manifestText = Get-Text ($Channel + "update.json")
  $manifest = $manifestText | ConvertFrom-Json
  $name = $manifest.payload.name
  $wantSha = $manifest.payload.sha256
  $remote = $manifest.version
  if (-not $name) { throw "update.json has no payload.name" }
  Write-Host "   package: $name ($remote)"

  # 2) download
  $zipPath = Join-Path $tmp $name
  if ($Channel.StartsWith("file://")) {
    Copy-Item ($Channel.Substring(7) + $name) $zipPath
  } else {
    Invoke-WebRequest -Uri ($Channel + $name) -OutFile $zipPath -UseBasicParsing -TimeoutSec 900
  }

  # 3) verify (fail closed)
  $gotSha = (Get-FileHash -Algorithm SHA256 -Path $zipPath).Hash.ToLower()
  if ($wantSha -and ($gotSha -ne $wantSha.ToLower())) {
    Write-Host "   SHA256 MISMATCH - aborted, nothing was installed" -ForegroundColor Red
    exit 1
  }
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
  & $runner $cli.FullName setup --source $payload --erp-home $ErpHome --offline
  $rc = $LASTEXITCODE

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
