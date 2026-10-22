# Native training room and standard map picker

## Scope

The standard LAN room keeps its existing layout and policy. Dropdowns use the
stock `ScrollBar` linkage when more than eight rows are present. The builder
checks this linkage against #1513 control SymbolClass definitions.

The map picker uses a mod-owned copy of the exact native training settings
movie. It keeps all authored controls, constructor properties, minimap and
stock selection/time handlers. Its title is Select map, its apply button is
Confirm, the unused invitation checkbox is hidden, and its capacity text uses
the live team capacities. A post-native map selection listener reapplies that
text when selecting another map. The actual battle duration path is unchanged.
The native TrainingWindow base QName is retained independently of the renamed
document class; the compiled output is decompiled and checked during building.

Training loads the unchanged `trainingRoom.swf` as a LOBBY_SUB page through the
native TrainingRoomMeta DAAPI contract. It does not enter RandomEntity's queue
or load BattleQueue beneath it. The LAN controller supplies the native map,
time, roster, capacity and permission models. No WG legacy prebattle entity
is fabricated. Start, map selection and leave retain their existing controller
boundaries. Unsupported remote-player reassignment, observer and voice controls
are disabled; personal team choice remains in Training settings. The native
invite button is explicitly labelled Training settings and opens the stock
control settings window for bots, difficulty, capacities and personal team.
Closing this child returns to the native training room without leaving LAN.

Training has its own title, training icon, Start training button and persistent
no-rewards/no-mission-progress description. Standard mode keeps its original
labels and queue background. Mode switching retires the previous page and
queue; delayed actions are fenced by room tokens and current view identity.
Native event callbacks defer teardown until the following BigWorld callback.
Training settings Escape closes the child instead of leaving the room.

## Exact client evidence

Chinese HD 0.9.22.0.1 #1513 x86. Inspected the native package's
`gui/Scaleform/daapi/view/lobby/trainings/__init__.pyc`, `TrainingRoom.pyc`,
`TrainingSettingsWindow.pyc`, `meta/TrainingRoomMeta.pyc`, `MinimapLobby.pyc`,
and native lobby ActionScript TrainingRoom, TrainingWindow and their VO/meta
classes. Native TrainingRoom registers trainingRoom.swf as LOBBY_SUB with the
default scope and seventh ViewSettings argument True; the offline registration
matches this contract under its own alias. MinimapLobby supports setMap without
a legacy training entity. The stock native Python TrainingRoom itself checks
TRAINING legacy state, so the offline adapter uses its generated meta base.

## Validation and acceptance

Focused tests cover live roster/map/time/capacity models, host permissions,
child close, Escape, delayed callbacks, stale generations, mode-specific room
opening, existing map/time application and standard queue behavior. Build gates
check both generated movies against their source/provenance. CPython 2.7
package verification checks every client module against current source.

These prove source, adapter and package contracts, not live Scaleform rendering.
On the exact Windows client, verify native training page rendering, minimap,
Training settings dropdowns, closing settings, personal team changes, selecting
a map and duration, starting training with bots off/on, leaving and rejoining,
and switching back to Standard. In Standard, verify overflow scrollbars and
map-picker capacities after changing maps. No release publication is requested.

Local results: 396 isolated reference test files passed, with the changed map
and native training adapter suites rerun after the final test edits. The local
CPython 2.7 package contains 198 verified client modules and 237 valid members.

The preceding PR head 12e77cb7 has an existing CI native-geometry failure in
check_native_world_pipeline.py at wreck/2 (ordered engine query trace). Its
state/report comparisons precede that failure. This UI change does not change
worker/native geometry or suppress that gate; it is not claimed resolved by
these local reference tests. The Windows package build is a separate workflow.

## Package 455 native binding regression (14:13 report)

Report wot-error-report-20261022-141311-a025163f2bf8.zip confirms package
colorfulmeans-39731209031-1. At 14:13:05.155, TrainingView fails inside
BaseDAAPIModule.setFlashObject -> DAAPIEntity.turnDAAPIon, before _populate.
At 14:13:05.432 the captured client raises 0xC0000005 writing address zero at
WorldOfTanks.exe+0x008AC38C. The minidump module timestamp 1517214884 and checksum
26890793 match the inspected installed executable (SHA-256
7fab583e04579dd3e1bffb3abede622acb7b65d6190087952833a22c456fffb3).

The Python TrainingView used a public owner attribute for its LAN adapter;
the original AS TrainingRoom declares owner:UserNameField. The exact binary's
script setter at VA 0x00AB2FB9 calls binding at 0x00AB11E0. That code collects
child names (0x00AB1650; its collector visit at 0x00AB0C80 retains names without
checking value types), probes Python attributes at 0x00AB12C0 (0x00FB3C90), and
attempts callback installation for matching names. It does not first check
that the Python attribute is callable. Thus the public owner context collides
with a typed, non-function AS slot. The failure is then replaced by the generic
Can not initialize daapi exception. The later minidump shows a damaged native
allocator list; it does not independently reconstruct the complete corruption
history, and no allocator patch or crash-containment guess is introduced.

Rename binding context to _offline_owner and _offline_token, including teardown
and all delayed action ownership checks. Preserve raw binding failure details
before the native Python wrapper replaces the exception, and log successful
binding and completion of population separately.

The updated fixture contains all public data-member names and types from the
pinned native TrainingRoom, with the movie hash. Tests now execute a strict
script-binding boundary before _populate, reproduce failure with the exact
old owner attribute, and pass after removing the collision. They also check
that the new view has no matching attribute for any authored control, retain
permission and delayed-callback checks, and verify raw error logging. Previous
fixtures skipped this binding boundary and could not detect this regression.
Successful contract tests are not a claim of a new live Windows acceptance.
