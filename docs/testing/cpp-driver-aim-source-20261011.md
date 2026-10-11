# Current-release driver aiming migration, source checkpoint

The user requested source-only incremental migration while unavailable for game
acceptance. No launcher/mod package is generated for this checkpoint. The
tracked shipping extension intentionally remains the last accepted binary;
rebuild it from the current sources before the next package. An older extension
without `driver_aim` retains the current Python reference policy.

## Scope

`driver_aim` moves four numeric policies into an engine-free C++ frontier:
limited-traverse combat hull laying, retained-side turret target selection,
yaw/pitch alignment, and barrel direction. It preserves the existing recovery
owners, withdrawal exceptions, +/-pi seam, exact comparisons and default
tolerances. It does not enable the older persistent navigation or driver owner,
change the production weapon alignment gate, or retain Python objects.

## Evidence

- Actual 32-bit CPython 2.7 host extension: 29,544 exact comparisons with the
  current reference laws, including fixed/asymmetric traverse, interval edges,
  recovery modes, rear-side retention, and exact alignment thresholds. Supported
  calls assert native admission; invalid inputs reject without Python conversion.
- Related engine-free regression tests: 258 passing tests in 14 files.
- Previous driver sweep frontier: 12,000 exact comparisons remain passing.
- All 179 client sources compile with CPython 2.7.18.
- Host and exact-client x86 extension sources compile with strict floating-point
  flags. Both binaries were produced only in scratch, not installed or shipped.

Scalar frontier benchmarks are small and mixed: on this host the rear hull
decision was approximately 1.62/1.44 microseconds reference/native, alignment
0.77/0.55, barrel direction 0.57/0.53, and the short turret clamp 0.21/0.48.
An isolated very small clamp pays more frontier overhead than it saves; future
weapon/frontier consolidation should fuse it with the enclosing aim operation.
These measurements are not evidence of a whole-game latency improvement.

## Latest accepted package report

Report `wot-error-report-20261011-141309-c03573482f0f.zip` contains build
`colorfulmeans-38116363251-1`, preceding this source checkpoint. All 106 Bot
shots have aligned admission and first-tracer muzzle ordering, without new
exception stacks. Player launch/display samples are 3/10-11 ms (four shots).
Bot publish-to-display median/p95/max is 235/612/896 ms across the full round;
71 shots after 14:09:47, during steady client callback windows, measure
226/278/295 ms. Earlier windows explicitly record minimized/restore pauses.
The later subset is not a controlled code comparison and has fewer live Bots.

Busy worker windows still cost roughly 112-122 ms on average. Busy trace stage
median self times include world motion 21.12 ms, Bot motion planning 7.88 ms,
Bot physics 7.09 ms, destructible body scanning 6.54 ms and ground motion
5.95 ms. These independent stage medians must not be summed into a frame cost.
The resisted-hit cosmetic event for projectile `1:b:19:7` sees current HP zero
after its earlier event HP 138; this cosmetic path explicitly skips durable HP
and killer mutation. This is not evidence of duplicate damage or resurrection.

## Next migration targets

Continue complete computation units in local planning/recovery, destructible
candidate preparation, and projectile lifecycle/settlement. Keep current
0.10.0 behavior as the oracle. Profile engine queries and waiting separately:
an existing C++ engine query does not get faster simply by moving its Python
caller. Actual gameplay and latency acceptance remain pending until the user
returns. Known unrelated baseline CI failures remain outside this checkpoint.

## Pitch-curve continuation

Opcode 4 extends the same synchronous aiming frontier with both yaw-dependent
pitch curves as one computation unit: fresh numeric node copies, per-operation
float32 rounding, binary interval search and the original weighted interpolation.
The Python adapter retains yaw validation/wrapping, descriptor lookup and the
unchanged reference/error path. No curve cache, sorting, absolute-envelope
fallback, targeting rule or existing aiming opcode is changed. Plain list/tuple
curves with plain list/tuple numeric nodes are admitted; unsupported sequences
or numeric objects are rejected without invoking their Python conversion or
iteration. Their original reference behavior remains available.

