@echo off
echo ===================================================
echo   Installing Herdr Quota Monitor Mod
echo ===================================================

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1"

pause
