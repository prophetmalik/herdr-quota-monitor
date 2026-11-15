# Uninstaller for Herdr Quota Monitor
$ErrorActionPreference = "Stop"

$homeDir = [System.Environment]::GetFolderPath([System.Environment+SpecialFolder]::UserProfile)
$herdrHome = Join-Path $homeDir ".config\herdr-app"

$modDest = Join-Path $herdrHome "mods\agent-quota-bar"
$wsDest = Join-Path $herdrHome "mods\workspace-status"
$dataDest = Join-Path $herdrHome "data"

Write-Host "Uninstalling Herdr Quota Monitor..." -ForegroundColor Yellow

# 1. Remove custom mod folder
if (Test-Path $modDest) {
    Remove-Item -Recurse -Force $modDest
    Write-Host "Removed: $modDest" -ForegroundColor Gray
}

# 2. Clean metric data files
$quotaFile = Join-Path $dataDest "agent_quota.json"
$cacheFile = Join-Path $dataDest ".hub_cache.json"
if (Test-Path $quotaFile) { Remove-Item -Force $quotaFile }
if (Test-Path $cacheFile) { Remove-Item -Force $cacheFile }

# 3. Restore original workspace-status
# Removing the folder allows Herdr to restore its shipped default version on restart.
if (Test-Path $wsDest) {
    Remove-Item -Recurse -Force $wsDest
    Write-Host "Reset workspace-status to Herdr original defaults." -ForegroundColor Gray
}

Write-Host "`nHerdr Quota Monitor has been successfully uninstalled!" -ForegroundColor Green
Write-Host "Restart Herdr to reload the default status bar." -ForegroundColor Cyan
