# Authored route tasks and editor connections

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
