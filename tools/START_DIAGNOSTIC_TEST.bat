@echo off
setlocal
cd /d "%~dp0"
start "" "%~dp0wot-0.9.22-offline-battles.exe" --diagnostics
endlocal
