# Authored route tasks and editor connections

## Maintenance and replay preflight follow-up (2026-10-27)

Scope: launcher-only maintenance and replay entry; no physics, combat, route,
worker frequency or client playback laws change. Four confirmed actions occupy
an equal two-by-two grid: Repair mod installation / Reset all offline client
settings; Clear all offline saves / Delete all data and restore factory defaults.
All four confirmations identify the game folder and bundled build, default to
No, and explain affected data. Running game/worker/room or report collection
blocks maintenance. Other frozen launcher/server processes also block it so
older packages cannot save shared settings back after reset. Factory completion closes the launcher without writing
its old settings; failures cannot use the success path.

The replay report `8fcd63a2cd30` fails before launching a client: the launcher
still capped logical bytes at 768 MiB while all recorders/readers already allow
8 GiB. The existing last-battle recording separately passes full read-only
validation: 27,907 records, 1,127,919,049 logical bytes, 118,498,974 file bytes,
631.934 seconds. The report does not identify the selected file, so that file
is corroborating evidence rather than an asserted path from the report.
Preflight now matches 8 GiB, retaining streaming, row limits, identity, time,
footer/count, gzip integrity and unchanged-file checks. Capacity regression
now streams a real recording above the former limit through the launcher too;
restoring the old limit must reject that same valid stream.

Clear-saves removes both game-folder and external saves/legacy state, rotated
copies and pending grant inboxes, rebuilds default metadata with legacy import
disabled and preserves schemes/preferences. Factory additionally removes the
project application directory, external legacy root, game config/data root,
offline recordings, process logs and known interrupted recovery directories.
Owned vehicle overrides are restored via their existing manifest contract;
unknown engine overlays and redirected paths are rejected before deletion.
Original client preferences, other mods/resources and manually copied/downloaded
files remain outside the explicit scope. Temporary staging is on each target's
volume, rebuild failures restore prior files, and cleanup failures are errors.
A successful reset leaves no automatic old-data backup in the managed roots.

Local validation: seven launcher/save/preferences/replay/overlay files execute
721 tests (568 unique test IDs; replay wiring reuses WindowTest), with nine
Windows symlink skips. The local embedded Python lacks Tkinter, so messagebox
imports are stubbed for fake-widget unit tests; real packaged Tk geometry is a
separate artifact smoke gate. Five replay-capacity tests also pass, including a
real compressed stream above 768 MiB through all readers and preflight. The
user's existing 1.05-GiB logical recording passes the fixed source preflight.
No destructive action is run against the user's real data as acceptance.
Windows build/artifact status is recorded after independent package inspection.

## Lobby music and worker preparation follow-up (2026-10-27)

Report `b9aafa2749ce` runs build 545 on Fjord and supplies a real terminal
boundary: player projectile `1:p:2:10` launches at 299877 ms and is cancelled
with `battle_finished` at 300000 ms. The other nine player projectiles and all
189 BOT projectiles have terminal receipts. The round ends by Team 2 capture;
there is no model/Python failure, motion rebase or multipart residue.

The music failure is narrowed to map reload. In both 545 Ghost Town samples,
each visible/worker process rebinds the remembered `MUSIC_EVENT_LOBBY` after
`game.onGeometryMapped` -> `SoundGroups.preloadSoundGroups` -> music `init`;
error 15 follows 0.25-0.66 seconds later, before GUI loading music takes over.
Exact #1513 bytecode shows `MusicEvent.stop` preserves its event ID, while
`stopMusic` calls `MusicEvent.destroy` and clears the ID and native reference.
The battle-loading boundary now uses stock `stopMusic` only when the active
music slot still remembers lobby music. Loading/combat/result music, ambient
events, audio banks and native sound identity are not replaced. No Vivox or
global-device initialization repair is claimed.

Initial build 547 native acceptance exposes a binding error: compatibility and
battle runtimes are different adapters, so attaching the module to the former
leaves the latter's boundary inactive. Prague sample `04cb007d61f5` still restores
lobby music and reports error 15. The final boundary resolves the process-global
`MusicControllerWWISE` module directly, matching the native owner rather than
injecting a field into the wrong adapter. Its integration regression now uses
that actual module lookup with a battle runtime that has no such field. The
corrected boundary passes four affected files / 1,033 tests; full BOT runtime
and worker-law validation remain unchanged. Build 547 is diagnostic evidence,
not final acceptance; the corrected package requires five fresh native matches.

Diagnostic-entry lifecycle receipts now include controller/slot state before
and after music controller init/destroy/stopMusic and SoundGroups unload/preload.
These rare transition receipts bypass the ordinary distinct-call logging cap;
normal entrance installs no sound wrappers. Native bank auto-load is still
unobserved. Final 548 acceptance below verifies the stale-slot repair in ten
process roles without claiming a global audio-device/bank repair.

Fjord worker callbacks fall to about 7.5 Hz for two 30-second windows, then
recover as the round progresses. A captured 30-second interval spends 26.25
seconds in BOT updates, including 25.48 seconds in physical slices. Rotation,
ground/support and per-actor preparation dominate; projectile update is 0.08
seconds and navigation service 0.04 seconds. These are inclusive scopes, not
additive costs. The 2.07-second completed-wait P95 is specifically the shot-lane
identity queue, not all BOT work or network RTT. Detailed native frontiers cover
seven selected frames per capture and must not be compared to full-window
totals as if they covered the same interval. Diagnostic overhead is not isolated.

Safe preparation changes share only roster membership across one physical
slice, retaining mutable state references so every sequential collision query
reads current poses. Actual native/fallback collision work is unchanged.
Ordinary entrance skips construction of unused tactical diagnostic snapshots;
diagnostic entrance retains those records. Physics, combat, probe precision,
planning/publication frequency and navigation data are unchanged. No general
worker speedup or lower native-query cost is claimed before measurement.

Validation: final engine-free reference coverage passes 16 files / 1,948 tests,
including the complete BOT runtime (550) and battle runtime (1,016). Initial
reference invocation omitted diagnostic-entry enablement and failed twelve
diagnostic-presence assertions; the final rerun uses the intended diagnostic
entrance and passes. Sound/report suites pass 61 tests (five Windows symlink
cases skipped). The source-derived native drive validator is updated to receive
the same slice roster; its initial omitted local failed CI rather than runtime.
Full native state/query/effect pipeline parity passes final source CI
`40456326811`, together with Windows server/editor and navigation-resolution.
The general gate retains Great Wall opposed-gate cleanup and Fjord 24-FPS
departure failures (428/430 files pass); BOT regressions retain the same Fjord
failure (147/148 files pass). The whole workflow is not green. Exact #1513
inspection passes; all 215 client modules compile with CPython 2.7.18.

Final runtime commit `9966eb70435227ef62ddfe0009be8144e4de31e4`, build 548 run
`40456319473`, identity `colorfulmeans-40456319473-1`. All three packaging jobs
pass. Independent inspection of the downloaded artifact verifies 38 frozen
launcher modules, 222 server sources, 215 client bytecode modules, x64 launcher,
native source identity, unchanged navigation bytes, outer/nested archive CRCs
and packaged editor smoke. All 1,226 delivered files match the inspected package.
Download: `WoT-0.10.2-test-548-sound-worker.zip`.

Native acceptance is five diagnostic-entry random matches with Default BOT,
Automatic lineup, random map/level/difficulty/classes/team and player vehicles
Object 260, T-34-3, KV-220-2, Sexton I and MS-1, in that order. Each match must
finish naturally with no assistant driving/firing. Reports are independently
copied and byte/CRC checked in Desktop `WoT_548_随机五车诊断_20261027`.
All five complete and all five reports are audited. Initial build 547's Prague
match is excluded from this acceptance.

| Player | Random map | Session suffix | Natural result | Accepted BOT shots / terminals | Worker callback Hz (three captured windows) |
| --- | --- | --- | --- | --- | --- |
| Object 260 | `08_ruinberg` | `b438a76f7961` | Team 2 capture | 244 / 244 | 7.83, 7.14, 19.45 |
| T-34-3 | `59_asia_great_wall` | `2a8677c21767` | Team 2 capture | 195 / 195 | 8.28, 9.59, 14.99 |
| KV-220-2 | `22_slough` | `a8cec82b59ec` | Team 2 capture | 230 / 230 | 9.04, 9.27, 21.78 |
| Sexton I | `01_karelia` | `31703b58960e` | Team 2 capture | 219 / 219 | 8.76, 9.94, 26.23 |
| MS-1 | `38_mannerheim_line` | `e1e9bf4989d5` | Team 1 elimination | 229 / 229 | 10.07, 10.43, 42.54 |

Both visible client and hidden worker clear the remembered lobby slot before
each map preload; all ten roles report zero sound errors. No model-refresh
assertion/refusal, Python failure, BOT state rebase or pending multipart residue
appears. All 1,117 accepted BOT projectiles settle. MS-1 sample additionally has
one aligned worker fire request (`1:b:26:8`) rejected by canonical authority
after BOT 26 dies: `BOT SHOT SUPPRESSED`, `canonical_vehicle_dead`, health 0.
It never creates a projectile and must not be counted as a missing terminal.
The report analysis now distinguishes aligned requests, suppressed requests and
accepted projectiles. The T-34-3 report's bounded server tail omits startup;
its launcher log retains all 29 initial ammo plans, matching the live capture.

Short-turn screening is evidence, not a stuck-loop verdict. Karelia SU-26 / BOT
30 has one overlapping deployment-to-hold window with ten sign changes in
10.55 seconds and 1.20 m displacement. It then holds stably; the control history
contains a sustained one-direction turn toward the authored emplacement heading.
Mannerheim SU-18 / BOT 13 has five overlapping deployment windows below 2 m,
including nine sign changes in 10.85 seconds / 0.38 m. It later reaches its
emplacement, holds and enters sortie travel. These samples do not establish a
persistent combat-control loop or permanent blockage; retain current behavior
and the existing driver/navigation/traffic/rotation evidence for follow-up.
No unsupported combat or physics change is made from a turn-counter heuristic.

Worker low-frequency windows persist under detailed diagnostics, especially
with the full roster alive. Different maps, tiers, survivors and combat load
prevent an uncontrolled before/after speedup claim. The measured result does
not show that the performance issue is solved or isolate diagnostic overhead.
The shipped optimization removes confirmed preparation allocations only; it
does not reduce probe counts, precision, update cadence or safety checks.
Other retained startup warnings concern unsupported offline Vivox, RSS and
Scaleform/settings containers; none is the former lobby WWISE error 15.

Evidence: workspace `work/acceptance548.json`, `work/acceptance548-audit.json`,
`work/acceptance548-music-audit.json`, each extracted case's
`turn-windows-review.json`, `work/followup-548-package-verification.json` and
`work/followup-548-delivery-proof.json`. No raw user logs are uploaded to the PR.
The final evidence-only documentation commit is newer than the tested runtime
commit above and does not change the delivered package.

## Build 545 adapter acceptance correction (2026-10-27)

### Corrected package and native acceptance

Runtime commit `cda4599f024f7b94090c2c3f4fbec7a2a1df2814`, package run
`40444684044`, identity `colorfulmeans-40444684044-1`. All three packaging jobs
pass. Independent downloaded-package inspection verifies 38 frozen launcher
modules, 221 server sources, 214 client bytecode modules, x64 launcher, native
source identity, unchanged navigation bytes, archive CRCs and packaged editor
smoke. All 1,225 delivered files match the inspected archive. Download:
`WoT-0.10.2-test-545-artillery-travel.zip`.

Final source CI `40444688664` passes Windows server/editor, navigation-resolution
and native-geometry jobs. General tests pass 426/428 files, retaining the same
Great Wall opposed-gate and Fjord 24-FPS departure failures. BOT regressions pass
147/148, retaining that same Fjord failure; the full workflow is not green.
The existing positive-class selection suite also passes after the user raises
the tier-one/missing-class boundary. Preflight refuses unavailable selected
classes and impossible all-SPG fill before loading; no matching rule is changed.

The first corrected-package diagnostic Ghost Town sample `90e4a105364a` runs
to the fifteen-minute timeout with lineup 30 and Default, without assistant
driving or firing. All 71 BOT launches have settled receipts. There is no
multipart residue, model-refresh assertion/refusal, Python traceback or BOT
motion rebase. Worker callback windows are 34.70, 36.05 and 24.00 Hz; this is
sample evidence, not a general performance improvement. No 10-13-second
turn-reversal window below two metres displacement appears.