Local continuation evidence uses CPython 3.13.5 and a scratch CPython-3 adapter
compiling the exact production C++ include, not the complete CPython-2.7/x86
extension. GCC and Clang, each with `-O2 -fno-fast-math -ffp-contract=off`, pass
7,536 bit-exact curve comparisons, including negative angles, independent node
grids, adjacent float32 knots, signed zero, subnormals and changing input nodes.
Malformed/collapsed nodes retain the reference ValueError; generator fallback is
not consumed twice. The seven unchanged gun-pitch oracle tests pass with both
the reference and native-backed adapter (805 native admissions). Another 10,000
old/new comparisons preserve opcodes 0-3 exactly; input reference counts stay
unchanged over 10,000 new calls.

`tools/check_native_gun_pitch_limits.py` is also called by the existing native
aiming conformance check, so that job exercises the real CPython-2.7 bridge on
its next run. Exact-target compilation, native descriptor admission and Windows
gameplay/performance are not established by the local host adapter. No shipping
binary, launcher/mod package, release, map or Bot behavior is changed here.

## Traffic braking continuation

The next source-only batch migrates the current traffic guard's complete
neighbour filtering/candidate loop and its ordered predictive-braking loop.
`driver_geometry` opcode 3 copies fresh plain rows, retains friendly/live and
pitch/roll-projected height admission, and returns ordered peer/candidate
indices. Opcode 4 retains the exact stopping-distance sweep, current-contact
SAT normal, tangent/departing exception, relative-velocity interval prediction
and first-blocker order. No body dimensions, stopping coefficients, traffic
lease, parked-yield state, recovery deadline or physical contact law changes.

The phases deliberately surround the existing lazy Python stopping-distance
callback. It still runs at most once, only when the original guard requires
it. The second phase reads current body/candidate dictionaries after that
callback while retaining the original pre-callback position and travel axis;
there is no stale cross-phase pose cache. Rotation admission and order/clearance
bookkeeping remain in the existing Python owner. Replaced reference laws and
unsupported native inputs use the local reference phase, never a replay of the
stopping callback. Both C++ phases retain no Python objects or engine handles.
`traffic_roster_native/reference` and `traffic_blocker_native/reference` counters
identify admission in detailed worker diagnostics.

Local evidence for this batch is CPython 3.13.5 with a scratch bridge compiling
the exact production driver/traffic includes. GCC 14.2 and Clang 17 both compile
with `-O2 -std=c++14 -fno-fast-math -ffp-contract=off`. Each passes 6,163 roster
comparisons, 6,162 ordered-blocker comparisons and 508 full-control comparisons
(12,833 total); supported phases assert native admission. Cases include mutable
30-peer rosters, missing heights/shapes, slope/bridge separation, gear/contact
boundaries, unchanged caller data, unsupported-object traps, iterator fallback,
live numeric tuning and callback mutation/failure without duplicate invocation.
Unchanged rotation/escape callbacks are controlled fakes in this scratch harness;
SAT and vertical-interval reference arithmetic are exact prior-source copies.

A separate comparison against the complete, unmodified previous traffic source
passes 3,000 full-control cases, including callback traces and all coordinator
ledgers. Every other TrafficCoordinator method has an unchanged AST. Another
15,000 baseline/new C++ comparisons preserve driver_geometry opcodes 0-2.
The new checker is invoked from `tools/check_native_driver_geometry.py`, which
will exercise the production CPython 2.7 bridge when run with a rebuilt host
extension; that complete build/test run was not available in this environment.

Isolated complete-safe_controls medians with 29 neighbours (seven samples of
1,000 calls, a constant stopping-distance callback and no rotation request):

| Scene | Previous Python ms | Native-backed ms | Ratio |
| --- | ---: | ---: | ---: |
| Distant neighbours | 0.05721 | 0.01695 | 3.38x |
| Nearby but clear lanes | 0.18217 | 0.03004 | 6.06x |
| First candidate blocks | 0.06488 | 0.02158 | 3.01x |

These are scratch component measurements, including the new Python wrappers and
C++ boundary, not a whole-worker, embedded-client or ping improvement. The
scratch CPython 3 dictionary gate is not the production CPython 2.7 ABI. Exact
x86 extension compilation, the full real-module regression suite, packaged
admission and Windows gameplay/frame timing remain unverified for this batch.
The shipping extension, launcher/mod package, update cadence, worker count and
threading architecture are unchanged. The rest of the current driving/traffic
state machines remain migration targets; this does not enable the older native
behavior owners or claim their complete replacement.

## Native friendly-crossing continuation

