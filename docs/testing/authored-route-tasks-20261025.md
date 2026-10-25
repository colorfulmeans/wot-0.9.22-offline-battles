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
import and map undo preserve or remove stable references. All-classes branch edits
rebind to each class's actual matching ordinary node, even when its index differs.
A missing/ambiguous matching junction rejects the edit atomically rather than
silently attaching a different road. Tier edits do not overwrite independent
class defense branches.

SPG parking has optional red solid base-to-parking and parking-to-parking
connections, editable in the same connection panel. A reciprocal relocation can
reverse the existing link. New parking creates its base connection. Red dashed
SPG attack routes have fixed own/enemy base ends and are separate from parking.
Up to three endgame SPGs first return along their connection to base, then follow
the authored sortie. Defense during a sortie reverses its already passed nodes;
defense retains the actual interrupted task/parking and returns there afterward.
Existing unconfigured parking retains its prior automatic path until an authored
connection is supplied. These new two-point outlines require map authoring;
they do not claim to have authored bridge detours automatically.

Missing deployment, relocation, defense and sortie connections each retain the
existing automatic destination for that purpose. A missing relocation link does
not invent a connection through base. A missing sortie cannot retain a cached
deployment. Present authored connections retain their points when join proof is
unavailable and continue through the existing physical checks and retries.

Optional schema-1 fields are `tier`, `family`, `node_ids`, `defense`, route
`purpose=spg_attack`, and parking `travel`/`links`. Exact map resource identities,
endpoint ownership and bounds remain checked. Packaging includes the new client
modules, server task owner, launcher connection editor and the server's zipfile
runtime import.

## Verification and limitations

- `test_port_0922_route_task_rules.py` covers command admission, guard phases,
  task ownership, frozen turnback, circle handoff, pressure commitment/expiry,
  class-family occupancy, directed rejoin, stable junctions and SPG deployment,
  relocation, defense and sortie sequencing.
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
  (Mittengard, Tundra, Ghost Town) are left for the owner's authored defense edits.
- CPython 2.7 compilation and exact packaged bytecode verification cover all
  client sources. Frozen source checks cover the launcher and server payload.
- Engine-free simulations and baked graph timings do not establish native
  Windows physics, live FPS/ping or map gameplay acceptance. Final acceptance
  still requires the diagnostic entrance on the exact CN HD #1513 client.
