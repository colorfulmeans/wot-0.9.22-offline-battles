@echo off
setlocal
set "WOT_OFFLINE_ROOF_CRUSH_TEST=1"
cd /d "%~dp0"
echo Temporary bridge-drop test: Victory Gate, enemy Type 59s below the bridge.
echo All Bots hold position and do not fire. Normal physics remains active.
echo Exit this launcher and use the normal EXE to leave test mode.
start "" "%~dp0wot-0.9.22-offline-battles.exe"
endlocal
