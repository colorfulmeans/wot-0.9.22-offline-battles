# Support-path reset to 2026-09-24

The user rejected the accumulated bridge-support fixes and requested a direct
return to yesterday's support path before starting again. This is a rollback
checkpoint, not a claim that the bridge or cliff defect is fixed.

Baseline: `a5401f87359ac916f6fcedc31aa09d25bf226dd8`, committed
2026-09-24 23:29:24 +08:00. The unpushed r6 rewrite was withdrawn separately
and is not part of this checkpoint.

## Restoration

- `vehicle_physics.py` and `world_collision.py` match the baseline byte for byte.
- The player's three suspension sample/integration methods and the Bot's
  corresponding methods, probe-height prediction, terrain support, vertical
  integration and wreck response match the baseline exactly.
- `tank_collision.straddled_support` matches the baseline. The new wreck-fall
  entry points, COM/origin correction, footprint cache, corner sweep callback,
  bridge support-departure rules and their new diagnostic dependencies are removed.
- HE, ammunition order, missions, editor/localization and tank-to-tank mass
  response remain. Bot routing, obstacle decisions and avoidance remain frozen.

The support implementation is a separate commit from the matching test/build
rollback so that its restoration can be inspected directly. Tests introduced
solely for withdrawn support implementations are withdrawn with them; existing
baseline assertions are not weakened. Their historical versions remain in Git.

## Known behavior after rollback

The yesterday solver does not produce `impact_track_loads`. Ordinary landing
observations still apply hull HP loss, but no longer enter the newer crew/track
critical-damage path. Healthy-seat selection and protocol compatibility code
remain, but are not a functioning landing-damage fix without real contact data.
Internal-module falling damage is still unimplemented.

The bridge/cliff problem remains unverified and may still occur. No Windows
native gameplay acceptance has been performed for this checkpoint.

## Investigation restarted from the restored source

The restored solver integrates a world-Y gravity term, `-mass * GRAVITY`.
That statement alone does not establish correct falling behavior: its contact
input contains scalar heights, not full world contact points and normals.
Spring forces act in +Y and `_project_suspension_limits` directly changes
height, pitch and roll to satisfy those height constraints. The final height
correction can therefore overwrite the falling motion. The restored model also
uses the vehicle model origin instead of a physical mass-center state.

The r5 report `wot-error-report-20260925-140919-344e9128def6.zip` demonstrates
why another collision exception is insufficient. At visible-client.log line
798, 14:08:31.582, released controls and clear world motion accompany five
right-side spring heights 0.282--0.403 m above their posed points. The reported
mass center rises 0.13746 m in 0.00899 s. This is a support correction, not
world gravity. The record does not distinguish direct, footprint and remembered
samples, so it does not prove which sampling substage supplied each height.

A subsequent fix must replace the incorrect contact representation and its
ability to manufacture support. It must demonstrate world-vertical free fall
with no contact, unilateral contact response at actual geometry, and release
at a finite bridge edge. Restoring the withdrawn r6 implementation or adding
another layer of bridge-specific exceptions is not part of this checkpoint.

## Verification at this checkpoint

The five changed production files parse successfully. The decision-freeze
audit passes: 16 frozen files and 353 Bot function definitions checked. Exact
module/method comparison confirms the restoration boundary above.

Focused retained regressions: 241 tests, 239 pass and two fail. Both failures
are independently reproduced with unchanged tests on a Git archive of
`a5401f87`:

- `RolloverBridgeTests.test_overturned_bot_uses_roof_support_without_track_spring_propulsion`: roof height 2.5402083333 versus required minimum 2.775.
- `BotRuntimeTests.test_bot_bridges_a_slot_running_along_its_hull`: actual 10.0 versus expected 9.975.

Both tests and their assertions remain active in the build gate. This
checkpoint is not presented as a passing repair or a validated Windows package.