BOT 14 (Object 261) records 21 actual defense samples: nine moving samples
retain the new hull owner, twelve stationary-hold samples do not. No current
control row has combat hull aim during these defense samples or the 1,460
travel-owner samples. Older rows in an eight-row control history can belong to
the preceding combat state and must not be attributed to its new task marker.
Defense preserves the interrupted `spg_attack_1` task. In the final two minutes,
Object 261, G.W. E and T92 each move more than 480 horizontal metres between
sample endpoints; Object 261 returns to defense, G.W. E follows its authored
return cursor and T92 reaches base capture. All retain ammunition. The draw
alone is not a proved permanent deadlock or a reason to alter ordinary combat.
The user observes that this sample resembles normal late-match play.

The known lobby music error remains once per role; actual report resource
inspection confirms its event/action reference and forty valid embedded-media
index entries. Native engine auto-load remains unobserved, so no audio cure is
claimed. The first report is copied to Desktop with exact-byte and ZIP-CRC
verification.

The second corrected-package diagnostic sample `c57568cc952d` finishes normally
by Team 2 elimination. All 47 BOT launches settle, with no unmatched or unknown
terminal identity, multipart residue, model-refresh assertion/refusal, Python
traceback or BOT motion rebase. Worker callback windows are 33.95, 38.17 and
32.81 Hz. The 117 reviewed 10-13-second turn-reversal windows contain none below
two metres displacement. All 1,099 travel-owner samples have current-row combat
hull aim disabled. This sample does not exercise actual base defense;
the first sample supplies that acceptance evidence. Known music error 15 still
appears once per role. Neither match proves an audio cure or a general worker
speedup. Neither finishes with an in-flight projectile, so individual
`battle_finished` cancellation receipts remain covered by tests, not by these
two native endings.

Both final-package sessions use lineup 30 + Default on `95_lost_city`, with no
assistant driving or firing. Both reports are preserved separately under
`C:/Users/USER/Desktop/WoT_545_火炮回防两场诊断_20261027`; exact-byte copy and ZIP
CRC checks pass. The game is closed after the second result and the launcher
is left available. No further runtime change follows this acceptance.

Build 544 native acceptance exposed an omitted producer-consumer boundary:
`BotAdapter.decide_with_order` did not retain `spg_mode` or the explicit
`throttle_override` hold boundary. Consequently moving base-defense commands
lost the new SPG hull-ownership guard at the final live-target/reproof layer,
although their older no-combat-hull-aim guard still prevented chassis aiming in
the first observed sample. Preserve both fields only on SPG-owned strategic
orders. A real adapter-to-live-target regression now checks moving defense and
stationary hold separately, rather than injecting an already converted command.
Ordinary combat, navigation and firing validation remain unchanged.

Final corrected-source focused validation passes five files / 744 tests,
including real adapter handoff, AI adapter, complete BOT runtime, authored route
tasks and SPG recovery. All 214 client modules compile with CPython 2.7.18.

Build 544 run `40441041047` passes all three package jobs; independent checks
verify 38 frozen modules, 221 server sources, 214 client bytecode modules, native
identity, unchanged navgraphs, archive CRCs, editor smoke and 1,225 delivered
files. Source CI `40441033665` retains the previous two general-test failures
(Great Wall gate and Fjord 24-FPS departure), with the same Fjord BOT failure;
Windows server/editor, navigation resolution and native geometry pass.

First diagnostic-entry Ghost Town sample `1ed7dc62442e` finishes by Team 1
elimination win: 56 launches / 56 settled BOT shots, no unmatched identity,
multipart residue, model-refresh assertion/refusal or Python traceback. Worker
callback windows are 30.67, 35.20 and 33.27 Hz. BOT 20 has 19 actual defense
samples and progresses along the return route, but its false hull-owner marker
exposes the adapter omission above; do not count this as full guard acceptance.
No 10-13-second turn-reversal window with less than two metres displacement
appears. Known music error remains once per role, with valid event/action and
embedded-media structure; native auto-load remains unobserved. The second 544
sample `8fbdbb21163f` finishes by Team 2 elimination, with 69/69 BOT shots
settled, no model/Python errors or multipart residue, and worker windows of
33.73, 38.07 and 18.17 Hz. It has no actual base-defense sample or turn-reversal
window below two metres. Both 544 reports are preserved separately. Their logs
are not reassigned to the corrected package: fresh 545 acceptance is recorded
above.

## Build 544 follow-up scope (2026-10-27)

Ghost Town build 543 proves stale parking/target-facing ownership during SPG
sortie return. Authored travel now sets chassis facing to its navigation goal
before rear-laying arbitration; live target pose, pending ballistic reproof and
late combat hull aim cannot reclaim that chassis. Moving SPG base defense uses
the same ownership: gun/turret tracking continues within the actual weapon
limits while the chassis navigates or recovers. Ordinary combat and stationary
base-defense holding keep their existing behavior. Fire still needs the original
ballistic, obstruction, friendly-safety and launch proof. No movement or native
query budget is reduced, and no worker speedup is claimed.

Diagnostic control samples now identify the travel hull owner and defense resume
identity. Battle finish emits individual diagnostic-only `battle_finished`
projectile terminal receipts for both player and BOT shots, without changing
settlement or cleanup. Logging failure cannot block terminal cleanup.

Sound report generation additionally inspects exact event-to-action references
and embedded-media index bounds. Native bank auto-load remains explicitly
unobserved. Original bank event presence and playback callbacks do not establish
why native error 15 occurs; there is no speculative resource/audio fix.

Engine-free reference validation passes 43 files / 1,607 tests using the explicit
Linux seam. Final diagnostic and projectile tests were rerun after their last
changes; the final projectile file passes 129 tests. Sound/report suites pass
61 tests (five unavailable Windows symlink cases skipped). All 214 client files
compile with CPython 2.7.18; exact Chinese HD #1513 inspection passes. Independent
package inspection and native acceptance were pending at this historical
runtime source commit; completed 544 observations and corrected 545 acceptance
are recorded above. Native observations separate exercised return-to-base
behavior from any untriggered defense branch.

## Build 543 follow-up scope (2026-10-27)

Manual Ghost Town report `69064df66e0b` proves a close-range SPG aim-point
failure: two stocked Object 261s reject both arc families at a fixed one-metre
height, requiring 5.26/5.87 degrees depression against their actual three-degree
limit. Only after this mechanical refusal, the controller now tries the existing
nine descriptor-local hull/turret samples. Gun limits, native muzzle, ballistic
solving, world obstruction, friendly safety and final launch proof remain intact.
The selected model-part identity follows live target pose through planning and
latency reproof; model replacement invalidates it. Reachable legacy aim points
and ordinary combat retain their existing behavior. This fixes a demonstrated
low-point blind spot, not every reason a nearby gun can legitimately refuse fire.

The same report proves allied-frag accounting and native arena update for enemy
BatChat 155 destroying enemy Object 261. Exact #1513 UI policy keeps other-team
vehicles enemy-colored; no blue-name rule is changed.

Sound diagnosis confirms `hangar_v2_music_lobby` exists in the original event
bank. Prior hooks could observe creation but not read-only native playback.
Diagnostic entry now wraps the actual mutable Python MusicEvent owner and the
missing global-sync entry, retaining native sound identity and recording
before/after event, mute and playing state. It explicitly reports engine-owned
bank auto-load as unobserved. No speculative audio/resource fix is included.
SPG control history additionally separates planner, pre/post-traffic and final
turn, with blocker/rotation/probe receipts. No movement policy or native query
budget is changed. Worker saturation and yaw oscillation remain investigations;
this build claims no measured worker speedup.

Final-source engine-free reference validation: 41 files / 1,457 tests pass using
the explicit Linux seam. Focused five-file regression passes; both sound/error
report suites pass. All 214 client sources compile with CPython 2.7.18 and exact
Chinese HD #1513 inspection passes. Package inspection and native acceptance
were pending at the runtime source commit. They are now completed below.

### Build 543 package and native acceptance

Runtime commit `7c81633c34b4b7ac92541cfdd1f8bdc56eb7374b`, build run
`40433507169`, identity `colorfulmeans-40433507169-1`. All three packaging jobs
pass. Independent inspection verifies 38 frozen launcher modules, 221 bundled
server sources, 214 client bytecode modules, x64 launcher, native source identity,
unchanged navgraph bytes, outer/nested CRCs, diagnostic launch entries and packaged
editor smoke. All 1,225 delivered files match the inspected archive. Download:
`WoT-0.10.2-test-543-artillery-aim.zip`.

Source CI `40433501522` passes Windows server/editor, navigation-resolution and
native-geometry jobs. General tests pass 426/428 files, retaining the Great Wall
opposed-gate and Fjord 24-FPS departure failures. Bot regressions pass 147/148
files, retaining that same Fjord failure. No new failing file appears against the
previous handoff; full source CI remains red. Final committed focused validation
passes 5 files / 1,082 tests. Reference validation uses the explicit engine-free
Linux seam; it does not claim native x86 execution.

Both requested matches ran on the exact #1513 client through the diagnostic
entry with lineup 30 and Default. The user changed the second sample to active
player driving for depression testing; the assistant did not drive or fire.
Each report is separately preserved on Desktop, compared byte-for-byte and
ZIP-CRC checked; both contain complete sound-analysis output and reconstruct
without pending multipart records. Default and lineup 30 remain selected.

| Map / session suffix | Result | BOT launch / settled-shot receipts | Worker callback Hz, three windows |
| --- | --- | --- | --- |
| Prokhorovka / a3d605ff86b5 | Team 2 elimination win | 71 / 71 | 35.71, 23.68, 33.52 |
| Ghost Town / f9cc6a4acf9c | Team 2 elimination win | 56 / 55, plus one final in-flight shot | 30.64, 19.78, 34.40 |

The remaining Ghost Town identity is `1:b:19:4`, emitted at 10:13:35.882 and
presented at 10:13:36.103; the match ends at 10:13:36. The existing server result
branch assigns `battle_finished` tombstones and clears in-flight shots without
printing individual terminal receipts. This is an end-of-match evidence limit,
not proof of a lost mid-match shell. Do not report 56 impacts or an independently
observed per-shot cancellation. All recorded launches retain aligned gun angles.

No model-refresh assertion/refusal or Python traceback occurs in either report.
The user observed Object 261 firing successfully at close range in Ghost Town.
The new model-sample fallback is exercised in native logs: 90 sampled candidate
rows in Prokhorovka remain outside actual gun limits; Ghost Town has 16 sampled
rows, including two legal model-part candidates after the low-point refusal.
These records prove mechanical fallback and continued refusal of illegal points;
they do not prove every close-range target has a safe ballistic path.

The known `hangar_v2_music_lobby` error remains once per process role in each
session. Both visible and worker reports include MusicEvent owner coverage and
before/after playback state; playback changes from false to true before the
later native error. Missing event creation or an uncalled play method therefore
does not explain these samples. Engine-owned bank loading/media failure remains
unproved. Preserve `sound-analysis.json` and the original logs; no audio fix is
claimed and broad extra hook installation is not the next diagnostic step.

The Prokhorovka record contains no 10-13-second window with at least eight turn
reversals and less than two metres displacement. Ghost Town contains four
overlapping windows for BOT 30 (Conqueror GC, around 10:07:43) and BOT 24 (T92,
around 10:11:50), both in `sortie_return`. Navigation is safe and sampled rotation
receipts show no hull/peer blocker; control histories show driver/gunner-facing
changes as well as reverse/forward movement. Both advance more than 39 metres
and enter their attack route within roughly 27 seconds of the cited sample.
This is temporary low progress, not a proved permanent deadlock or a proved
pitch-only cause. Retain the new steering-stage receipts for a scoped follow-up.

User-reported loss-of-spot turns are a distinct observation. Existing logs show
unassigned/sortie vehicles changing between engagement, waiting and route travel
as targets disappear/reappear. A waiting vehicle may retain a server anchor face
without actually reserving or moving to that parking place. Do not describe all
such turns as a parking refill or as a regression. Inspect each actual task,
move goal, face goal, target and throttle before changing ordinary combat.

