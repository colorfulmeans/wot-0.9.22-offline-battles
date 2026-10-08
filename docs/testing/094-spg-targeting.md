# SPG target / muzzle-proof feedback repair

Base: `c675b21611afc20f008b832740cd3f8559319cb9` (PR #34).
Client: Chinese HD 0.9.22.0.1 #1513.

## Report evidence and its limits

The new 11:53 report has matching visible-client, worker and server build
identity `colorfulmeans-v094-mechanics-35949861559-1`; this is not attributed to
an old installation. The rounds are 08_ruinberg at 11:45:36 and 35_steppes at
11:48:25. Motion samples include two SPGs in the first round and six in the
second. In the second round FV3805 (Bot 13) turns toward -1.620 radians at
11:50:05 with hull_aim=True, returns to the same -0.616-radian base direction
at 11:50:23, turns toward -1.629 at 11:50:41, and returns again by 11:51:18.
These are actual sampled motions, not a reconstructed per-shot target trace.

The first-round FV3805 (Bot 30) holds approximately (10, -221) in
artillery_hold/arrived; sampled collision=True does not independently identify
which wall or which trajectory blocked a shot. Movement path_clear=True is
not evidence of an unobstructed firing arc. The old report did not log all SPG
fire gates, so it cannot prove every native missed shot has one cause.

## Earlier-than-final-proof fault

The server required a positive muzzle-dependent artillery lane before selecting
an enemy. Turning the hull invalidates that advisory proof (0.001 radians),
then the generic two-second movement lease expires. The SPG faces its base
again, clears a new proof from that pose and repeats the cycle. The final
launch-latency repair in PR #34 cannot fix a cycle before final launch.

SPGs now track their own received, visible, in-range contacts independently of
that advisory. Other classes retain direct-lane target admission. Unproved SPGs
do not reserve a ready shooter's focus budget. The order fire flag permits a
local attempt, not a shell: the worker still requires the ballistic solution,
actual gun alignment, ammo/reload/critical checks, gunner reaction, selected
lane, full exact native arc and friendly clearance. An advisory expiry cannot
revoke a still-valid selected target's pending exact proof. Lost/dead or
radio-disconnected targets are not admitted.

The regression uses the real BotPlanner, BotAdapter, LocalDriver, BotRuntime
and both ArtilleryController queues. Only descriptors, native geometry and
clock are controlled; no fixed fire_allowed=True or fabricated receipt. The
unmodified server fails with zero shots in 40 seconds; the corrected chain
fires at least twice. A confirmed wall still produces zero launch receipts.
This is an integration test, not gameplay against a native map mesh.

## Close-wall positions and diagnostics

A completed failed proof records its actual sampled hit/chord/arc. Only when
all available arcs are confirmed blocked within 25 m, for at least three
seconds at a stable pose, may a stationary SPG choose another existing rear
route waypoint (16-80 m away, rear 30 percent). Up to three such changes are
allowed. Unknown/pending probes, expired evidence, distant walls and invalid
physics do not trigger relocation. The original navigator, movement collision
and driver perform the move; no teleport or world-collision bypass is added.
Once reached, the new position is retained rather than reverting to the bad
anchor. Base-defense orders take precedence. Missing safe candidates remain
explicitly blocked instead of inventing geometry.

New bounded `SPG FIRE GATE` records capture target, order/local readiness,
reload/ammunition, actual/desired angles, queue state, checked chord counts,
world hit coordinates, final proof/receipt and fire sequence. They use existing
probe results and never issue extra native rays. Serialization failure cannot
cost a shot. These records are needed to confirm remaining native cases.

## Scope and acceptance

Five production files change: server_bot_ai.py, artillery_arc_queue.py,
artillery_controller.py, battle_runtime.py, bot_runtime.py. Original driver,
traffic, adapter, all 41 maps, matchmaking, radio geometry, contact mechanics,
armor, downhill speed, exchange and crew fixes are retained. No save mutation,
main merge, tag or official release. Whole-package replacement is required for
the hidden worker and server as well as the visible client.

Validation: 14 new regressions plus the existing 1,308-case focused runner,
whose one conditional skip and two documented baseline exclusions remain.
Actual Python 2.7 compilation/bytecode comparison, packaged source/asset
identity, Windows launcher tests and server readiness are separate gates.
Native acceptance remains: SPGs engaging stationary/moving received targets on
Steppes, Ruinberg nearby walls and alternate-position behavior, no shooting
through solid cover or friendlies, and removal of targets after radio loss.

## Follow-up: report 20261005-224253, M12 exact-launch failure lifecycle

Build 102's third El Halluf round contains two M12s. Team 1 fired nine times;
team 2 reached its parking position with ammunition and ready fire orders but
never fired. Its gate samples include 93 completed exact-path world failures,
including hits about 504 and 647 metres from the gun. These were reported as
`exact_launch_pending`: the native adapter returned the same `None` for pending
and completed failure, leaving the runtime's frozen nominal aim alive. The
same failed random parabola was repeatedly checked while the target moved.

The adapter now publishes an explicit terminal failure from the existing queue
receipt. The runtime cancels that intent and its stale aim caches immediately,
without spending ammunition, changing reload or advancing the fire sequence.
The next attempt obtains a freshly proved nominal solution. A still-current
world-blocked family is excluded for the existing planning-success cooldown;
another legal family can be proved, or lane admission becomes false so the
existing target planner can select another received contact. Target displacement
over the existing 1.5 m aim-staleness threshold, source pose changes, a fired
sequence, cooldown expiry or round reset clear that exclusion. Pending alternate
planning/launch work and a completed clear alternate keep their family ownership
through the cooldown, so long native queues cannot cause low/high ping-pong.
Timeouts and unresolved probes release the hold without claiming world geometry.

The same deterministic random draw and next fire sequence are retained. There
is no endpoint compensation, random reroll, cover bypass, native-ray budget
increase, cadence change, parking relocation, route/save mutation or slope-pose
change. Gate records distinguish terminal failures from genuine pending work.
The new end-to-end Python regressions exercise both queues, the native adapter
boundary and runtime intent cleanup, including movement, alternate arcs, timeout,
cooldown and reset. Native M12 firing and frame pacing on #1513 remain Windows
acceptance requirements.


## Occupied parking and external displacement

The October 5 23:09 report ran test build 102. WZ-111G repeatedly approached
the same authored waiting place while the player occupied it. T25/2 later
returned and completed its wait; periodic motion records do not capture the
instant of the player's shove. Tortoise fired before taking damage, then lost
its retreat endpoint after the six-second damage memory expired. No native
gameplay acceptance is claimed by the engine-stub tests below.

## Behavior

- Waiting-place admission accounts for current humans, live Bots and wrecks,
  with chassis-derived radii and separate identity domains. An approaching
  hull relinquishes an occupied lease. It uses another free authored slot or
  holds a stable queue pose, retaining normal target and fire permissions.
- The one-metre arrival tolerance only starts the clock. Small displacement
  within two chassis radii, consistent with the admitted terrain grade and
  not airborne, holds the current pose. The original timer runs continuously;
  a larger or unsafe shove requires deployment again without resetting it.
- SPGs check occupancy on the existing one-second tactical cadence. Occupied
  goals retry selection at most once per five seconds, preferring another
  graph-checked location in the same manual zone. If all valid destinations
  are occupied, they hold the current position and recheck after bodies leave.
- An arrived SPG may remain at a displaced pose only inside its manual zone
  or sourced cell, with baked footprint clearance and matching ground height.
  This does not move an authored zone or skip any ballistic/launch checks.
- A committed retreat retains its endpoint through target or recent-hit
  expiry until arrival or the existing no-progress timeout. The existing
  defensive pause then permits route resumption when the local threat ends.
- A short, checked reverse withdrawal can make a small fixed-gun correction
  while keeping reverse throttle. Long travel and recovery retain steering
  ownership; gun traverse, elevation, line-of-fire and reload gates still apply.

## Validation and real-client follow-up

`test_port_0922_parking_displacement` covers occupied/reoccupied waiting
leases, full occupancy and release, chassis size, separate floors, displaced
wait clocks, same-zone SPG reselection, bounded queue checks, supported SPG
displacement, retreat expiry/arrival/pause, and a limited-traverse hull which
actually reverses, aims and fires through the production worker.

On the exact #1513 client, repeat the Grille 15/WZ-111G blocked-wait setup,
push T25/2 after its clock starts, occupy/push an SPG inside and outside its
authored zone, and observe Tortoise under fire. Verify there is no deliberate
player shoving, no timer reset, no six-second route reversal, and continued
normal firing whenever the installed gun can physically bear. No additional
native terrain rays, authored coordinates, saves or suspension settings are
changed by this fix.

The 23:48 report ran build 103. Object 268 v4 had completed its wait and
repeatedly approached a corpse-blocked route corridor before switching lanes.
Only a new best approach or new radial detour territory now renews the stall
clock; revisiting opposite sides of the same obstruction does not. A physical
obstruction close to a travel waypoint no longer disables the fallback timer.
Nearby occupied travel targets receive a bounded, temporary baked-ground bypass
using current chassis footprints. This leaves the authored point and one-metre
wait admission untouched, restores the ordinary goal after the blocker leaves,
and adds no native terrain probes. Regression cases also cover a corpse entering
an already leased wait, all wait slots occupied by corpses, and a vacated slot.
