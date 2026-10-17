# Temporary bridge-drop fixture

This branch is a test entrance based on Windows325. It must not be merged into
main as a gameplay change.

Extract the complete Windows package and run START_ROOF_CRUSH_TEST.bat.
Create a room and start normally. The server pins Victory Gate (37_caucasus),
15 versus 15, and human players to team 1. Enemy slots contain fifteen Type 59s
in a close 3-by-5 array below one bridge edge (3.5 m lateral, 6.4 m longitudinal). The fourteen friendly Bots form one 3.5 m-spaced row on the same-side deck edge, noses outward, centred along the enemy array. Human slot zero keeps its normal base spawn. All Bots hold
and do not fire; gravity, support, external pushing and damage remain active. Physical pair responses now classify oriented 3D body contact before horizontal separation; vertical contact remains with suspension. Initial impact damage is unchanged.
Drive to the bridge and drop onto a target. Start another battle to reset targets.

The flag exists only in the launched process environment. Close both the game
and launcher before returning to the ordinary EXE. Do not reuse an already
running game or server from another launcher for the fixture.

The seed Y excludes the bridge deck. Native ground queries choose actual spawn
heights and log each enemy slot; no synthetic floor or position lock is added.
Native placement and contact still require the exact Windows client test.

The temporary flag is WOT_OFFLINE_ROOF_CRUSH_TEST=1. No route profiles or
persistent physics settings are changed. No navigation or support switching algorithm is
changed. Ordinary launches without this flag retain the baseline behavior.