Worker saturation is not fixed or conclusively absent: these six windows are
about 20-36 Hz and do not reproduce the prior severe slowdown, but scene and BOT
survival differ. No physics/query/cadence budget is reduced in this build.
Evidence helpers: `work/acceptance543.json`, `work/acceptance543-audit.json`,
`work/acceptance543/case1`, `case2`, package/delivery verification JSON and retained
CI failure logs. Desktop reports are under `WoT_543_火炮两场诊断_20261027`.

## Build 542 follow-up scope (2026-10-27)

Live enemy-pose refresh used to overwrite `face_position` even on an explicit
empty-ammunition travel order. It now updates gun aim while preserving the
existing movement/facing, recovery and capture owners. Stocked and reloading
combat retain the original live-target transformations. This fixes a proved
ownership violation; native acceptance must still determine whether it explains
the reported circling. Ordinary combat logic is otherwise unchanged.

Tactical order witnesses are only read by diagnostic logs. Ordinary entry now
avoids their repeated field copies; diagnostic entry preserves the witnesses.
This is bounded allocation cleanup, not a claimed fix for the measured 6-Hz
all-empty worker workload. Navigation, physics, collision, target selection,
gun solving and weapon safety budgets are unchanged.

Diagnostic entry adds compact SPG control histories at a 0.25-second sample
cadence, publishing eight scalar samples every two seconds per SPG. The records
include actual versus planned controls, hull/turret angles, stock/reload,
target/aim versus navigation goal, task/recovery/pause, path/probe and physical
gates, desired gun angles/aim intents, plus pending fire-proof ownership. Turn
sign reversals are counted on every control update, including updates between
timed samples. These records have an independent
bounded cadence so bulk geometry quota exhaustion cannot hide the symptom.
Ordinary entry constructs no history. Team-killer receipts link server allied
frag commitment, client receipt/missing mapping, binding return and native arena
state after update. They change no blue-name rule or display policy. Existing
model-refresh failure receipts and the complete sound diagnostics remain active;
no new model or sound fix is inferred from the prior five matches.

Ghost Town exchanges the two SPG attack corridors in the shared first-run/reset
Default, retaining each team's own-base to enemy-base direction. This reverses
the other team's point/node sequence rather than swapping team ownership and
leaving invalid endpoints. All other map/route data remains unchanged. Local
test profiles 1/2 must copy the new Default map data while retaining their zero/
one-round behavior rules before native acceptance.

Final committed-source validation passes 39 reference files / 1,428 tests,
4 focused files / 86 tests and 3 Windows editor files / 23 tests. All 214
client sources compile under CPython 2.7.18; exact #1513 inspection passes.
Reference tests use the existing engine-free Linux seam, not a loaded Windows
x86 extension. Initial interpreter attempts without native extensions or Tk
are retained but are not product acceptance evidence. Build 541 preflight
exposed a standalone binding import regression; the canonical absolute import
fix is included in replacement runtime commit
`ec73c4d8dbb03c0a5a2a8f95ec7ad178a1da420f`.

Build 542 run `40393572785` passes all three packaging jobs, identity
`colorfulmeans-40393572785-1`. Independent inspection verifies 38 frozen
launcher modules, 221 server source files, 214 client bytecode modules, native
source identity, unchanged navigation graph bytes, archive CRCs and packaged
editor smoke. All 1,225 delivered files match the inspected archive. Source CI
`40393580992` passes Windows server/editor, navigation-resolution and native
geometry jobs. General tests pass 426/428 files; only the retained Great Wall
opposed-gate and Fjord 24-FPS departure assertions fail. Bot tests pass 147/148
files, with the same Fjord failure. Full source CI is not green.

Exact #1513 client disassembly establishes that
`VehicleArenaInfoVO.isTeamKiller(playerTeam)` returns false for the other team;
`ArenaDataProvider` supplies the player's team. Thus an enemy GC killing an
enemy 261 can remain enemy-colored by native UI policy. That observation alone
is not a missing accounting defect. New server/client/native receipts still
need to establish actual accounting independently; no blue-name rule changed.
Primary evidence: `work/blue-542-client-contract.txt`.

Windows acceptance uses lineup 30: Default/Prokhorovka,
Default/Ghost Town, two one-round Ghost Town matches, two one-round
Prokhorovka matches and zero-round Ghost Town. An additional Prokhorovka
sample is allowed for hull-yaw observation. In restricted Ghost Town matches,
the assistant may drive the player to enemy spawn as explicitly requested;
these are active interaction tests rather than pure AFK. If killed before the
post-last-shot behavior can be observed, repeat that sample. Preserve each
diagnostic report separately on Desktop and restore Default afterwards.

### Build 542 native acceptance and next-work handoff

All seven sessions completed on the inspected package. Each generated report
is separately copied to Desktop, compared byte-for-byte and ZIP-CRC checked;
multipart diagnostic reconstruction has no pending fragments.

| Case / configuration / map | Session suffix | Result | Bot launches / terminal receipts |
| --- | --- | --- | --- |
| 1 / Default / Prokhorovka | 07a68aa6a520 | 15-minute draw | 68 / 68 |
| 2 / Default / Ghost Town | 2a56aaed5f3d | Team 2 elimination | 65 / 65 |
| 3 / one round / Ghost Town | 10b008d1b762 | Team 1 capture | 23 / 23 |
| 4 / one round / Ghost Town | 4590ba45297e | Team 1 capture | 20 / 20 |
| 5 / one round / Prokhorovka | 4a7c51ada7d5 | Team 2 capture | 21 / 21 |
| 6 / one round / Prokhorovka | 20ee50880fdc | Team 1 capture | 19 / 19 |
| 7 / zero rounds / Ghost Town | bb2676feecbf | Team 2 capture | 0 / 0 |

All 29 BOT inventories in each one-round session start at exactly one, and no
BOT launches sequence 2. Case 3 compact controls cover all 23 shooters after
depletion: 1,841 travel and 84 capture records, with no empty `engage` records.
1,312 empty records retain distinct gun aim and navigation-facing positions.
Positive reload timers coexist with actual zero stock in 381 samples; the
trigger is stock exhaustion, not merely reloading.

No model-refresh assertion/refusal or Python traceback appears in these seven
reports. The known sound error remains once in each process role per session;
it is identified as `hangar_v2_music_lobby` / event 2967843034 / error 15 and is
not declared fixed. No team-killer receipt occurs, so these sessions do not
independently exercise an allied-kill accounting transition.

Case 7 proves all 29 BOT inventories start with every shell type at zero,
with no launch or terminal projectile. Both the bulk and compact diagnostic
streams cover all 29 depleted BOTs. The compact stream contains 2,886 travel and
45 capture records, no empty `engage` records, and 1,206 distinct gun-aim versus
navigation-facing positions. All four one-round samples conserve every launch
through its terminal receipt, never launch sequence 2 and retain zero stock;
there is no observed stock rebase. Death before firing explains why not every
initial BOT necessarily produces a shot.

Worker 30-second callback samples are 38.12/26.51/34.31 Hz (case 1),
30.76/36.59/27.49 (2), 30.92/35.72/24.03 (3), 31.78/36.02/18.97 (4),
35.37/14.41/10.67 (5), 35.54/14.82/9.82 (6), and 6.77/7.89/5.94 (7).
The all-empty workload remains slow. These are observational samples, not a
paired performance benchmark or a claimed overall speedup. Case 5's last
window spends 24.70 of 29.90 seconds inside `bot.slice` (inclusive); its completed
wait sample has p50 565 ms and p95 913 ms. This warrants further stage profiling,
not speculative removal of collision, physics or combat checks.

Case 1 still exposes a stocked-SPG late-game stall: five surviving SPGs remain
in `engage` until timeout after firing stops. Low alignment/collision-probe
records and old aim-intent timestamps are evidence for continued audit, not a
proved cause. Existing ordinary combat remains unchanged. Turn-direction
reversals also occur while vehicles make substantial progress; no sampled
window in case 1 with at least eight reversals over ten seconds has under two
metres of endpoint displacement. This does not rule out moving hull oscillation.
The same screen across cases 2/3/4/5/6/7 finds 16/5/0/1/0/2 overlapping windows
under two metres; these are windows, not distinct incidents. Case 5 BOT 29 at
worker time 749.693 has 11 reversals in 11.04 seconds, 0.435 m displacement,
empty stock and `base_capture`; actual control samples have `hull_aiming=false`
and retain the navigation-facing owner. Case 7 BOT 17 has eight reversals in
11.182 seconds, 0.88 m displacement during `sortie_return`; BOT 4 has eight
in 10.637 seconds, 1.875 m during attack recovery `skip`. Thus repeated small
steering is not declared solved or dismissed as ordinary progress. The reports
contain the needed control/traffic/path context for the next audit; no new
ordinary-combat behavior was changed during these acceptance matches.

Active driving to enemy spawn is not completed: injected game driving/menu
keys produced no observed response, although mouse UI and OS close work. A
manual-driving request is pending. Case 2 includes unsuccessful driving-input
attempts; cases 3-7 are AFK. These samples must not be represented as successful
close-range enemy-spawn interaction tests. The remaining acceptance gap is the
requested active enemy-spawn observation after the last shot, not the seven
completed match runs. No assistant shot was fired. Default was reapplied via
the editor and verified in `active.json` after case 7. Profiles 1/2 retain their
zero/one-round rules and their complete map data still equals the new Default;
lineup 30 and the selected Object 260 remain available.

Local evidence inventory: `work/acceptance542.json`,
`work/acceptance542-audit.json`, and per-case `summary.json`, `decoded.jsonl`,
`sound-analysis.json`, `turn-windows-review.json` under `work/acceptance542/`.
Desktop reports are in `C:/Users/USER/Desktop/WoT_542_火炮七场诊断_20261027`.
The test package is `WoT-0.10.2-test-542-artillery-control`; runtime remains
`ec73c4d8dbb03c0a5a2a8f95ec7ad178a1da420f`. The subsequent handoff commit
only documents acceptance and does not change shipped runtime bytes.

## Build 540 Windows acceptance and next-work handoff (2026-10-27)

Runtime commit: `c01b72c4bbc7b183393db93df6702effb76268e9`, identity
`colorfulmeans-40374935928-1`. Build run `40374935928` passes all three
packaging jobs. Independent package inspection verifies 38 frozen launcher
modules, 220 server sources, 213 client bytecode modules, native source identity,
unchanged navigation bytes, archive CRCs and packaged-editor smoke. All 1,224
delivered files match the inspected archive. The source CI run `40374947240`
still fails Great Wall opposed-gate and Fjord 24-FPS spawn-departure assertions
(425/427 general test files pass); full source CI is not green.

Five diagnostic-entry sessions completed in the requested order with lineup 30.
The assistant only operated launch, room, close and report controls, without
driving or firing. The user manually tested case 3; it must not be described as
an uninterrupted, controlled AFK sample. Each report was separately copied to
Desktop, compared byte-for-byte and checked for ZIP integrity. All multipart
records reconstruct without remaining fragments. Default was reapplied after
the final match; configuration 1/2 and lineup 30 remain available.

| Case / configuration / map | Session suffix | Result | Bot launches / terminal receipts |
| --- | --- | --- | --- |
| 1 / Default / Prokhorovka | `dd5dd5f57d30` | Team 2, team eliminated | 73 / 73 |
| 2 / Default / Ghost Town | `224721bdd8b7` | Team 2, base captured | 2 / 2 |
| 3 / 2, one round / Ghost Town | `3dba908196a1` | Team 1, base captured | 20 / 20 |
| 4 / 2, one round / Prokhorovka | `327adc3a9e10` | Team 2, base captured | 23 / 23 |
| 5 / 1, zero rounds / Ghost Town | `454f215cba09` | Team 1, base captured | 0 / 0 |

Both restricted cases publish 29 initial inventories totaling one each; all
launch identities have sequence 1 and exactly matching server projectile
terminal identities. No sequence 2 occurs. Case 3's server startup has rolled
out of the report's server tail, but its full launcher log retains all 29 ammo
plans. Subsequent confirmed-zero route/capture samples cover 19 Bots in case 3
and 21 in case 4. The zero-round case publishes 29 true-zero inventories and
all 29 have route/capture-mode fire-gate evidence; no Bot launches a projectile.
Reload samples with positive inventory are distinguished from exhausted stock.
All five cases have zero magazine rebase warnings, no Python traceback or
model-refresh assertion/refusal in the retained report logs, and no worker
disconnect before the battle result. This establishes the tested boundaries,
not absence of gameplay bugs.

