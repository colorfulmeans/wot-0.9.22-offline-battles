@echo off
setlocal
set "WOT_OFFLINE_SPIKE_PROFILE=1"
set "WOT_OFFLINE_COMBAT_PROFILE="
cd /d "%~dp0"
start "" "%~dp0wot-0.9.22-offline-battles.exe"
endlocal
