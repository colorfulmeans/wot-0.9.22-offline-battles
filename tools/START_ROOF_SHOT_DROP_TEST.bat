@echo off
setlocal
set "WOT_OFFLINE_ROOF_CRUSH_TEST=1"
set "WOT_OFFLINE_ROOF_SHOT_DROP=1"
cd /d "%~dp0"
echo Shot-triggered bridge-drop test: player below Victory Gate bridge.
echo Fifteen enemy Type 59s wait above. Each successful shot releases one Bot.
echo Stay at the spawn mark for the fixed landing lane. Bots never fire.
echo Exit BOTH game and launcher before changing test entrances.
start "" "%~dp0wot-0.9.22-offline-battles.exe"
endlocal