Performance is still an open issue. Worker callback sample rates, in capture
order, are: case 1 37.32/25.41/35.27 Hz; case 2 32.04/38.66/37.27 Hz;
case 3 30.07/36.47/11.04 Hz; case 4 38.19/14.39/13.89 Hz;
case 5 6.91/5.93/6.11 Hz. These are worker callbacks, not displayed client FPS
or network ping, and are not a controlled before/after benchmark. In case 5,
Bot slices consume 25.99/26.57/26.45 seconds in approximately 30-second captures;
planner/driver, physics translation, ground probes and hull rotation remain
substantial. The empty firing-lane queue cleanup does not solve this motion
workload. Preserve collision/height checks and combat while investigating;
do not infer a safe optimization solely from an expensive stage name.

All five reports contain `sound-analysis.json`. Each records one native
`2967843034 / ErrorCode 15` error per process role, 20 installed initial hooks,
event definitions and recent calls. The new ID mapping identifies the event as
`hangar_v2_music_lobby`; exact HIRC membership confirms an event in
`audioww/hangar_v2.bnk`, without bank-scan failures. This is a useful positive
identification, not proof that a nearby `gun_damaged` call caused it or that the
native playback/loading error is fixed. Native readonly method limitations
still apply; no undocumented native hook should be claimed observed.

Keep these user-observed issues open for the next diagnostic/fix iteration:

- Case 1, Bot 23 Object 261: repeated small alternating hull corrections on a
  slope before firing at the player at 02:27:51.279, from approximately
  (-75.370, 7.473, 249.044). Existing detailed motion receipts end before this
  interval. Progress and a successful shot do not disprove a control loop.
  Capture continuous, bounded yaw request/output, task owner and aim/navigation
  arbitration around the symptom before changing ordinary combat.
- Case 3, GC Bot 25 kills allied Object 261 Bot 23 at 02:54:10 with 44 damage.
  The user reports no visible blue name. The shared server frag handler sets
  `team_killer` and publishes vehicle statistics for allied kills; the retained
  report does not prove this event's end-to-end native display. Trace event
  production, both client consumers and native team-killer/color presentation;
  do not dismiss the observation or declare a new artillery exception.
- Case 3, exhausted artillery circles the player, while some artillery ignore
  the player and Bat.-Chatillon 155/T92 aim. Exhausted inventories and
  `spg_route_travel` are confirmed, with later positions substantially changed;
  retained targets are allowed. These facts alone do not prove movement goals
  are correct or explain the reported circling/aim differences. Correlate
  actual route goal/progress, control owner and aim selection for the specific
  Bots. Do not assume gun traverse caused it: the user explicitly checked that.
- The user requests swapping Ghost Town team-1/team-2 SPG attack paths and
  adopting them as the shared Default in the **next package**. Do not mutate
  build 540 or rewrite these five matches as testing the proposed swap.

Local evidence: `work/acceptance540.json`, `work/acceptance540-audit.json` and
`work/acceptance540/case1` through `case5` in the parent workspace. Desktop
copies are in `C:/Users/USER/Desktop/WoT_540_火炮五场诊断_20261027`.
No main push, merge, tag or public release was performed.

## Build-539 failure corrections and complete audio receipts (2026-10-27)

The Ghost Town worker failure is reproduced by an unassigned artillery Bot
entering and leaving base defense: the old owner restored `{}` as its initial
parking plan. Defense return now restores only a canonical plan for the current
map, vehicle, team and pinned tactics; absence remains absence. Optional plan
identity extraction contains malformed records. Sortie/empty task ownership and
ordinary combat are unchanged. Parking-return tests now use complete real-shape
manual plans rather than a zone-only fake.

The 65 restricted-ammunition rebases per match are reproduced independently:
the service expected a reduced clip before the first full reload completed.
Initial still-loading checkpoints now retain their published descriptor clip
until the first reload completes; ready state uses the actual finite inventory.
Stock conservation, subsequent magazine boundaries and fire gates remain
enforced. Zero/one/partial/full inventories cover this boundary explicitly.

Confirmed-empty sources no longer acquire or service firing-lane jobs, close
fire priorities or stale blocked-fire reprobes. Unknown inventory and stocked
reloads remain eligible. Targets, turret aim, ballistic aiming, movement,
recovery, capture and already launched projectiles keep their existing owners.
This removes demonstrated unused work without reducing motion/shot safety;
no native frame-time improvement is assumed before the new acceptance matches.

Diagnostic-only sound receipts now include parent calls, object identities,
event-name short IDs, bank operations, callback requests, continued repeat
sampling and a bounded recent-call buffer. Returned native objects are not
replaced or retained. Available play/stop/event/callback methods are observed
where the native type allows it; readonly methods are reported as a coverage
limitation. Stream interception records asynchronous errors with recent context;
the report collector separately scans raw native log writes that bypass Python.
Every new event name is indexed independently of the first-call detail budget.
Native exceptions, returns and playback arguments are preserved.

Generated diagnostic reports add `sound-analysis.json`, containing session-only
per-role errors, context, hook coverage, event-ID mappings and exact HIRC bank
membership. Bank inspection runs during report generation, never on the worker
frame loop. It distinguishes actual HIRC IDs from incidental binary byte hits.
Malformed/unavailable audio resources are described without losing primary logs.
An end-to-end report test excludes prior-session sound errors. The real #1513
resource identifies `2967843034` as an event in `hangar_v2.bnk`; `gun_damaged`
maps to a different event in `damaged_modules.bnk`. This establishes resource
ownership, not the asynchronous error's root cause or a sound fix.

Reference regression passes 35 files / 1,335 tests, with final targeted audio
checks after diagnostic coverage additions. Launcher core passes 188 tests
(one existing Windows symlink skip); report/audio tests pass 60 tests. The
213 client scripts compile with CPython 2.7.18 and exact-client inspection
passes. Logs are under `build/followup-540-*`. Final package inspection, source
CI limitations and all five Windows acceptance results are recorded above;
the prior Great Wall/Fjord findings remain explicit.

## Build 539 diagnostic acceptance (2026-10-27)

The tested runtime is `1677b51f11f5c3a138dc6bc9961af8ff4918f3ad`,
identity `colorfulmeans-40356954664-1`. Build run `40356954664` passes
all three packaging jobs. Independent inspection verifies 37 frozen launcher
modules, 220 staged server sources, 213 client bytecode modules, native source
stamps, unchanged navigation bytes, archive integrity, packaged-editor smoke
and all 1,224 delivered files. Final source CI `40356909264` still fails the
opposed Great Wall gate and Fjord 24-FPS spawn-departure assertions; full CI is
not green. These are not the historical Airfield subcase.

Four independent diagnostic-entry sessions used lineup 30. The assistant
issued launcher, room, close and report inputs, without driving or firing.
Each report was separately copied to Desktop, compared byte-for-byte and
passed ZIP CRC inspection. All multipart diagnostic records reconstructed
without pending fragments. Default was restored after the tests.

| Configuration / map | Session suffix | Result |
| --- | --- | --- |
| Default / Prokhorovka | `eb0f82c1053c` | Team 2, team eliminated |
| Default / Ghost Town | `b234742dd5f5` | Failed: worker disconnected |
| 2, one total round / Ghost Town | `678c2add95a9` | Team 1, base captured |
| 1, zero total rounds / Ghost Town | `54e60286f5d5` | Team 1, base captured |

Inventory boundaries have positive native evidence. All 29 initial inventories
in configuration 2 total one. Eight distinct Bots publish sequence 1 and all
eight projectiles have server terminal receipts; no Bot publishes sequence 2.
Four exhausted Bots have subsequent fire-gate samples showing `[0, 0]`,
`fire_seq=1` and `spg_route_travel`. Samples with positive stock while reloading
retain armed behavior. All 29 configuration-1 inventories total zero; fire-gate
samples cover all 29 Bots with zero stock and travel/capture modes, with no
launch or server projectile terminal receipt. Zero stock is independent of
reload and magazine readiness; unknown stock cannot establish this state.
These samples do not establish every route reservation or every first-entry
transition. They do not prove all vehicles reached the enemy circle.

The requested verification resumed after the earlier interruption. Six focused
reference files / 104 tests pass in `build/spg-modes-ammo-539-followup/`:
empty navigation, ammunition transitions, late projectile results, allocation,
artillery modes and artillery recovery. This is engine-free reference evidence,
not a substitute for the failures observed below.

Confirmed/open findings from the new reports:

- Default / Ghost Town fails at 00:55:32 with `KeyError: 'catalog'` in
  `spg_positions.plan_identity`, reached through `_navigation_target_impl`.
  Source inspection finds a defense-resume path that can restore an empty
  dictionary as `_spg_initial`; the identity consumer requires a complete plan.
  This is a Python task-state failure, not a diagnosed native crash. The report
  records no model-refresh refusal or native assertion.
- Both restricted-ammunition sessions record 65 `BOT STATE rebased` messages,
  all `bot clip changed outside reload`, involving the partial/empty magazine
  startup boundary. The ordinary-stock sessions record none. The source tests
  passing does not dismiss this native lifecycle mismatch; its exact transition
  needs reproduction before claiming a correction. It is separate from the
  confirmed all-shells-zero admission rule.
- The zero-stock session remains expensive: three approximately 30-second
  profiling windows contain 206, 215 and 150 worker callbacks (about 6.87,
  7.20 and 5.02 Hz). The other three sessions' corresponding windows are about
  30.37--37.92 Hz. These scenes have different numbers of moving vehicles;
  the comparison does not establish a version regression or a particular
  optimization. Selected slow traces reach about 346 ms, predominantly Bot
  update work. Do not represent selected traces as whole-match averages or
  visible-client ping.
- All four sessions retain the same sound resource error
  `2967843034 / ErrorCode 15`, once in each native role. Ten passive sound hooks
  install per role and record calls/callers, but no receipt directly maps that
  resource ID. Nearby `gun_damaged` creation precedes the asynchronous error;
  temporal proximity alone does not identify the failing sound. No sound fix
  or model-refresh fix is claimed.

The four requested sessions and report audit are complete; build 539 is not a
clean gameplay acceptance. This follow-up records evidence only and does not
silently change gameplay policy or rebuild the already tested runtime.

## Artillery mode ownership and sound receipts (2026-10-26)

The build-537 findings below led to an explicitly approved artillery policy
change. The worker now owns round-scoped deployment, armed endgame sortie and
empty-ammunition sortie identities. The service no longer independently sends
every artillery vehicle to capture when it has no known enemy.

- Deployment reserves at most three distinct parking regions per side, one
  vehicle per region including vehicles en route. Other artillery drives and
  shoots automatically. Dead parking owners admit a replacement. A replacement
  that makes no progress for the existing 20-second deployment interval closes
  only that region's replacement admission until the next battle. Parking
  retries cannot select another owner's region or a closed region.
- When only artillery Bots remain, excluding humans from this test, reserve
  three persistent armed sortie identities. Prefer automatic/free artillery,
  then randomly choose parked artillery. Returning home, combat, recovery and
  temporary automatic base defense retain the reservation. Death or transition
  to empty ammunition admits another eligible Bot. Nonselected artillery waits
  and can shoot; parking replacement admission stops in this phase.
- A selected Bot first returns to its own capture circle and then follows its
  attack road. A firing opportunity pauses movement at the actual pose rather
  than restoring the old parking destination. Defense resumes the interrupted
  sortie, not its old parking plan. Weapon ballistics, range, reload, aiming,
  launch validation and ordinary-vehicle combat retain their existing owners.
- Confirmed empty inventory enters once, retires old task controls and bypasses
  the armed three-sortie admission cap. The first three attack-road claims use
  the authored artillery road; subsequent claims select ordinary effective
  main/reserve roads with the least physical occupancy, randomly breaking ties.
  Claims include vehicles returning home. Disabled roads are excluded and
  equal geometry shares occupancy. Unknown inventory does not trigger empty.
