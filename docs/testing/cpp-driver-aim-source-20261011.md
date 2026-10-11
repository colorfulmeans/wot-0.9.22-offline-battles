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
