# Waiting-room proportions and canonical-path progress follow-up

This is an unpublished PR 113 test candidate, not a 0.10.2 release.

## Report and scope

Report `20261022-024540-d06e9b60113c` contains Serene Coast and Windstorm.
Enemy Lorraine 155 50 (first round, bot 13) received base defense at 02:27:03.
It had one loaded round by 02:27:05, with ammunition inventories 10/14. Its
close-range planning returned `no_candidate`; that record does not identify
which physical candidate condition rejected it. The final native aim record
requires +0.070067 rad local gun pitch (about 4.01 degrees depression), but
the installed native range is [-45, 0] degrees and the gun stops at 0. That
final close-range aim is genuinely outside depression. Keep existing gun limits,
ballistics, real obstruction checks and defense movement priority.

Windstorm bots 29 (T71 CMCD) and 30 (Bat.-Chatillon 12 t) repeatedly revisited
the same river pocket. Bot 30 recovery count rose from 5 to 54 between
02:34:51 and 02:39:15. Canonical path/corner changes reset the old per-leg
macro-progress baseline. The temporary-fallback watchdog did not cover all
complete-path handoffs.

## Changes

- Retain actual best distances to issued canonical endpoints and visited
  realised cells across private path and corner changes within one request.
  First seeing a different endpoint does not count as physical progress.
  New terrain or improvement beyond a previous endpoint best still counts,
  including a necessary dogleg away from the final goal. At the existing
  12-second deadline, invoke the existing private macro retry. Holds, arrival
  and new requests end the movement episode. No shared obstacle marking,
  new route scoring, terrain rejection, collision bypass or water-limit change.
- Expose bounded frontier age, credit reason, previous best and retry count
  in the existing search diagnostic. No added terrain queries.
- Record low/high artillery candidate rejection at generation, including
  muzzle/target pose, shell physics, world/local pitch, actual pitch limits,
  flight time/range and excluded arc. Retain the receipt with its planning
  key through pending/cached/failed states; clear it on replacement/reset.
  Diagnostics reuse the already computed solver values.
- Waiting form: 640x286, 14 px body/button text, original 16 px title;
  move its center upward by adjusting the reserved stock text band. Use
  pinned #1513 `guiControlsLoginBattle.swf` ButtonNormal bitmap 108, matching
  the stock Modify/Close control family. Nine-slice 24/100/128/180 x 22 faces
  without squeezing their bevels. Reduce side frame/content insets and the
  bottom bar to stock-window proportions; remove the excessive team-row gap.
  Standard/training share this form. Preserve all room callbacks, difficulty
  order/default/acknowledged memory and stock map picker.

## Validation boundaries

Focused regressions cover corner/path churn, revisiting known cells, real
dogleg travel, existing private retry, changed requests, zero-depression
rejection/cached diagnostic lifetime, native bitmap bevels and UI controls.
Recorded position/target replay admits watchdog stalls for both light tanks;
it is not a simulation of the movement after a changed decision.

Pure reference runtime tests run under the same non-Windows reference
contract as Linux CI. The Windows game requires its x86 Python 2.7 native
extension; a local x64 Python 3.11 interpreter cannot load that extension.
Do not report such loader failures as gameplay regressions or alter runtime
authority to make reference tests pass. Package inspection and exact-client
rendering/physics acceptance are distinct evidence layers.

Native GUI appearance, actual post-retry escape and the Lorraine's precise
close-range rejection require owner testing of the new package. Support mode
remains one missing point enables detailed support, all five valid disables it.