- Missing artillery roads use the same ordinary-road selection after returning
  home. A borrowed road with a defense connector reverses that connector from
  base to its stable junction, then follows the main road forward. Without a
  connector it visits the actual first point before advancing. Automatic travel
  remains the fallback when no usable authored road can be proved. Existing
  C/D/reverse-B/A/home/switch recovery remains unlimited. Selection rejects
  proved disconnections and avoids the failed geometry when alternatives exist.
  Navigation is checked only on acquisition; once a valid preference/occupancy
  tier exists, higher-occupancy candidates cannot win and are not rechecked.

`spg_modes`, `spg_route_travel`, `spg_route_recovery` and the runtime parking
tests cover admission, replacement failure, same-round reservations, human
exclusion, empty transitions, shooting/defense ownership, offset-base entry,
stable-node defense connectors, route tiers, occupancy, retries and new-round
cleanup. Existing artillery firing/launch, ordinary combat, withdrawal,
bootstrap and server tests remain in the regression scope. These engine-free
checks do not establish native gameplay or a reduction in worker frame time.

Initial isolated engine-free reference validation passes 25 files / 1,141 tests
using CPython 3.11.9 and the non-Windows reference path (`sys.platform='linux'`
inside each test subprocess; no fake native motion acceptance). Logs are in
`build/spg-modes-final-reference/`. Launcher core passes 188 tests with the
existing Windows symlink skip. All 213 client sources compile with CPython
2.7.18. Direct Windows source tests cannot load the x86 embedded-game native
module into the x64 audit interpreter; native/package gates remain separate.

The expanded CI follow-up fixes pre-battle initialization when `round_id` is
`None` and removes `sort_keys` from sound receipts to retain the CPython 2.7
C encoder. Unsigned sound resource IDs remain numeric under Python 2.7 `long`.
Old service-wide artillery capture and multi-vehicle/single-region assertions
now validate worker-owned sortie admission and one reservation per region.
Physical spacing, vehicle-size and source-catalog validity checks remain.
Expanded isolated reference validation passes 35 files / 1,328 tests; the final
sound/encoder checks pass 12 tests, including the added unsigned-ID assertion.
An explicit CPython 2.7 probe preserves the numeric unsigned ID and compiles
all 213 client sources. Inventory lifecycle tests confirm that reloading,
changing shell or emptying a magazine with reserves does not mean total stock
is zero. Only a successfully consumed round decrements the finite inventory.

The first pushed CI run (`40352968500`, source `14a3556d`) caught the defects
above before delivery. Its retained traffic findings are the opposed Great
Wall gate and the Fjord 24-FPS spawn-departure case; the earlier Airfield case
must not be used as the identity of this run's departure failure. The source
fixes and adapted contracts require a new CI run. Build 538 stayed queued and
was not delivered. A local assembly may retain the build-537 frozen launcher
only after confirming that all launcher source is unchanged and verifying its
frozen modules against the checkout. Its standalone server, staged server
sources and Python-2 client payload are rebuilt. Retained x86 native assets
must match current C++ source stamps, and all package contents and startup
gates are checked independently. Such an assembly has an explicit local build
identity and is not represented as a successful GitHub build.

The exact Chinese HD #1513 client inspection passes. Python 2.7 bytecode of
`SoundGroups` confirms the wrapped method signatures and its direct
`WWISE.WW_eventGlobal` consumer. Only the diagnostic entrance installs passive
wrappers around already-loaded sound APIs. Receipts record method, scalar event
or bank arguments, caller, role, wall time and returned/raised outcome. The
first 256 distinct calls per process are recorded; repeats are deduplicated.
Native argument identities, return values and exceptions are preserved. No
extra playback, native object retention, sound-bank alteration, worker probe
or callback is introduced. Normal entry installs no wrappers. These receipts
may correlate the unresolved resource-ID/code-15 error with its caller; they
do not decode or repair that native loading error. Build-539 acceptance above
confirms hook installation and caller receipts, while the failing resource's
event identity remains unresolved.

Build-537 native evidence remains historical. Build-539 acceptance above records
the new-package Windows matches and their remaining failures. The final source
CI retains the Fjord 24-FPS departure and opposed Great Wall gate failures;
no assertion or safety budget is relaxed here.

## Empty ammunition and artillery recovery follow-up (2026-10-26)

### Build 537 native acceptance

The delivered runtime source is `cef470eb713d0d81ea7542ce60ac52c0e28ebe1b`;
`8f20b3badeccabc52a6db3918c516924f6027649` adds only validation documentation
and the disabled-vehicle test adaptation. Build run `40329210315` passes all
three package jobs, including packaged server startup. Independent inspection
checks 211 client bytecode modules, 218 staged server sources, 37 frozen launcher
modules, native identity and 1,222 delivered files. Navigation data is unchanged.
The latter commit's CI run `40331567034` retains only the known Airfield 15-FPS
departure and opposed Great Wall assertions; the adapted immobility assertion
now passes. Full CI is not green.

Three diagnostic sessions completed and their separately named report copies
passed SHA-256 equality and ZIP CRC checks. Configuration 1 and 2 both ran
`63_tundra`; lineup 30 with Default ran `05_prohorovka`. The requested AFK
conditions were not exclusive: player actions occurred in the sessions. The
owner explicitly accepted the first match as case 1. Do not describe these as
three uncontaminated AFK trials. The assistant issued launch/room/close/report
inputs, not vehicle driving or firing inputs.

- Zero stock: all 29 initial Bot inventories total zero, no Bot fire-alignment
  launch records, both teams reach capture and team 1 wins by capture. Empty
  artillery also reaches capture; recovery remains active for obstructed units.
- One shell: all 29 initial inventories total one; 26 Bots publish one launch
  each, with no second sequence. Sampled exhausted vehicles have numeric zero
  inventory, `empty_ammo=true`, `travel_before_aim` and route movement. Team 2
  wins by capture. This does not prove every Bot fired or every recovery ended.
- Default/all artillery: all 29 Bot identities in the firing-gate observations
  are artillery. Fourteen Bots fire 22 shots; the battle reaches its 15-minute
  timeout without capture. Keep this as a failed artillery acceptance case.

The third session exposes an ownership defect: received `base_capture`/authored
sortie travel alternates with `artillery_deploy` back toward the old firing
position when shootable contacts appear. At 22:11:30, Bots 2 (GW E), 16 (GW E)
and 17 (Bat.-Chatillon 155 58) receive fire-enabled deployment orders toward
their own parking areas. At 22:12:29 Bot 2 again receives capture and resumes
sortie travel. The local sortie code returns the incoming order when a target
admits an attempt; that incoming order can still own the old deployment goal.
Recorded tactical samples use `server_order`, so this is not evidence of the
legacy local planner's retreat branch being exercised.

The server's artillery-only/no-known-enemy capture branch also admits Bots
outside the local three-artillery authored-sortie selection. For example,
Bot 5 receives `base_capture` without `spg_route_travel`. Server and worker
admission must be reviewed together before changing this behavior. Initial
placement selected eight manual plans and left 21 with automatic fallback;
per-vehicle deployment/fire retries are not a continuing vacant-position
replacement scheduler. No new combat, replacement or retreat rule is approved
by these observations alone.

No model-refresh refusal, Python traceback, assertion or native exception is
recorded in these reports. Exception files contain session headers only. Both
roles log the same sound resource loading error (2967843034 / code 15); it is
not evidence of navigation or ammunition failure. Sampled worker callback
execution peaks are 240.049, 214.724 and 272.839 ms. Bot update dominates; the
third peak includes 169.447 ms in `bot.planner_driver` across 25 calls. These
bounded triggered samples are not whole-match averages or ping measurements,
and do not yet establish a safe optimization. Preserve the existing physics,
combat and query budgets pending a separately approved fix.

An explicit, nonempty, shape-valid inventory of numeric zeros enters a
round-owned empty-ammunition state. Missing inventory, reload, empty magazine
with reserves, invalid data and a depleted selected shell with another shell
available do not enter it. The state retires old player, defense, pressure,
combat, parking and recovery ownership once, then retains its own route and
recovery progress. It overrides ordinary task admission without changing
armed-vehicle combat. Aim and existing launch checks remain active; hull travel
has priority over firing pivots. Already launched shots retain their ledgers.

Ordinary vehicles resume their original effective road, skip all waits and
capture the opposing circle. Hits and contacts do not pause travel. Arrivals
hold the circle and re-enter after a shove. Empty vehicles are excluded from
player-command recipients, defense and pressure donors; physical road occupancy
is retained. Their own mobility/recovery checks are separate from donor
eligibility. State is cleared for a new round and pruned for departed vehicles.

Empty artillery returns home and follows its authored endgame road even in a
mixed team and beyond the normal three-artillery selection limit. Missing
authoring retains automatic enemy-base navigation. Authored attacks now use
C timeout -> D -> reverse B/A -> old first node -> own base -> another road's
first node. Returning and transfer remain recovery; combat pauses the clock
only for armed artillery. Include effective ordinary main/reserve roads,
deduplicate equal geometry, reject failed route/entry navigation checks, prefer
least occupancy and randomly choose equal candidates. Avoid the failed geometry
when any other valid road exists; otherwise retry it without a stop counter.
Reserve a switched road before another artillery chooses. Preserve existing
local avoidance, steering, collision and navigation laws.

The optional behavior `ammo_limit` is an integer 0..1800, inherited when absent.
It caps initial Bot stock at the installed gun capacity without changing that
capacity, player inventory, magazine size or shell-ratio policy. Allocation,
preview, canonical storage and manifest sanitization share it. Zero and one
provide reproducible saved configurations for the requested empty/last-shot
native acceptance, including partially filled native magazines.

The first package startup gate exposed a missing explicit server staging entry
for the new mixin. Include it in the payload and verify a cold staged-server
import with isolated Python paths, in addition to the actual packaged protocol
startup gate. Do not use the rejected package for native acceptance.

Adapt the older disabled-vehicle handoff test to supply actual destroyed
engine/left-track/right-track state instead of mocking pressure-donor
eligibility. Recovery and donor admission are intentionally separate now:
an empty but mobile vehicle must recover, while real motor damage still pauses
its clock. This is a test-only correction; retain all hold/command assertions.

Coverage includes inventory negatives and round lifecycle, once-only handoff,
external-command rejection versus own recovery, timed/permanent waits, retained
aim with navigation hull facing, circle hold/re-entry, no-route fallback, exact
zero/one stock and one-round exhaustion, mixed-team/fourth-SPG admission,
blocked return loops, combat pause, base/spawn offsets, immediate road claims,
reserve admission and disconnected entry rejection through the real graph.
Run the focused source and launcher tests, Python 2.7 compilation, the isolated
reference suite and exact-commit CI. Native acceptance is three separate AFK
matches: configuration 1 (zero), configuration 2 (one round), then lineup 30
(all artillery) with Default. Generate and preserve one report per session on
the Desktop; only after all three finish compare their reports. These tests do
not establish native motion or performance before those matches.

## Approved behavior

The task priority is automatic base defense, existing combat (including its
reload/cover/withdrawal phases), recovery, pressure transfer, player command,
then ordinary route travel. Combat cancels player ownership permanently. It
pauses recovery and pending pressure movement; it does not extend a pressure
transfer's wall-clock expiry. No target, ammunition, ballistic, native collision,
steering or damage law is replaced by these task owners.

Fresh normal deployment starts at the second authored node. Route points remain
coarse navigation goals with the existing arrival disk and local obstacle,
traffic and physical recovery checks. Enemy-circle entry finishes attack travel;
its exact centre or last waypoint is not an arrival prerequisite. Rejoining after
combat or an expired temporary command uses a reachable node on the same lane,
ranked by directed baked graph cost with actual height changes. This static check
is not a new permission to cross a native obstacle.

Lane occupancy is shared across a team's vehicle-class variants of one road.
Prefer empty main roads, then the least loaded main road below three vehicles.
Use reserve roads after main roads fill, then allow authored overflow instead of
abandoning the lane network. Keep class eligibility, fixed-slot intent and the
class-local priority tie breaker. Truly absent or unusable authored routes retain
the existing automatic fallback. Pressure reservations count an in-transit
recipient separately from force which has actually arrived; protect existing
recovery/transfer owners from repeated dispatch.

