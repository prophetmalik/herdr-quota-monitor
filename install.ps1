# Installer for Herdr Quota Monitor
$ErrorActionPreference = "Stop"

$homeDir = [System.Environment]::GetFolderPath([System.Environment+SpecialFolder]::UserProfile)
$herdrHome = Join-Path $homeDir ".config\herdr-app"

$modDest = Join-Path $herdrHome "mods\agent-quota-bar"
$wsDest = Join-Path $herdrHome "mods\workspace-status"
$dataDest = Join-Path $herdrHome "data"

Write-Host "Installing Herdr Quota Monitor..." -ForegroundColor Cyan

# 1. Create directories
New-Item -ItemType Directory -Force -Path $modDest | Out-Null
New-Item -ItemType Directory -Force -Path $wsDest | Out-Null
New-Item -ItemType Directory -Force -Path $dataDest | Out-Null

$scriptDir = $PSScriptRoot
$srcDir = if (Test-Path (Join-Path $scriptDir "mods\agent-quota-bar\main.js")) { Join-Path $scriptDir "mods\agent-quota-bar" } else { $scriptDir }

# 2. Copy mod files
Copy-Item -Path (Join-Path $srcDir "main.js") -Destination (Join-Path $modDest "main.js") -Force
Copy-Item -Path (Join-Path $srcDir "mod.json") -Destination (Join-Path $modDest "mod.json") -Force
Copy-Item -Path (Join-Path $srcDir "collector.py") -Destination (Join-Path $modDest "collector.py") -Force

# Also update active workspace-status so it takes effect live immediately
Copy-Item -Path (Join-Path $srcDir "main.js") -Destination (Join-Path $wsDest "main.js") -Force

# 3. Seed initial metrics
Write-Host "Seeding live metrics..." -ForegroundColor Cyan
python (Join-Path $modDest "collector.py")

# 4. Check with herdr-app
$herdrApp = Join-Path $env:LOCALAPPDATA "Programs\herdr-app\herdr-app.exe"
if (Test-Path $herdrApp) {
    Write-Host "Verifying mod with herdr-app check..." -ForegroundColor Cyan
    cmd /c "`"$herdrApp`" check `"$modDest`" 2>&1"
}

Write-Host "`nInstallation successful! The bottom bar in Herdr is now active." -ForegroundColor Green