The next source-only batch moves the remaining current traffic-pair numeric
pipeline to the same synchronous `driver_geometry` frontier. Opcode 5 handles
complete pair meeting classification (head-on/yield/none), both actual travel
axes, relative moving-OBB interval overlap, the crossing intersection,
arrival-order priority including held-vehicle pace, and the exact lease
parameters. Opcode 6 tests the current lease's exit geometry. Opcode 7
computes the current SAT clearance gap between hulls. Opcode 8 filters the
`TrafficCoordinator.adjust` roster in original order, including team,
life and pitched/rolled vertical-body overlap. Python retains only the
current lease/order/parked-yield state, callback dispatch and output mappings.

Every native operation receives fresh borrowed numeric rows and retains no
Python/BigWorld objects. Static world/engine probes, the separate final vehicle
rotation admission, physical momentum/contact, stationary-yield deadlines and
Bot strategy remain unchanged. An unsupported input or a monkeypatched source
law stays on the original Python reference path. The old persistent native
traffic/driver owner remains disabled; this is a port of the 0.10.0 rules, not
installation of that older state machine. All control cadences, worker counts,
network transport and the shipping extension remain unchanged.

In local CPython 3.13 scratch host tests, GCC and Clang compiled the identical
new production C++ include with `-std=c++14 -O2 -fno-fast-math
-ffp-contract=off`. Each passed 12,000 random pair decisions, 12,000 SAT
gaps, 6,000 changing 30-peer adjust rosters, 2,320 lease clearance decisions
and 50 80-tick complete `TrafficCoordinator.adjust()` history comparisons
against the previous rules. Float distances are compared at 1e-12 tolerance,
while branch outcomes, actor IDs, event/lease states and callback traces match
exactly; some computed clear-after thresholds vary below 1e-15 between libm
implementations. An independent production-entry conformance script covers
2,209 pair decisions, 524 lease clearances, 4,400 SAT gaps, 1,000 rosters,
mutable runtime thresholds, custom-type rejection and missing-binary fallback.
The new checker is called by the established CPython 2.7 driver-geometry check.

Seven-sample median complete `adjust()` microbenchmarks (29 peer rows,
1,500 calls per sample, no arbitrary engine collision query) show:

| Scenario | Previous Python (ms) | Native-backed (ms) | Ratio |
| --- | ---: | ---: | ---: |
| Distant same-team peers | 0.14567 | 0.06611 | 2.20x |
| Mixed nearby peers | 0.13374 | 0.06968 | 1.92x |
| Nearby opposing traffic headings | 0.12406 | 0.07665 | 1.62x |

Those host component figures include the Python frontiers, but are not
whole-worker or game-latency evidence. The scratch host used controlled
engine/driver callbacks and CPython 3 dictionary-layout equivalents, not
#1513's CPython 2.7/x86 runtime. Actual x86 extension compile, real-module
CI, packaged native admission and Windows gameplay/frame-time acceptance are
pending. No launcher, `.wotmod`, binary, tag or release was updated.

## Current-release projectile chord and moving-target continuation

This source-only batch adds a `projectile_math` entry point to the exact-client
native extension, with new timing diagnostics and method admission counters.
Opcode 0 handles the complete numeric flight-chord preparation from frozen
start/velocity/gravity and the current distance cursor: two absolute-time
trajectories, three-axis segment distance, remaining-range clipping, endpoint
interpolation, and the constrained callback timestamp. One operation replaces
the previous multi-call Python math in `InFlightProjectiles._advance_one`.
Substep boundaries, global chord budget, real collision callbacks, impact and
terminal ordering, cursor commits, cancellation and owner identity remain
unchanged. Opcode 1 performs the complete relative-motion projection of a
moving target's current collision-frame chord in one operation.

Both operations borrow only plain numeric tuples/lists, retain no Python
objects, and reject custom numeric types, nonfinite input and unsupported
shapes without invoking Python conversion callbacks. Unsupported inputs and
older binaries use the original precise Python reference laws. The adapter
avoids bypassing patched `trajectory_position` or `lerp3` implementations.
The old `projectile_runtime` position, range and curvature helpers remain as
public reference interfaces for other clients and the manager's takeover path.
No original #1513 engine callback ownership is moved across threads.