Artillery never enters the ordinary road allocator or consumes its occupancy.
Parking connections and sortie routes own SPG travel and count their own users.
Missing purpose-specific authoring retains automatic navigation to the task's
destination, including the enemy circle during a sortie, without borrowing an
ordinary class road. An empty ordinary SPG route is not a completed attack lane
and cannot send artillery forward while regular teammates are still active.
This matches the existing pressure-dispatch exclusion of stationary artillery.

Pressure evaluation is every 180 seconds. A donor reverses its old nodes to the
old start, reaches the selected new road's start, then commits that new road.
If the transfer expires before commitment, resume from the last passed old-road
node; after commitment retain the new road, regardless of the original manifest
or old radio lease. Do not teleport between middle nodes when knowledge changes.

Defense reverses the original route, skipping waits. An optional branch attaches
to a stable intermediate-node identity and ends at the own base. Already passing
that junction toward the own start does not require revisiting it: finish the
reverse traversal and then approach the base. Local failure gets the existing
attempt interval, one reverse-point skip and then the explicit direct-base
fallback after a second failure. Physical vetoes still apply. Arrival uses the
actual own base circle. A displaced arrived defender approaches the circle again
without resetting the player's arrival phase.

Automatic defense replaces player orders and ends only after a continuous 30
seconds without an enemy occupant. An occupant with zero capture points still
interrupts safety. Player guard has 90 seconds from issue to arrive; arrival
switches once to continuous-safe 30 seconds, never back to 90. Combat cancels
player guard. Inside the own circle, shootable capturers rank by current capture
points, then existing target score; retain real visibility, range, aiming and
launch checks. An outside attacker cannot retain a target lease over a legal
capturer. Ordinary combat ranking resumes when defense ends.

Player guard creates and checks its own-circle task against canonical
`capture_bases`, including a currently safe base. Threat-only `bases` cannot
define guard arrival or its continuous-safe release phase.

Attack travel has no selected three-Bot capture squad and no peripheral capture
screen. Every ordinary route can finish at the actual enemy circle. All actual
arrivals retain their circle during contact pursuit, reload and worker-local
repositioning; aim, range and final launch checks remain unchanged. Displacement
outside the circle requests re-entry. Separate defense, recovery, player and
pressure task ownership remains intact. The native/server capture law still
limits scoring speed to three contributors; this is not a vehicle admission cap.

Local recovery has no cumulative half-forward-distance reverse allowance.
Repeated proved reverse escapes remain eligible even after tiny forward pushes.
Short escape endpoints, collision/water/boundary checks and the existing macro
recovery cycle still apply; removal of the allowance is not clearance evidence.

Player command admission has one shared 10-second cooldown per issuer. Only an
executable recipient starts it. A cooldown rejection neither queues nor renews
an old order: eligible recipients reply negatively only on the first rejected
attempt during that cooldown. Accepted recipients reply positively; other Bots
remain silent. New valid requests supersede older recipient ownership across
issuers. The broadcast to human teammates remains independent of Bot admission.
A turn-back command owns one frozen previous-node goal and ends on arrival.
Following uses the current issuer pose and ends on death, leave or expiry;
attention, stop and follow expiry rejoin the same original route.

## Authoring and storage

The route toolbar has six equal columns: New route, New SPG, Duplicate, Delete,
Undo, Redo on the first row; Make main, Make reserve, Check map, Fit view, Load
image on the second. The remaining cell holds a Restore menu for Reset route and
Restore default routes. These operations retain their existing scope and prompts;
Default remains read-only. Chinese labels follow the requested order, including
Import map for the existing background-image loader, whose calibration dialog
still distinguishes images from exported route data. Language changes preserve
the current draft and translate both restore commands.

Main routes are solid and reserve routes dashed in their vehicle-class color.
Capacity explanations are in help text. Class/overview scopes cannot delete a
lane. All-classes deletion disables a built-in family; a user-created family and
its mirrors/branches are removed completely. Restore-default-routes restores
all packaged built-in geometry, waits, tiers and defense branches while keeping
user-created routes. Legacy single-class deletion masks become visible reserve
variants; whole built-in deletions stay disabled. Disabled geometry owns no waits
or branch references.

A defense junction cannot be a waiting place, endpoint or parking zone. A defense
junction also cannot be converted into a waiting place. Connection editing has
its own selected geometry and fixed ends; insertion, dragging, deletion, copying,
import and map undo preserve or remove stable references. All-classes edits
reset the selected route family to the common point coordinates and ordering,
including the common defense-junction node; old per-class third/fourth-node
choices do not survive a later common edit. Main/reserve priorities stay local.
Wait places survive only on unchanged coordinates that remain ordinary nodes;
removed/moved nodes cannot retain orphaned waits. Disabled rows remain disabled
and do not acquire waits or defense branches.

Parking deployment, relocation and return to a remembered parking position use
existing automatic navigation. Remove authored parking connection controls,
tree children and red solid connection lines. Legacy parking `travel`/`links`
remain accepted input keys only: canonical reads discard them, owned launcher
files are migrated, and stale deployment/relocation task caches cannot control
automatic movement. New/copy/reset/import do not recreate these connections.
The offline draft builder no longer generates them. Map inventory does not
report these automatic legs as missing authored configurations.

Only independent red dashed artillery attacks remain authored. They have fixed
own/enemy base endpoints, no tiers or ordinary route-capacity use, and no defense
branch. Up to three endgame artillery Bots automatically return to their own
base circle before following the attack from its next point. Spawn anchors are
not substitutes for the base. Combat cannot rejoin past the mandatory return.
Defense during attack reverses the passed attack nodes; at parking it retains
automatic base navigation. Remember the actual interrupted attack or parking
and resume that owner after defense. Missing attacks retain the old automatic
endgame fallback. Existing combat/fire gates and ordinary navigation/recovery
remain unchanged. Authored attack geometry still requires owner review.

All-classes is the black common-editing view. An actual main-route or defense
geometry edit updates only the selected map/team/route family: copy the common
point coordinates, order, node identities and defense branch into every ordinary
class variant. If the common junction is point three, every same-team variant
now uses that same point three, even if it previously had a different point four.
Do not preserve the superseded class geometry or select a nearby old junction.
Total and individual-class views edit only the selected class. A later common
edit replaces those independent edits again. View selection itself never writes.
Tiers, priorities, other families and artillery are excluded from propagation.

When route symmetry is enabled and the map permits it, also reset the opposite
team's corresponding variants to the reversed common road, keeping their fixed
spawn ends and own-base defense endpoint. The shared junction keeps its stable
identity in the reversed order. This follows existing reversed-road semantics;
it does not invent terrain-mirrored roads. Failure on either team rolls back
both drafts/history. Unsupported maps keep symmetry disabled. Add/delete/insert,
dragging, main-junction movement, deletion and undo/redo all use the same scope.
A list refresh/queued selection event preserves active defense editing; map-check
location enters the actual branch. Single-class custom splits retain selection.

Optional schema-1 fields remain `tier`, `family`, `node_ids`, `defense` and route
`purpose=spg_attack`. Endpoint ownership, bounds, stable junctions, waits and
Default read-only restrictions remain checked. Parking legacy keys are discarded
rather than treated as executable authoring data.

## Verification and limitations

- Report 171327 exposes authored `advance` travel paused solely by an aiming
  target. Host recovery and local driver now use one shared route-leg identity:
  acquiring, changing or losing a distant target cannot suspend C/D/B/A travel
  or replace its progress episode. Actual engagement/cover/retreat ownership,
  commanded holds, parking, defense and player commands retain their existing
  behavior. The full fifteen-minute retry test also runs while aim targets
  change; existing engagement-pause/resume tests remain unchanged.
- Diagnostic-entry captures label `completed_wait` as `shot_lane_identity`;
  this is not a global worker/motion queue or screen ping. Bounded
  `slice_residual_*_us` counters partition the existing `bot.slice.self_ms`
  into preparation, actor work, advisory work, contacts/support and tail.
  They are not additive stages or extra CPU work. Checkpoints are enabled
  only by the diagnostic entry and subtract completed nested stage times;
  no physical query, steering law or probe budget changes for timing.

- `test_port_0922_initial_allocation.py` reproduces the parking-artillery
  capacity defect, checks unchanged ordinary draws with/without SPGs across
  40 seeds, and covers the reported mixed TD/heavy roster with a class-specific
  reserve variant. Keep whole-team class-family occupancy, fixed routes,
  symmetric draws, reserve admission and overflow tests enabled.
  A third 40-seed check excludes SPGs even when ordinary class weights permit
  them. Own sortie usage and unconfigured automatic attack are tested separately. The
  unchanged Fjords/Airfield departure simulation must still pass at 15/24 FPS;
  preserve all departure, physical-retry, traffic and premature-arrival bounds.
- Windows connection tests verify every toolbar row/column, translations,
  Restore menu invocation and Default/editable state changes. The frozen-editor
  smoke and downloaded-package verifier require the same toolbar/menu receipt.

- `test_port_0922_route_task_rules.py` covers command admission, guard phases,
  task ownership, frozen turnback, circle handoff, pressure commitment/expiry,
  class-family occupancy, directed rejoin, stable junctions and automatic SPG
  parking, defense and authored sortie sequencing.
- `test_port_0922_capture_protection.py` reproduces the ebb19501b480 circle and
  contact positions, including lost firing lanes, reload, six arrivals with
  three human contributors, displacement, owner changes and network cache
  invalidation. Local adapter tests reject outside reposition goals without
  changing target or shot permissions. `test_port_0922_recovery_return_budget.py`
  now requires continued reverse eligibility and retains blocked-exit and
  diagnostic-entry coverage; the obsolete cumulative-budget tests are removed.
- Repeat these checks with `python tools/run_test_suite.py --jobs 4 --pattern
  test_port_0922_capture_protection.py --pattern test_port_0922_route_task_rules.py
  --pattern test_port_0922_recovery_return_budget.py --pattern
  test_port_0922_terminal_route_handoff.py --pattern
  test_port_0922_base_circle_arrival.py --pattern test_port_0922_server_bot_ai.py`.
- Real Windows Tk tests exercise connection editing, fixed ends, long branches,
  waiting-place exclusion, tier changes, class-specific junction identities,
  save/reopen, copy/undo and toolbar reachability. Frozen editor smoke saves a
  defense branch, route tier, parking connection and SPG sortie through the
  real packaged editor in a temporary profile.
- Existing combat/reload/aim, navigation, capture, radio and recovery regressions
  remain enabled. Update obsolete immediate pressure-switch/minute-lease and
  deleted-class-mask expectations to the approved tasks and reserve semantics.
- Collision-only Great Wall and Himmelsdorf replays retain their reviewed build
  506 lane IDs explicitly, so changing the fresh lottery does not change their
  physical inputs. Separate runs use the new lottery with the actual server
  planner and recovery owner. Do not lower their passage or occupancy checks.
- The old default source and all baked geometry are unchanged. A 41-map audit
  checks that only historical class masks migrate to reserve, with aligned
  shared travel and no resurrected waits. The three exceptional spawn/base maps
  (Mittengard, Tundra, Ghost Town) have a separate editable review profile;
  their public Default geometry is not replaced by that draft.
- CPython 2.7 compilation and exact packaged bytecode verification cover all
  client sources. Frozen source checks cover the launcher and server payload.
- Engine-free simulations and baked graph timings do not establish native
  Windows physics, live FPS/ping or map gameplay acceptance. Final acceptance
  still requires the diagnostic entrance on the exact CN HD #1513 client.
- The expanded flat-world Fjords/Airfield departure simulation currently has
  an unresolved Airfield 15 FPS one-minute departure failure after ordinary SPG
  assignments are removed. Keep the original assertion and failure evidence;
  allocation/own-route checks passing does not establish traffic acceptance.
  This candidate must disclose that failure rather than silently change motion
  laws or weaken the departure bound to make packaging appear fully validated.


## Current shared baseline and complete map checks

The owner-approved Default remains shared by all installations, with all 41 maps,
82 independent artillery attacks and ordinary defense branches only on
Mittengard, Tundra and Ghost Town. Retire the 246 deployment and 492 directed
parking relocation paths; retain every parking position, ordinary route point,
wait, tier, defense branch and attack point exactly as reviewed. Do not simplify
or re-route those retained geometries during this editor task. Existing Default
materializations refresh; independent custom geometry remains independent.
The standalone review profile is not shipped or recreated.

