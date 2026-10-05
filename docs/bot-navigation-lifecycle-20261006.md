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
