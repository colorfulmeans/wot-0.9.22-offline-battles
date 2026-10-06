# Navigation lifecycle repair

## Runtime evidence

The 20261006-014225 report came from test build 107. At 01:41:16, Bot 22
(E50M) was at `(213.906570, 13.225835, -69.015067)` and its supported target
was `(214, 14.84, -62)`. Parking occupancy included nearby moving Bot 21
(Bat25tAP), so travel avoidance replaced that target with a point less than
one metre behind the E50M. The adapter then treated the underfoot target as
a pending path and stopped. Replaying the reported hulls against the exact
El Hallouf graph reproduces this target rewrite.

Ordinary moving peers now remain local traffic/contact obstacles without
becoming parking blockers for a route corner. Players, wrecks and authored
parked hulls still block occupied destinations. Actual motion retains hull
sweeps; a temporary bypass inside the arrival radius is never issued.

## Restored behavior

- A driver-owned pending-path wait applies the brake, preserves failure leases,
  and allows one bounded, checked rear translation after local obstruction
  evidence. Completion requests a private replan exactly once.
- Frame-owned navigation ticking advances admitted searches without requiring
  another target request. Frame and target calls share the existing expansion
  credit; catch-up does not create another budget.
- Hard contact reports identify stable navigation intent and realised heading.
  Expired failures retire their local replan state. New wreck revisions veto
  both shared paths and previously selected private joins.
- Deferred native proof does not become a cached wall. A selected pending
  prefix keeps its issued leg until arrival; canceled jobs cannot publish old
  paths over their replacements.
- Temporary exits retain fixed endpoints and macro progress across small pose
  changes. A forward translation escape continues only while its proved hull
  sweep and finite distance/time lease remain valid.
- Missing baked support can use a live join at most 24 metres long. Continuous
  centre and two shoulder support, physical grade, map bounds, water and static
  collision must all pass. Supported route corners cannot use this mechanism
  to bypass missing cardinal links. No global graph cells are fabricated.
- Wait/search diagnostics read cached job and cell state without world queries.

## Verification and boundaries

The final local selection executes 1,277 checks without failures, errors or
skips, including Python 2.7/3 codec parity. All 161 client sources compile
under CPython 2.7.18. The restored navigation, driver, pending-prefix, live
egress and runtime-report suites are included in Bot behavior CI.

Older fixtures required repairs as well: native parking/route collision must
use the same geometry as driver probes; passive probes are not actual contact;
a rebaked map need not select an old A* bend or rear bearing. The historical
fjord bend remains an explicit authored path against current baked heights.
Artillery radio authorization remains separate from controller-owned launch
proof; target selection tests now exercise that reviewed contract.

Controlled support/collision replies prove admission and lifecycle logic, not
native BSP geometry. Real #1513 Windows gameplay must still verify the reported
vehicles, collision clearance, slope descent and frame pacing. Physics support
coefficients and authored user routes are unchanged. Live joins add bounded
native proof only for local missing-support exits and already issued local
targets; this is not a claim of zero additional terrain queries.

## Test108 repeated local target replacement

Report `033050-3c56a774c2a4` identifies installed and bundled build
`colorfulmeans-37360095958-1`. Panther 8.8 and M60 still change short local
targets while attempting the same authored medium-tank lane. Test108 did not
resolve this class of steering ownership failure. Its fixed-endpoint helper
was reached only from fallback selection; ready paths and runtime lane/bypass
transforms could replace the endpoint before that helper ran.

An issued local leg now precedes ready-path admission and the short direct
shortcut. Pending prefixes and the final runtime-transformed destination use
the same ownership record. Lane offsets apply once; an occupied gate keeps a
fixed candidate across occupancy refreshes, with fresh body/corridor checks.
A consumed short leg remains the next fallback's fixed origin. New commands,
stops, arrival, passed endpoints, proved unsafe geometry and private penalties
still retire ownership.

The existing 12-second no-progress budget applies to the local leg. Only at
least 0.2 m closer travel or improved alignment toward its fixed heading can
renew it; source changes and heading oscillation cannot. A timed-out endpoint
is suppressed privately for 12 seconds, including ready-path and direct
admission, without changing shared terrain. Deferred native proof pauses the
vehicle and retains the endpoint rather than caching a wall or yielding it to
another path. Cached diagnostics expose the current endpoint, progress age and
unsafe/timeout termination receipt.

Two new behavioral regressions fail against unchanged test108 source: ready
paths steal an unfinished exit, and runtime lane translation repeats on every
decision. Additional checks cover completion of a real incremental search,
arrival continuation, direct shortcuts, stop/new-order retirement, new
obstacles, fixed occupied-gate candidates, useful slow alignment, oscillation,
private timeout expiry and deferred native proof. The selected Bot CI checks
and all 161 Python 2.7 source compilations pass locally. This is controlled
lifecycle validation; the report's native BSP collision and mutual-contact
episode still require #1513 Windows playtesting.