The map check expands effective team/class routes, reserve lanes, waiting places,
parking regions, artillery attacks and configured/required defense branches.
Configured/correct, configured/incorrect and unconfigured are distinct; disabled
lanes are listed separately. Use the shipping navigation checks in both directions
and bounded area-goal snapping for base/parking circles. Ordinary intermediate
nodes remain strict. Passing results say navigation-data checks passed, not live
physics acceptance. Locate selects the exact branch/node without editing;
changed geometry/profile invalidates old reports and location requests.

Tree text and map geometry share the class palette; All-classes is black,
artillery is red. Language/view changes preserve pending edits and selection.

Regression gates: run all launcher tests, especially artillery, connection,
inventory, adopted-default, route-control and localization tests. Connection
regressions exercise shared -> individual -> shared edits, Total-view edits,
common point-sequence/junction resets, later independent class edits, symmetry, deletion,
transaction rollback and undo/redo. Artillery tests cover old-file migration,
no retired controls/data, all-map display and retained attacks. Route-task tests
cover automatic parking even with stale caches, offset spawn/base sequencing,
base-circle handoff, at-most-three sorties, defense return/resume, and unchanged
combat ownership. Frozen editor smoke requires both class colors and automatic
parking receipts; inspect downloaded client bytecode/server/frozen launcher sources
against the exact pushed commit. Compile all client sources with CPython 2.7.18.

Keep the existing Airfield 15 FPS departure and opposed Great Wall gate failure
assertions. Editor/static navigation/package checks do not establish native
bridge, slope, wall passage or worker performance. Real-client tests must use
START_DIAGNOSTIC_TEST to collect the existing diagnostic logs.

Local validation of this change: all 34 launcher test files pass after final
transaction/UI/route-control reruns (1,113 discovered checks, existing local
environment skips retained). The connection tests exercise the complete
shared/single-class/symmetry/rollback contract. Seven route/runtime files pass
119 checks; 31 additional editor/runtime integration checks pass in explicitly
engine-free reference mode. All 209 client sources compile under CPython 2.7.18.
Exact Default comparison against the previous commit proves that only parking
travel/links were removed, preserving every other field on all 41 maps. Source
editor smoke exercises automatic parking UI and real shared defense edits with
undo/redo; the frozen-package verifier requires these receipts too.

The final common-edit clarification is covered by explicit point-order resets:
a class whose old junction was point four is replaced by the common point-three
road/junction. Main point insertion/movement/deletion uses the same family reset
as defense edits, while subsequent single-class changes remain local. Tests
retain per-class priorities, reverse-team endpoints and valid unchanged-node
waits. The frozen editor verifies different old node counts are unified, with
`common_route_reset` required by the downloaded-package verifier.

Reset-route/default restoration is an explicit baseline operation, not another
common geometry edit: restoring must not recreate overlays just removed or
propagate over freshly restored class defaults. Navigation tests fail fast on
unexpected error dialogs and exercise this reset path. Final navigation,
connection, route-control and launcher-window reruns all pass after this fix.

Fixed endpoint validation also accepts the packaged common endpoint for a class
variant after a common reset. The old class endpoint stays legal for untouched
or restored class defaults; arbitrary endpoints remain rejected. This matters
on Mittengard and Tundra, where existing class/common endpoints differ. The
all-map regression resets every ordinary class family across all 41 maps, saves
and reopens the entire profile, then checks later class edits and rejection of
a detached endpoint without changing the applied profile.

### Owner-selected artillery corridors (2026-10-25 follow-up)

The shared Default uses the following class-specific corridors for both teams'
artillery attacks, except the explicitly different Erlenberg team choices.
Copy the intermediate coordinates in their original order, clear ordinary
waiting behavior, and retain exact own/enemy objective-base endpoints. Do not
copy ordinary-route priorities, defense branches or allocation membership.

| Map | Ordinary corridor source |
| --- | --- |
| Kharkov | Light / factory |
| Erlenberg | Team 1 Light / north_bridge; team 2 Light / south_bridge |
| El Halluf | Light / south_valley |
| Ensk | Medium / east_field |
| Mittengard | Light / rim_west |
| Lakeville | Light / east_town |
| Redshire | Light / river_town |
| Arctic Region | Light / west_lakeside |
| Sacred Valley | Light / river |
| Mountain Pass | Light / central_basin |
| Sand River | Light / village_road |
| Himmelsdorf and Winter Himmelsdorf | Light / banana |
| Airfield | Light / south_towns |
| Westfield | Tank destroyer / east_fields |
| Malinovka | Light / central_field |
| Siegfried Line | Light / east_city |
| Ruinberg and Winterberg | Owner profile 1 Ruinberg Light / central_streets |

Ruinberg's two edited seven-point Light routes from profile 1 also become the
Light and Medium class overrides in both Ruinberg and Winterberg, retaining
each map's ordinary fixed endpoints. Winterberg's corresponding built-in
family is `city`; keep that internal identity and label the two class overrides
Central streets. Leave shared/heavy/tank-destroyer geometry unchanged.

Verification: all 38 changed artillery attacks and eight ordinary class rows
pass the actual editor inventory's directional navigation-data checks. The
complete profile passes canonical/fixed-endpoint validation and save/reopen.
An exact whole-profile comparison excludes only these permitted changes and
proves all other geometry, parking, behavior and metadata unchanged. Refresh
the adopted-default digest fixture, retain the existing all-map default tests,
and compile the modified client data module under CPython 2.7.18. No native
passage or artillery combat/performance improvement is established by this
data-only change. The existing editable profile 1 retains unrelated edits and
receives the same requested routes for immediate owner review; do not delete it
or change the selected applied profile.

### Map-dependent ordinary endpoints and Tundra follow-up (2026-10-26)

Endpoint policy is a map property, not the route's symmetry checkbox. On maps
whose two spawn anchors are inside their respective capture circles, ordinary
routes keep the two fixed spawn endpoints. On unsupported asymmetric maps,
ordinary routes start at the own spawn and end at the enemy capture objective.
Preserve existing valid packaged class endpoints inside that circle; remove
the old enemy-spawn exception when it lies outside the circle. Artillery
attacks retain own-base to enemy-base endpoints under both map policies.

Fix the 19 stale ordinary/default endpoints in Mittengard team 1 and Tundra
both teams, including shared rows hidden by class overrides. Keep intermediate
geometry. Migrate the same old enemy-spawn ends on owned profile read, import
and editor adoption, using generated lightweight spawn/objective/radius data
rather than loading every navigation mesh. New/copy/mirrored roads use the same
policy, including untouched baked fallback roads and sixteen-point copies.
Canonical four-decimal anchors must survive save/reopen without false changes.

Capture objectives are area goals: a missing center cell can use a bounded
three-cell usable endpoint inside the same capture circle. Directed graph
connectivity is still required; ordinary intermediate nodes stay strict.
Admission and detailed route diagnostics must agree. No steering, collision,
combat, worker cadence or recovery laws change.

Promote profile 1's current Tundra team-1 artillery attack and its reversed
team-2 version to shared Default. Both Erlenberg attacks use each team's Light
north_bridge road. Tundra team-2 village and plateau defense paths for all
ordinary classes use the owner's current Heavy defense geometry. Align the
plateau TD junction to the Heavy's first intermediate point, preserving other
main nodes, stable junction references and own-base defense ends. Retain profile
1, unrelated edits and its applied selection.

Team switches clear connection/drag/wait editing state. Connection drawing
rejects a foreign-team row and tags each line with its actual team; real Tk
tests switch 1 -> 2 -> 1 in Total view and assert no opposite-team lines.
Regression coverage also checks symmetric Erlenberg endpoints, offset Tundra
endpoints, old-file migration, full-map save/reopen and a missing capture center
that cannot legitimize an invalid ordinary intermediate point. The actual
source/frozen editor smoke requires `map_endpoint_policy_and_team_connections`.

### Total-view route tier controls (2026-10-26)

Selecting an ordinary route in Total view must allow changing the selected
class's main/reserve tier. Remove both the stale disabled-button condition and
the action's Total-view rejection. All classes still changes only the current
map/team/family's tier metadata; individual class changes remain independent.
Do not propagate tier changes through the geometry/defense synchronization.
Changing one class of a multi-class custom road splits its class ownership while
retaining the same points and independent sibling tiers. Do not change route
geometry, waits, defense branches, allocation laws or runtime behavior.

Disable the conversion to the already selected tier. Both controls stay locked
for immutable Default, no selection, parking, artillery attacks and active
defense editing; direct handler calls must preserve those guards too. Actual Tk
regressions invoke buttons in Total view for built-in and custom families,
verify complete document differences, undo/redo, save/reopen, common-scope tier
propagation and protected contexts. The real source/frozen editor smoke requires
`total_view_route_tier_controls` and exercises conversion, undo/redo and save.

### Three-map owner review promotion (2026-10-26)

In profile 1, replace only Mittengard's six All-classes rows: both teams' rim_west
use their Light road, pit their Heavy road and rim_east their Medium road. Copy
the selected road's coordinates/order, stable node identities and attached
defense topology so the adopted common road cannot retain detached references.
Common nodes have no waits. Preserve class-specific rows and all target tier,
priority and labeling metadata.

For Ghost Town, only team-1 park and team-2 outskirts Medium/Heavy/TD defense
branches adopt the corresponding Light branch. Rebind to each target's existing
unique matching intermediate node. Keep their main points and every other field
unchanged, including the black common branch and the Light source itself.

Then promote exactly the complete profile-1 map entries for Tundra, Mittengard
and Ghost Town into shared Default. Retain the other 38 maps and global behavior;
do not delete profile 1 or switch the applied profile. Exact whitelist comparison
limits personal changes to these twelve rows and shared changes to these three
complete maps. All 168 map inventory entries are configured/correct, including
both directions, parking, ordinary roads, defense branches and artillery attacks.
Both complete profiles save/reopen; the adopted-default and baseline tests pass
all 16 checks, and the changed client data compiles with CPython 2.7.18. Native
physics passage remains a separate gameplay check. Ship the new Default in both
client and server payloads; old packaged Default references cannot represent
the newly adopted fixed common endpoints.

### Mittengard west class alignment (2026-10-26)

In profile 1 and shared Default, only both teams' rim_west Medium/Heavy/TD rows
adopt the current profile-1 Light row's complete points, stable node sequence
and attached defense branch. Preserve each target's tier, priority, label and
all unrelated rows/maps/behavior. Exact field-whitelist comparisons guard both
documents; the complete profiles must still save/reopen. Directional navigation
and defense checks pass, and all four classes now use the same west geometry:
477.3m planned for team 1 and 489.0m for team 2. The former west large-detour
screen flags are absent. This is a planning-data result, not a native heavy-hull
clearance guarantee. Retain the adopted-default/baseline regressions and fixture
digests. No runtime, editor or allocation code changes.

The other flagged corridors remain unchanged. Owner-facing node-location
evidence must identify map, team, class, family, one-based edge nodes and exact
X/Z coordinates, rather than just listing map names or total distances. At this
snapshot: Paris tower_east TD 1:7->8 / 2:4->5; Siegfried fortification_line
Heavy/TD 1:6->7 / 2:7->8; Westfield east_fields TD and SPG attack 1:5->6 /
2:3->4; Sacred Valley hills Light 1:6->7 / 2:8->9; Stalingrad city Light
1:8->9 / 2:6->7 and Medium 1:11->12 / 2:4->5. Re-audit after node insertion
or deletion because later indexes change. A flagged edge does not identify
which of its two nodes is wrong; terrain/obstacle necessity needs review.

### Screenshot-local Stalingrad navigation and complete profile promotion (2026-10-26)

The requested yellow samples are navigation mesh nodes, not the numbered
authored road anchors. Preserve every Stalingrad road coordinate, ordering,
stable identity, wait and defense branch. The complete map content, excluding
its refreshed graph fingerprint, is pinned by the new regression digest.

Decode pinned #1513 collision and terrain offline. Add fourteen bounded two
metre patches at the screenshot circles while retaining the original four
metre base arrays, routes, spawns and objectives. The 17,048 local samples
include 11,448 supported nodes; unsupported samples remain closed. Retain the
original 2.15m node clearance disk, body-height collision clipping, slope,
water, reciprocal links and diagonal support checks. The old base grid is not
globally refined and no collision restriction is relaxed. The baker accepts
an explicit output candidate and does not silently install it.

