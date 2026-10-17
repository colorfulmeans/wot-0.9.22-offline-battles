# Temporary bridge-drop fixture

This branch is a test entrance based on Windows325. It must not be merged into
main as a gameplay change.

## Shot-triggered drop onto the player

Run START_ROOF_SHOT_DROP_TEST.bat for the second fixture. The player spawns
below the same bridge edge; fifteen enemy Type 59s wait in two lanes above
and on its approach, leaving the deck edge clear until released.
There are no friendly Bots in this fixture. Every acknowledged player shell
launch releases exactly one living, unreleased Bot in slot order. Reload clicks
and repeated snapshots do not release another Bot; missed snapshot sequences
still release one Bot per accepted shot. After fifteen releases, start a new
battle to reset. Bots never fire. Wait for the preceding Bot to fall before
firing again if separate impacts are desired.

Released Bots use fixture-only steering through the clear deck apron and off
a common edge toward the fixed player spawn lane. Stay near spawn to receive
the drops. The endpoint is fixed, not a homing or guaranteed-impact mechanic:
native placement, descent and actual contact must be tested in the client.
The player seed is 3.5m farther outward than Windows340, centred at lateral
12.5m from the bridge baseline. This matches the first two recorded contact
centres (12.775m and 12.207m) in report 20261017-175512; Bot driving is unchanged.
No teleport, position lock, synthetic support, impact or damage is added.
ROOF SHOT DROP records releases, apron waypoints, falls and queue exhaustion.
The extra process-only flag is WOT_OFFLINE_ROOF_SHOT_DROP=1, in addition to
WOT_OFFLINE_ROOF_CRUSH_TEST=1. Close both game and launcher before switching
entrances. The old START_ROOF_CRUSH_TEST.bat arrangement is unchanged.

Extract the complete Windows package and run START_ROOF_CRUSH_TEST.bat.
Create a room and start normally. The server pins Victory Gate (37_caucasus),
15 versus 15, and human players to team 1. Enemy slots contain fifteen Type 59s
in a close 3-by-5 array below one bridge edge (3.5 m lateral, 6.4 m longitudinal).
The player starts on the bridge. Six friendly Bots park broadside to the edge,
with hulls parallel to the bridge, and eight wait at the bridgehead. All Bots
hold and do not fire; gravity, support, external pushing and damage remain active.
Physical pair responses retain oriented 3D intersection testing. Top/bottom
contact remains with suspension; intersecting bodies whose centres are both
inside the other's thickness slab separate along the 3D horizontal axes.
This prevents an embedded same-layer pair from losing both response owners.
Start another battle to reset targets.

The flag exists only in the launched process environment. Close both the game
and launcher before returning to the ordinary EXE. Do not reuse an already
running game or server from another launcher for the fixture.

Native ground queries choose actual spawn heights and log each slot. Fixture
startup waits for loaded bridge geometry; no synthetic floor or position lock is added.
Native placement and contact still require the exact Windows client test.

The temporary flag is WOT_OFFLINE_ROOF_CRUSH_TEST=1. No route profiles or
persistent physics settings are changed. No navigation or support switching algorithm is
changed. Without the flag, ordinary room/spawn/driver behavior is retained;
the contact, damage and performance fixes on this test branch also apply to
ordinary launches from this test package.


Support sampling reuse is confined to each synchronous support solve. Exact
terrain rays (including filter identity), roof rays and prepared body/component
matrices are shared only within that solve; None results are cached, failures
are not. Different endpoints, poses or later solves query afresh. The full
elapsed-time physics loop and all support admission rules are unchanged.

SUPPORT QUERY PERF emits per-actor windows with call/cache counts and wall time
for candidate_select, filter_prepare, terrain, matrix_prepare, roof_stage,
roof, native_bsp and probe_log. Timings are inclusive: roof_stage contains roof,
matrix_prepare and probe_log; roof contains native_bsp. context_total includes
the support solve, while previous_emit_ms reports the preceding summary write.
physics_dt_s records consumed/observed support intervals. Do not add nested
timings together. Results still require exact-client dense-stack acceptance.