## Test110 failed retry and deferred proof audit

Private route retries now start at the realised vehicle position; shared
route geometry retains its authored anchor. An unselected pending tree far
behind the hull cannot become a return order. Deferred collision evidence
pauses the existing path without changing its index or issued endpoint.
Replanning retires the owner's stalled marker, temporary visit history and
completed local origin, while retaining unrelated searches and real contact
vetoes. Partial cached paths expire after eight seconds so a completed retry
can replace them.

A near corner remains required until arrival or a proved passed connector.
Short straight escapes retain one direction for their checked distance, with
a four-second deadline and fresh obstacle vetoes, rather than selecting front
and rear anew every decision. The six Panther II/M36/SU-122-44 dead-end cases
at 5 and 15 FPS pass with full hull collision checks and unchanged 120-second
arrival assertions. Their fixtures now use the production search budget and
actual issued local sweep lengths rather than inconsistent inflated rays.

Planning interfaces accept the shared static soft-object policy explicitly.
Unsupported per-vehicle kinetic planning policies are rejected with a clear
ValueError; this does not restore the retired policy of making crushable props
hard route obstacles for some vehicles. Callback arities are inspected before
calling them, so a TypeError in a callback body cannot duplicate a native call.
Mounted forward/reverse numeric snapshots are refreshed on descriptor changes
and battle manifests. Same-map new rounds invalidate old paths and native
receipts. Diagnostics retain bounded search origin, goal, refusal and step
records; invalidation and cache trimming remove their receipts too.

Report 120135 on build109 exposed a second failure: an unproved fallback to
the current pose was labelled safe and the driver reported arrival forever.
It is now pending and enters the adapter's existing bounded navigation wait.
A rejected connector also retires the completed origin before the next retry.
This covers the M46/T34-3 pause mechanism; native mountain clearance for the
reported WZ-111G still requires testing in the exact Windows collision scene.

The final Bot selection includes the previously omitted retry/replan/motion
and callback wiring suites. All 1,323 selected checks pass locally. The
historical full repository suite is not claimed green: obsolete vehicle-scoped
planning fixtures are distinct from the current shared-policy contract.
Packaging separately checks exact source and compiled Python 2.7 payloads.


## SPG firing-position relocation

Report 133914 (test110) showed team1 T92 remaining at its authored position
without firing. Native exact-launch receipts hit remote terrain; targets and
proofs continued changing, so this was not the old frozen-intent defect.
Completed unusable lanes previously did not trigger authored-position retry.

An arrived SPG now records ready time after completed world-blocked/no-candidate
proofs. At least two independent terminal proofs and 30 seconds of ready time
are required; polling the same cached refusal cannot count as multiple attempts.
Pending work alone, reload, missing radio permission and absent targets cannot
start a relocation. After confirmed failures, intervening queued proofs retain
the position episode rather than resetting its clock. A current conclusive
failure is still required at selection. An exact clear launch receipt, an actual
shot, displacement, a different position or expired evidence retires it.

Retry prefers a safe, reachable and unoccupied point inside the current zone,
then another configured zone using existing priority and footprint rules. The
current failed area is excluded for 120 seconds, with at most eight remembered
positions and one selection per 45 seconds. Deployment retries respect those
exclusions. No alternate leaves the SPG holding and able to try ordinary firing;
no arbitrary position or route is invented. A relocation finishes before new
launch intent is admitted, then resumes normal target/fire gates at arrival.
Base-defense orders still preempt it. The ballistic ray budget and collision
checks are unchanged; selection uses existing graph data only at bounded retry
cadence. Cached gate diagnostics include failure time, independent proof count,
retry cooldown and same-zone/other-zone/no-alternate outcomes.

Controlled tests cover same-zone and cross-zone retry, occupied/no available
parking, cooldown, arrival/resumption, repeated failure through pending work,
single random failure, stale-target evidence, reload/radio/target gates and base
defense. Replaying the captured T92 proof/gate sequence now reaches the retry
condition; this does not prove the alternate site's native firing clearance.


## Test112 repeated relocation with stale server deployment mode

Report 153208 proves test111's team1 T92 moved once at 15:27:28, reached its
adopted point, then accumulated over 109 seconds of ready failure without a
second move or shot. The worker's decision was artillery_hold at the new point;
the server still ordered artillery_deploy toward the original manifest anchor.
The retry hook required the server's hold mode, so it stopped observing eligible
relocation requests after the first worker-owned move.

Retry now uses the recent locally arrived failure episode under either ordinary
SPG hold/deployment order. It still requires current target/fire permission,
matching position-plan identity and fire sequence, an unchanged ground pose,
two independent proofs, the existing ready-time threshold and cooldown. Shoves,
airborne/overturned hulls, actual shots and non-artillery defense orders cannot
reuse the old failure episode. No firing, ray-budget, parking geometry, priority
or authored coordinate policy is changed. A regression issues the old server
anchor after a successful first relocation and verifies a second deployment
with firing paused, rather than merely calling the retry helper in isolation.
The old source fails that regression; the corrected source passes.


