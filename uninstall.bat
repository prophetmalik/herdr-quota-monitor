@echo off
echo ===================================================
echo   Uninstalling Herdr Quota Monitor Mod
echo ===================================================

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0uninstall.ps1"

pause
