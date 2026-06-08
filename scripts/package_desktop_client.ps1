# Packages the Jarvis desktop companion (local_client) into releases/jarvis-desktop-windows.zip
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
$releases = Join-Path $root "releases"
$staging = Join-Path $env:TEMP "jarvis-desktop-pack-$(Get-Random)"
$zipPath = Join-Path $releases "jarvis-desktop-windows.zip"

New-Item -ItemType Directory -Force -Path $releases | Out-Null
if (Test-Path $staging) { Remove-Item $staging -Recurse -Force }
New-Item -ItemType Directory -Path $staging | Out-Null

Copy-Item (Join-Path $root "local_client") (Join-Path $staging "local_client") -Recurse
Copy-Item (Join-Path $root "shared") (Join-Path $staging "shared") -Recurse
Copy-Item (Join-Path $root "requirements.txt") $staging
Copy-Item (Join-Path $root "config") (Join-Path $staging "config") -Recurse -ErrorAction SilentlyContinue

$bat = @"
@echo off
title Jarvis Desktop Client
cd /d "%~dp0"
echo Installing dependencies (first run may take a minute)...
python -m pip install -q -r requirements.txt
set PYTHONPATH=%CD%
echo Starting Jarvis daemon — keep this window open.
python -m local_client.daemon
pause
"@
Set-Content -Path (Join-Path $staging "Start-Jarvis-Desktop.bat") -Value $bat -Encoding ASCII

$readme = @"
Jarvis Desktop Client
=====================
1. Install Python 3.10+ from https://www.python.org/downloads/
2. Extract this ZIP anywhere (e.g. Desktop\JarvisDesktop)
3. Double-click Start-Jarvis-Desktop.bat
4. Ensure the backend is running: http://localhost:8000
5. Pair your device via the web dashboard if needed (pair_device.py on full repo)
"@
Set-Content -Path (Join-Path $staging "README.txt") -Value $readme -Encoding UTF8

if (Test-Path $zipPath) { Remove-Item $zipPath -Force }
Compress-Archive -Path (Join-Path $staging "*") -DestinationPath $zipPath -Force
Remove-Item $staging -Recurse -Force

# Mirror for Next.js static fallback
$publicDl = Join-Path $root "frontend\public\downloads"
New-Item -ItemType Directory -Force -Path $publicDl | Out-Null
Copy-Item $zipPath (Join-Path $publicDl "jarvis-desktop-windows.zip") -Force

Write-Host "Created: $zipPath"
Write-Host "Size: $((Get-Item $zipPath).Length) bytes"
