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