Local scratch bridge validation uses the exact production C++ include compiled
with GCC 14.2 and Clang 17, `-std=c++17 -O2 -fno-fast-math -ffp-contract=off`.
Both pass 40,000 bit-for-bit prepared-chord comparisons, 40,000 moving-target
projection comparisons, 5,000 mutable-input comparisons and malformed-input
rejection tests. A separate production-host conformance checker
`tools/check_native_projectile_math.py` is wired into the native driver
geometry test runner; its 15,000 paired-operation and manager lifecycle checks
still require actual CPython 2.7 host execution.

A scratch host microbenchmark of the entire Python adapter boundary, using one
frozen chord and one moving-target pair, records roughly 1.319 to 0.401
microseconds (3.29x) for a full chord and 1.182 to 0.320 microseconds (3.70x)
for moving-target compensation. The scratch bridge is CPython 3.13 and does
not reproduce the embedded CPython 2.7/x86 dictionary or DLL ABI. The values
are component observations, **not** whole-worker, in-game latency or visible
projectile timing measurements.

Exact #1513 Win32 extension packaging, real-manager conformance on the pinned
Python 2.7 runtime, package inspection and Windows gameplay acceptance remain
outstanding. No shipped binary, release, gameplay law, physics constant,
collision filter, control cadence, callback budget or worker architecture has
been changed.

## Projectile spatial and ricochet continuation

The next source-only checkpoint extends the *current* 0.10.0 projectile
calculation frontiers. The existing native `projectile_math` opcodes 0 and 1
continue to own whole flight-chord preparation and moving-target relative
projection. A separate synchronous `projectile_spatial` frontier now ports
six remaining Python numeric laws without installing an old projectile owner:

- Squared distance from a point to the actual finite projectile segment.
- Conservative expanded-segment AABB candidate admission.
- Ideal reflected velocity, including the original degenerate-normal behavior.
- The actual 2 mm plate-normal ricochet departure origin.
- Parabolic chord-error estimation.
- Gravity-dependent maximum curvature substep selection.

The original formulas, comparisons, epsilon boundaries, return shapes and
ordered CPython 2.7 floating arithmetic are retained. Ricochet normal length
still follows `float(value) ** 2` rather than replacing it with an
algebraically equivalent dot product; the native shipping build already
disables compiler fast-math and pow substitution. Invalid reflected normals
use an explicit integer-zero success sentinel, distinct from `None` meaning
native rejection. A collapsed departure normal falls back to the original
Python ValueError. Invalid inputs never trigger Python coercion/iteration
inside the C++ parser; the existing reference Python law handles the
unsupported case. The C++ operation holds no Python object, engine handle,
shot identity or state across calls.

The visible/worker clients still own real hit-tester/BigWorld queries,
projectile callbacks, frozen launches, canonical hit and damage settlement,
all collision filters, and the original generator substep boundaries.
No physics coefficient or update budget changed. The older shipping `.pyd`
that lacks `projectile_spatial` still follows the original reference Python
calculations. New per-method admission diagnostics distinguish native and
fallback paths.

Scratch GCC and Clang `-O2 -std=c++17 -fno-fast-math -ffp-contract=off
-fno-builtin-pow` CPython 3.13 bridges each passed 16,000 randomized
comparisons for segment distance, AABB and reflection, 15,600 for departure,
and 13,000 each for chord error and curvature (89,600 total per compiler).
The tests also cover signed zero, subnormals, shared endpoints, invalid
normal lengths, boundary radii, changed input lists, hostile converters,
one-shot Python fallback, and native object/reference ownership. To match
the supported embedded CPython 2.7 semantics, scratch Python 3.13's newer
compensated `sum()` behavior is replaced in the isolated oracle by the
2.7-style left-to-right sum; no game code changes that built-in. A native
parity checker with 5,000 cases per primitive and explicit native admission
is wired into the existing native driver test entrypoint.

Component-only CPython 3.13 host medians (GCC; complete public Python
function with native dispatch) were 0.513/0.260 us for point-segment
distance (1.97x), 0.708/0.323 us for expanded AABB (2.19x),
3.269/0.342 us for ideal reflection (9.56x), 1.789/0.374 us
for ricochet origin (4.79x), 0.504/0.256 us for chord error (1.97x),
and 0.622/0.252 us for curvature (2.47x). These are neither
whole-hidden-worker figures nor embedded-client latency measurements.

The final production CPython 2.7/Win32 extension, ABI import audit,
complete client regression suite, in-game #1513 parity and Windows
frame-time measurement remain unverified for this source-only batch.
No binary, mod, launcher, CI workflow, release, worker count or threading
configuration is changed here.
