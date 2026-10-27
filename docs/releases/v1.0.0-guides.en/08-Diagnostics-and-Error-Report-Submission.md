# Diagnostic Entrances and Error Report Submission

Version: 1.0.0. Supported client: Chinese HD World of Tanks 0.9.22.0.1 #1513.

## 1. Entrances

Extract the complete package and retain the EXE, _internal and companion files. Exit both game and launcher before changing entrances so a test does not remain in an old session.

| File | Purpose |
| --- | --- |
| wot-0.9.22-offline-battles.exe | Normal play with key-event logging |
| START_DIAGNOSTIC_TEST.bat | Detailed gameplay diagnosis, preferred for navigation, combat, modules, audio and models |
| START_SPIKE_PROFILE.bat | Additional performance/spike profiling |
| START_ROOF_CRUSH_TEST.bat | Mountain Pass bridge push/drop fixture |
| START_ROOF_SHOT_DROP_TEST.bat | Mountain Pass shot-triggered falling-Bot fixture |

The push fixture puts the player on the bridge with friendly parked tanks along its edge. Push them off to inspect first impact, landing, sustained pressure and wreck contacts. The shot fixture puts the player below; each successful shot releases one Bot above for repeatable roof impacts. Fixture Bots do not actively fire.

These fixtures do not replace saved normal-room lineups. Exit before returning to normal/diagnostic battles.

## 2. Reproduce and collect

1. Open the current package through START_DIAGNOSTIC_TEST.bat.
2. Confirm save, vehicle profile, Bot profile/lineup, map, difficulty and tier mode.
3. Reproduce and note vehicle, location, time and player interventions.
4. After the match/session, return to the launcher and use Create error report.
5. Keep and submit the complete wot-error-report-date-time-session.zip.

Reports normally live under the current Windows user's LocalAppData/WoTOfflineBattles/reports. Collection uses session start/end offsets rather than mixing all historic python.log output. A session can contain several rounds; identify the affected round.

Only the newest three completed reports are retained by default. Copy important evidence elsewhere promptly and use distinct names. Factory reset clears managed report storage, not manually copied files elsewhere.

## 3. Report contents

Depending on availability, reports contain launcher, server, visible-player, hidden-worker and worker-starter logs, environment summaries, audio analysis and captured dumps.

Read missing-source notices; having a ZIP does not guarantee every source exists. Normal exit, player-requested closure, worker cleanup and native crash are distinct.

Detailed logs have budgets and duplicate suppression, with exhaustion notices. Errors and lifecycle messages remain. Log volume, startup load, network RTT and rendering frame rate are different measurements.

## 4. Context to submit

| Issue | Useful details |
| --- | --- |
| Blocked route/detour | Map, team, class, route, nodes, vehicle, wrecks/obstacles and whether it eventually escaped |
| SPG holds fire/oscillates | Model, range, visibility, slope, parking assignment, ammunition settings and time |
| Empty Bot does not advance | Initial zero or fired empty, other stock/reload, route and location |
| Audio | Transition stage, exact error and which music/effects failed |
| Model assertion/crash | Error window, timing, manual closure and dump presence |
| Performance | Map/roster, opening or late battle, FPS/ping and chosen entrance |
| Friendly kill/blue name | Attacker/victim team and human/Bot identity, damage source and whether the viewed colour is allied or enemy |

Screenshots locate the scene; complete reports trace causes. Distinguish a temporary blockage that escaped from one persisting to the end.

## 5. Crash dumps

The launcher crash setting can use Microsoft ProcDump under its existing consent controls. Full-memory dumps can be very large; an error report does not automatically contain a full dump.

Native diagnosis requires matching program, logs and dump. The last log line or a process exit alone is not a cause. Enabling capture after a finished fault cannot recreate that fault's memory.

## 6. Submission template

Package:
Entrance:
Map/round:
Player vehicle, Bot lineup and profiles:
Affected vehicle/team/location:
Time:
Observed behavior:
Expected behavior:
Later recovery/escape/end result:
Player intervention or manual game closure:
Attachments: complete report ZIP, locating screenshots and available dump.

Source checks: error_reports.py, report_environment.py, sound_report.py, wot_launcher.py and the diagnostic/performance/two ROOF entrance files.