Require complete paths in both directions through all fourteen circles, with
bounded costs rather than merely testing nonempty planner frontiers. The
former Light city edge around (-168.75,-210.64) to (-167.48,-245.49) now plans
35.8m forward instead of 716m; the Medium edge around (-375.86,-294.86) to
(-293.84,-315.84) plans 86.5m instead of 365.9m. The authored anchors are unchanged.
`check_stalingrad_local_meshes.py` submits all 150 unique current authored and
passage forward/reverse edges three times to the compiled worker. CI builds
that executable from current source and retains its completion/timing report.
Local benchmark timing is diagnostic evidence, not a claim about live ping.

Promote map configuration only after auditing all 41 effective maps, including
both teams/classes, ordinary roads, parking, defense and artillery attacks.
Preserve shared Default behavior parameters. First-run, reset, save/reopen,
profile deletion and independent-profile regressions must retain the adopted
shared map baseline. Delete local profile 1 only after successful promotion
and switch its applied snapshot to Default; package both server source and
Python-2 client bytecode with matching maps and fingerprints. A packaged editor
smoke and independent archive verification supplement source tests; native
physical passage remains a separate match acceptance boundary.

The final Siegfried scope is the four circled town groups and their street
entrances: four 2m patches plus one 16x18m, 1m corner pocket. The original
(80.8441,-67.0406) anchor is physically clear, but its nearest 2m centre falls
on the wall; the tiny pocket preserves the authored point without opening the
wall or refining the whole town. All 23,559 local samples retain the original
clearance/grade/water checks. Both teams' Heavy fortification_line adopts the
current same-team TD geometry and stable references, preserving tier metadata.

Read the owner's latest Westfield TD symmetry before copying artillery. Keep
both TD roads exactly as edited; both artillery attacks use those intermediate
coordinates without TD waits and retain own/enemy base endpoints. Audit the
complete candidate after copying, not an earlier owner snapshot. The final
41-map inventory contains 1,384 configured/correct entries, no nonadjacent
node repetitions and no former large-detour screen flags. These checks do not
prove that all native vehicle hulls can pass in a live battle.

Keep the existing water-rebake receipt comparisons for every original layer.
Later additive local meshes are checked separately against their measurement
count, 1.2m water policy, exact-client collision provenance and graph schema;
they must not replace or weaken the old water-layer assertions. The existing
41-map static water audit passes with the new additive layers.

Route admission and its detailed authoring report previously consulted only
the coarse SPG graph even when the navigator used additive local meshes. A
physically supported fine-only corner could therefore pass the editor's
inventory but silently fall back to the original road at battle setup. Maps
with local meshes now admit ordinary/wait travel over the same baked local
nodes and directed links. Cache directed reachability for one plan; do not
change parking clearance, live collision, combat or worker control. Intermediate
points must own a safe sampled cell; only existing capture-circle endpoints
retain bounded area snapping. Negative regressions reject an identical anchor
after marking its fine cell hazardous or disconnecting its local links. The
six shared-default regressions include a complete no-fallback check and now pass.

## Build 531 live audit and diagnostic follow-up (2026-10-26)

The ordered diagnostic session `20261025T205441Z-18046da53777` exercised
23/41 maps, not the full inventory: 12 ordinary wins/losses, four timeouts and
seven `IndexError` server-tick terminations. The owner later closed the game
normally; that exit is not a crash. Preserve the remaining 18-map coverage gap.

The tick supervisor now emits opt-in `SERVER TICK TRACE` JSON parts before
handling the original failure. Reassemble ordered `data` parts by round/tick;
retain the throw-site traceback, map/phase and whitelisted actor, task, route
index and point-count context. Do not log arbitrary locals or actor rosters.
Basic mode must not construct a traceback. A failed formatter must not replace
the gameplay exception. The existing terminal barrier, no-settlement policy,
reset and fixed-step catch-up remain unchanged. The original array/throw site
is still unproved until the next diagnostic reproduction; do not blanket-catch
`IndexError`, clamp an unrelated cursor, or retry a partially consumed tick.

Stalingrad T-10 entity 19 remained at approximately (51.7272,59.9369) for the
last 180 seconds. Worker receipts show nearby wrecks 7/9/14/22, rejected reverse
world sweeps and forward vehicle occupancy. Recovery counts reached 161 and
macro cursors still changed. This proves repeated attempts without movement,
not a stopped retry loop or a proved viable exit. Keep existing collision and
combat laws. The compact 15-second `BOT RECOVERY POCKET` now retains decision
and control sample times, driver-clock short-escape observation age, complete
pivot outcomes, alignment, failed headings and local target retirement even
when the large motion-history budget is exhausted. No extra geometry query is
allowed for this diagnostic.

The five suspected artillery deployment stalls on Arctic and Sacred Valley
were false positives: worker receipts show `artillery_hold` within two metres
of replacement positions while server records retain the old deployment goal.
Diagnostic-only `SPG POSITION STATE` reports received and effective modes/goals,
adopted parking position, radius and occupancy every 30 seconds, independently
of the bulk-history budget. Do not change deployment or firing behavior.

Worker captures establish significant Bot-update cost and queue age, but do
not establish local mesh density as the cause. One sampled Kharkiv callback
took 340.641ms, including 317.552ms in Bot update; another queue capture recorded
2489.014ms oldest wait. Captured slow frames are not a full-session average.
The confirmed optimization avoids constructing diagnostic-only collision and
refusal copies in normal-mode `_report_blocked_planner`; local-action feedback
and private replans still run. No physical query, simulation interval, contact
proof, target selection, combat policy or queue cadence is removed or relaxed.
Do not promise a live-ping improvement from static tests.

Run server tick supervision, recovery-return/pocket, SPG-position diagnostics,
complete-pivot handoff, combat manoeuvre and diagnostic-mode regressions first;
then the existing navigation, motion, recovery, capture, artillery, worker and
postbattle suites. Validate Python-2 client compilation, inspect the downloaded
frozen launcher/server/client bytes, and carry this precise coverage boundary
into the delivery handoff. Native T-10 exit and server throw-site acceptance
remain next-run tasks, not claims made by this diagnostic package.

Local follow-up validation: six focused files / 61 tests pass. The wider
62-file / 1,030-test reference run also passes. Running that wider set directly
under Windows Python 3 without its matching native extension leaves 13 files
with native-simulation-unavailable errors; retain that result separately from
the Linux-semantics reference run. All 209 client modules compile under pinned
Python 2.7.18. CI and independent final-package evidence are recorded in the
delivery handoff rather than inferred from these local reference checks.

## Build 532 eight-match reproduction and empty-route correction (2026-10-26)

Diagnostic session `20261026T050318Z-ead8c7d38067` retested the seven maps
previously terminated by the server and Stalingrad. El Hallouf, Canada,
Prokhorovka and Cliff finished normally. Lost City, Tundra, Paris and Stalingrad
terminated in `RouteTasksMixin._task_begin` at the reverse source comprehension.
All four complete traces show `map_route`, zero waypoints and `base_defense`:
bot 30/team 2 in the first three, bot 14/team 1 in Stalingrad. The failure is
an empty-source indexing defect, not evidence that these four meshes are wrong.

Skip only the nonexistent reverse-source leg. Keep the existing base target,
circle arrival, local navigation, safe-time release and artillery return owners.
Configured ordinary roads still reverse their authored points and defense
branches. Do not borrow another vehicle class's road or catch/retry a failed
server tick. Replay all four captured map/actor combinations through the real
planner's order-building path; first demonstrate the old IndexError, then
assert a nonempty direct-base task. Cover absent/empty/single-point sources,
artillery and ordinary vehicles, automatic defense and player guard, arrival,
combat preservation and release. The empty-source diagnostic is opt-in, capped
at 64 reports per round and cannot prevent task creation if output fails.

Paris also recorded a WZ132-1 model-refresh AssertionError at 13:46:40:
callback `destroyed`, current state `exploded`. This preceded, but did not cause,
the 13:49:59 server indexing failure. Preserve the native callback and exception;
record the last 16 callback entries, sequence, scalar appearance/vehicle identity,
state before entry, return/assertion outcome and assertion frames. No reference
to a native appearance/entity is retained. The existing eight-refusal report cap
remains. Basic entry retains no diagnostic history. Test return values, original
exception identity, bounded history and formatter failure without changing the
appearance or suppressing assertions.

The Stalingrad T-10 died early in this run, so its previous persistent wreck
pocket was not reproduced. Existing 15-second recovery receipts now also identify
the vehicle/name/team, travel-task owner and age/clock of the last execution
receipt. Old execution displacement must not be mistaken for this decision's
movement. Read existing receipts only; do not add a physical query or alter
recovery/combat rules. The eight captured worst worker frames range from
175.696 to 295.172 ms, not average ping. The latter contains 275.86 ms of Bot
update and 124.121 ms oldest queue wait. These samples do not justify speculative
cadence, collision-budget or native-migration changes. No live performance gain
is claimed. Subsequent owner roof-crush testing confirmed no cross-round blue
name; team-killer behavior is outside this correction.

## Build 533 follow-up: capture donors, friendly kills and diagnostic gaps

Session `20261026T073700Z-bb978d495a87` completed eight maps without the previous
empty-route exception. A successful result did not prove every tactical order
was correct: on Canada at 16:03:35, pressure rebalancing selected bot 17 while
it contributed 28 capture points. Its order changed to `route_transfer`, cleared
the capture hold, and reduced total points from 59 to 34 after leaving alive.
Exclude canonical contributors, physical first-tick arrivals and retained
circle re-entry holds before donor admission. Keep ordinary pressure transfers,
explicit defense/player tasks and combat behavior unchanged.

On Stalingrad at 16:48:25, bot 28/team 2 killed the same-team player with shell
`8:b:28:2`; the client reported destroyed ammunition storage and the server
committed 1,497 HP loss. Bot `_record_frag` failed to set `team_killer`, unlike
the player branch. Set it for the shared friendly-kill path and publish the
actual Bot flag in public result rows. Test both actor and victim kinds,
nonlethal damage, player splash/reflected terminal retries, both result flag
values and next-round cleanup. This does not introduce cumulative-damage
thresholds, new blue-victim exemptions or friendly ram damage. Replaying the
three new regression cases against the old methods fails four assertions:
both Bot victim kinds, the Bot result flag, and capture-donor admission.

The El Hallouf IS-7 callback at 15:45:41 still asserted with current `exploded`
and callback `destroyed`. Preserve its native callback, return and exception.
At the diagnostic entrance only, observe state reads and callback entry/return/
assertion in a per-appearance scalar ring: at most 64 appearances, 24 entries
each, cleared at battle start. Include observed caller and wall time; a state
read is not proof of a load request. Keep the existing global callback ring and
eight-refusal output cap. Test unrelated global traffic, bounded storage,
disabled mode and diagnostic failures without retaining engine objects.

The 437.434-ms Lost City worker frame contains many motion/ground queries.
Opt-in detailed frames now retain at most eight repeated geometry signatures
from the existing bounded 2,048-key observer, including actor, slice, stage and
count. Truncated keys identify candidates for investigation, not safe cache
reuse: scene state may change. Do not add collision queries or change physical
budgets, navigation, control cadence, combat or native laws. A repeat count is
not a native error, average ping, or a claimed performance improvement.

Validate the focused cases, existing capture/defense/pressure/task/projectile
and lifecycle regressions, Python 2.7 compilation and exact-commit CI. Inspect
the downloaded package independently. Native acceptance must still reproduce
the original T-10 wreck pocket; this session's different-team T-10 used the
railway road and was destroyed after making progress. Keep model/performance
issues open until their new receipts establish the cause.

Validation starts with focused task/model/recovery/diagnostic tests, then the
existing route, artillery, capture, command, combat and lifecycle regressions.
All client sources must compile under Python 2.7.18. Exact-commit CI, downloaded
package byte comparisons and the next native-client acceptance are separate
evidence boundaries; retain the known Airfield 15-FPS and opposed Great Wall
failures rather than weakening assertions or describing full CI as green.
