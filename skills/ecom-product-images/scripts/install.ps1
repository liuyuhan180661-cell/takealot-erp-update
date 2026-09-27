# ecom-product-images dependency installer for Windows (PowerShell 5.1+)
# Contains install ADDRESSES/commands only - no binaries, no credentials.
#
#   powershell -ExecutionPolicy Bypass -File install.ps1
#   powershell -ExecutionPolicy Bypass -File install.ps1 -WithIsnet
#
# Idempotent: re-running only fills what is missing. Prints next steps at the end.
param([switch]$WithIsnet)

$ErrorActionPreference = "Stop"
$Venv   = if ($env:IMGTOOLS_VENV)   { $env:IMGTOOLS_VENV }   else { Join-Path $HOME ".hermes\venvs\imgtools" }
$Models = if ($env:IMGTOOLS_MODELS) { $env:IMGTOOLS_MODELS } else { Join-Path $HOME ".hermes\venvs\models" }
$Index  = if ($env:PIP_INDEX_URL)   { $env:PIP_INDEX_URL }   else { "https://mirrors.aliyun.com/pypi/simple/" }
# model download fallbacks (mainland China)
$Mirrors = @("", "https://gh-proxy.com/", "https://ghproxy.net/")

function Say($m)  { Write-Host "`n== $m" -ForegroundColor Cyan }
function Ok($m)   { Write-Host "   [ok] $m" -ForegroundColor Green }
function Warn($m) { Write-Host "   [!] $m" -ForegroundColor Yellow }
function Die($m)  { Write-Host "   [x] $m" -ForegroundColor Red; exit 1 }

Say "1/5 venv: $Venv"
$Py = Join-Path $Venv "Scripts\python.exe"
if (-not (Test-Path $Py)) {
  if (Get-Command uv -ErrorAction SilentlyContinue) { uv venv $Venv } else { python -m venv $Venv }
  if (-not (Test-Path $Py)) { Die "venv creation failed (need python3.9+ on PATH)" }
}
& $Py -V

function PipInstall {
  if (Get-Command uv -ErrorAction SilentlyContinue) { uv pip install --python $Py @args }
  else { & $Py -m pip install --index-url $Index @args }
}

Say "2/5 base packages (Pillow layout + onnxruntime inference)"
PipInstall pillow numpy onnxruntime
if ($LASTEXITCODE -ne 0) { Die "base package install failed" }

Say "3/5 OCR packages (local translation lane)"
PipInstall opencv-python-headless pyclipper shapely PyYAML six tqdm
if ($LASTEXITCODE -ne 0) { Die "OCR install failed" }
PipInstall --no-deps rapidocr-onnxruntime
if ($LASTEXITCODE -ne 0) { Die "rapidocr install failed" }

Say "4/5 matting models (one-time download, fully offline afterwards)"
New-Item -ItemType Directory -Force -Path $Models | Out-Null
function FetchModel($name) {
  $dest = Join-Path $Models "$name.onnx"
  if ((Test-Path $dest) -and ((Get-Item $dest).Length -gt 1000000)) { Ok "$name.onnx already present"; return }
  foreach ($m in $Mirrors) {
    $url = "$mhttps://github.com/danielgatis/rembg/releases/download/v0.0.0/$name.onnx"
    Write-Host "   downloading $name.onnx from $(if ($m) { $m } else { 'github direct' }) ..."
    try {
      Invoke-WebRequest -Uri $url -OutFile $dest -TimeoutSec 900
      Ok "$name.onnx ok"
      return
    } catch { Warn "channel failed, trying next" }
  }
  Warn "$name.onnx download failed - download manually into $dest"
}
FetchModel "u2net"
if ($WithIsnet) { FetchModel "isnet-general-use" }

Say "5/5 self check"
& $Py -c "import importlib.metadata as md; import cv2, onnxruntime, rapidocr_onnxruntime; print('   [ok] cv2', cv2.__version__, '| numpy', md.version('numpy'), '| ort', onnxruntime.__version__, '| rapidocr ok')"
if ($LASTEXITCODE -ne 0) { Die "import check failed - paste the output above for help" }

Say "done"
Write-Host @"
Next steps (no credentials needed):
  1) white bg : python <skill>\scripts\imgctl.py white --image img.jpg --engine local
  2) full set : python <skill>\scripts\imgctl.py set --images img.jpg --platform takealot --gallery 5 --detail 5 --composite
  3) translate: python <skill>\scripts\imgctl.py translate --image img.jpg --to en --mode local
  4) doctor   : python <skill>\scripts\imgctl.py doctor
Cloud lanes (Aliyun AccessKey) are optional - see references/providers.md, no reinstall needed.
"@