## Test113 dispersed SPG first-impact admission

Report 155012 on test112 shows Conqueror GC changing firing positions normally
and firing twice at short range, while distant nominal lanes become clear then
fail exact dispersed launch proof. A random path's early world impact was
rejected unless its last chord landed within seven metres of its sampled
terminal. That refusal could also reject the entire nominal low family, leaving
no candidate for a gun whose high root exceeds its real elevation limits.

The exact-launch queue can now finish at a finite world impact more than 25 m
from the muzzle when the hit lies on the actual checked chord. All earlier
chords must be proved first. The immutable receipt retains muzzle, velocity,
random angles, flight time, sequence, shell and full binding key; only the
internal checked/friendly path ends at that first hit. Friendly body and HE
splash checks therefore use the real landing point. The ordinary projectile
simulation still performs collision and produces impact, explosion and damage;
the admission receipt never fabricates a hit or bypasses scenery.

Nominal family planning retains its complete obstruction proof. Muzzle-side
hits, opaque/False replies (including retained-wreck vetoes), query exceptions,
nonfinite points and off-chord replies cannot become remote-impact receipts.
No ray quota, gun limit, random sample or projectile law is relaxed. Cached
launch diagnostics expose the recorded terminal impact. Near-wall lifecycle
fixtures now place their blocker about 5 m away rather than at the end of a
50 m first chord, preserving the intended near-obstruction contract.

New regressions prove original random-angle runtime firing, first-hit path
truncation, pinned receipt reuse, unchanged nominal-family admission and the
remaining muzzle/unknown/malformed checks. Existing exact friendly-body/splash
and projectile terminal tests remain mandatory. Native #1513 landing effects
and GC gameplay still require testing with the new package.


## Test114 bounded reverse ownership and completed snapshot slew

Report 172035 uses test113. Team2 Object268 repeatedly returns a zero-input
blocked withdrawal near (97.5, -34.5), despite clear realised-motion reports
and no nearby hulls. Its local driver clock scarcely advances while macro
replans accumulate. Team2 Waffentrager E100 P also enters this branch during
withdrawal, then fires and reaches its low-health retreat hold. The reverse
adapter returns before LocalDriver.drive, so rear-sweep/pose refusals bypass
the driver's translation timeout indefinitely. This is not an authored wait.

The adapter now owns a bounded reverse progress episode. Eight seconds without
actual translation, including continuous rear denial, hands the order to the
normal safety-checked driver. The fallback remains latched until two metres
of progress toward the withdrawal destination or a changed destination/ended withdrawal; a transient rear-clear
reply cannot steal recovery control back. Normal successful backing resets
the progress clock. Forget and explicit hold clean up the episode. No terrain
probe, physics, graph or collision veto is relaxed.

The firing gate previously admitted 0.06 rad traverse and 0.04 rad elevation
error. At 400 m those separate centre-line errors can exceed 24 m and 16 m.
Runtime now requires the slew to reach its raw requested local angles to
numerical precision before applying existing gunner reaction/laying and
dynamic dispersion rules. A snapshot can still fire before fully shrinking
the aiming circle; gun limits, difficulty bias, dispersion, friendly safety
and automatic burst continuation retain their owners. Controlled checks cover
separate yaw/pitch arrival and all four retreat modes with denial, no physical
progress, progress reset and fallback latching. Native gameplay acceptance
requires the next test package.


## Test115 blocked approach to optional waiting places

Report 175026 on test114 shows team2 T110E4 near wreck17 while travelling
to a small waiting place about 100 m away. Recovery count rises from 12 to
19 near the wreck before the round ends. Both worker static-hull evidence
and the server's bounded gate attempt excluded parking_approach, so the
ordinary timeout could not retire this optional destination.

Worker parking approaches now publish the existing cached static-hull lane
evidence. The server admits this phase to the existing 20-second attempt
budget. Expiry releases the small-place lease and permanently declines that
wait for the current gate, then uses its ordinary parent travel point. This
also handles a wait at the final gate. If the parent remains blocked, the
existing bounded skip-successor/change-route sequence applies. Resumed travel
clears stale parking phase, slot and one-metre arrival metadata. Arrived waits
remain excluded and retain normal timers and attack behavior. No parking
coordinates, physics, collision vetoes or search budgets change.

Controlled checks exercise worker evidence, approaching/arrived separation,
lease release, parent fallback without reacquisition and subsequent parent
timeout. The capture's independent performance hotspot remains motion/world
collision and repeated ground/destructible work; this patch does not claim
to solve that separate performance problem. Native wreck clearance still
requires testing the next package.
