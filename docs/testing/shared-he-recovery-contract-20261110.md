# Shared loaded-HE and recovery contract, November 10

This follow-up starts from PR119 head `909ac35293c3cf50788f74ecc6fb327868110756`.
The supplied `042532-d29cb4308aa1` report identifies that exact build; the
observed failures are not attributed to the user running an older package.
This document records the approved behavioral contract and reproducible
validation entrances. Final commit, CI, artifact digest and platform results
belong in the updated PR and delivery handoff, not an unverified completion
claim in source documentation.

## Scope and authority

- The user extends protected current HE from magazines to every current HE
  round, including an already started native load. CURRENT fires penetration
  or a legal HE fallback; independently evaluated NEXT chooses the later load.
- Loaded HE does not enter the global eight-second penetration search. Without
  a legal current contact it awaits valid evidence or uses a separately
  justified finite physical recovery; an unavailable HE contact is not a
  reason to launch another penetration-search policy.
- Ordinary HE retains one penetration sample per eligible enemy. The reviewed
  full-domain HE identities are unchanged. Fallback ranking still excludes
  barrel/track-only contacts and accepts a legal zero-damage contact.
- A current non-HE round/clip can load a positively verified alternative once
  its current penetration domain fails. Unknown alternative geometry does not
  authorize unloading a clip. An eight-second movement search requires the
  complete all-enemy, stocked-ammunition negative domain, not just current AP.
- An admitted search keeps its original elapsed clock across evidence refresh,
  roster changes and same-weapon descriptor changes; all shooting evidence is
  still invalidated when its physical scope changes. Movement acceptance, not
  a speculative decision, starts the existing search clock.
- A legal current-HE fallback on one fully reviewed enemy is not vetoed by
  unrelated wall-blocked or unavailable enemies. Those enemies remain unknown
  for NEXT and the global no-penetration certificate.
- When a current full-domain HE review exceeds the existing atomic slice,
  complete enemy point groups receive fair turns. This retains the existing
  48 atomic, two foreground, two background and time budgets; the remaining
  same-slice work can compare the qualified enemy's HE contacts. One unknown
  point still prevents that enemy's fallback qualification. A global domain
  can remain unclosed across many frames when relevant poses keep changing
  and a complete fresh domain cannot fit the existing candidate, time, world
  or armour-query budgets. More than 48 points is one such boundary, not a
  safe/unsafe dividing line; fewer points can exhaust the time budget. The
  dependent eight-second search and NEXT HE fallback are not guaranteed to
  become eligible. Independently proved positive NEXT penetration candidates
  remain usable; current-HE fairness does not solve general global closure.
- A current, fully proved stationary-pose plan can qualify ordinary HE's
  single-point failure for the corresponding physical recovery. It is not
  stored as an actual-pose failure and cannot authorize firing from the old
  pose. Unproved, pending, blocked and stale plans remain ineligible. The
  original hydraulic HE/magazine regression assertions are retained.
- Default route ownership survives hints and incomplete observation. Physical
  line/mechanical recovery is a finite phase of the one shared combat owner;
  it does not restore a second proactive attack-position or pursuit policy.
- Query age alone grants neither motion nor armour failure. Stationary review
  observes alternatives before a known obstruction can request physical
  recovery; explicitly unavailable geometry is not an endless veto against a
  separately observed physical blocker.
- The finite termination contract applies to an admitted physical phase, not
  every unknown geometry query. It is not a guarantee that all waiting or
  native-game stalls have been eliminated.
- A confirmed wreck or landed-turret collision carries a physical-blocker
  receipt instead of a bare false lane result. Foreground envelope candidates
  still require the original native component collision. Exceptions and
  unclassified false results remain unknown; allied wrecks are static
  obstructions, not live cooperative-yield partners.
- Automatic base capture cannot take movement merely because an ongoing
  combat task crosses a base circle. Actual user travel, hold, capture and
  cancellation retain their existing priority.
- The same gun sample's aim intention survives temporary proof renewal, on
  both player and worker bindings. It does not preserve a launch permission.
  Target replacement, death/loss, manual/mission changes, weapon changes and
  owner retirement still clear the retained intention.
- A native front-vehicle refusal records the actual entity, network actor,
  team and pose. The existing candidate review handles it; no new selector or
  permission to shoot through another vehicle is introduced.
- Living enemy hulls participate in driving neighbours, braking and rotation
  sweeps. Cooperative yielding remains allied-only. Python and shipping
  native geometry must use the same roster contract.

No third client, hidden-worker migration, driving/brake timing retune, new
penetration threshold, ammunition identity expansion, damage rule change,
authored-route edit, main merge, tag or release is included.

## Regression evidence and changed legacy assertions

New focused files are `test_shared_loaded_he_policy.py`,
`test_shared_physical_recovery_owner.py`,
`test_shared_native_aim_continuity.py` and
`test_shared_enemy_hull_avoidance.py`, plus
`test_shared_physical_blocker_receipts.py`. They exercise policy and actual consumer
boundaries, with negative controls against the unchanged `909ac352` source.

The native shell setting tests use the real `GunState`,
`BattleRuntime.change_vehicle_setting`, `NEXT_SHELLS`, `CURRENT_SHELLS`,
first-trigger admission, `battle.shoot` and ammunition ledger. The required
observable sequence is HE then AP for single shot, and a completed HE clip
then AP for magazines; merely setting a next-shell field is insufficient.

Legacy assertions are migrated only where superseded by this approval:

1. Unloading current ordinary HE before its first shot is now prohibited.
2. Failing current AP while an alternative has positive evidence must not
   start the global eight-second search.
3. Pending/unknown evidence or a timed wait is not an attack-position order.
4. Physical recovery follows completed applicable stationary review rather
   than a fixture's assumed first callback; bounded completion and real
   movement/ownership/release assertions remain necessary.
5. The old explicit enemy-ignore assertions become full-hull collision
   checks. Exact contact and positive clearance still permit normal driving;
   only real overlap uses the unchanged physical escape law. An admitted hold
   still stops translation and cancels that escape.
6. Fixed-throttle head-on collision fixtures bypass only automatic driving
   decisions, so the new enemy brake does not replace their stated input.
   Actual collision response, mass, engine power, energy, momentum, delay and
   displacement assertions are unchanged.

The original HE damage-ranking assertions remain unchanged. The reported
wreck scenario must demonstrate a real finite recovery, failed-phase release
to its authored route, and four HE shots with three actual reloads and the
correct remaining ammunition after the blocker is removed. Changing its
expectation to indefinite waiting is not an acceptable repair.

The first frozen candidate, `3e2806e8`, passed the local full suite but failed
the worker-handoff setup in CI run `42705392898`. The new physical-admission
gate incorrectly required every current-shell alternative to be fresh at
once. A deterministic actual-worker scene reproduced the failure with only
27 CURRENT AP points: real evaluations charged 1.5 ms each exhausted the
unchanged eight-millisecond atomic slice while other actors kept changing
pose. Extending the original 200-callback bound or zeroing its real clocks
would conceal that production liveness regression.

The follow-up separates completed physical-inspection coverage from exact
launch evidence. A still-current known blocker is required for movement;
completed observations do not enter armour-failure certificates, NEXT or
launch permission. New identities and domains must be inspected, and genuine
task, load, shot or recovered-aim boundaries retire the appropriate inspection.
The original handoff cases keep their real clocks and 200-callback bound.
Additional actual-native slow-query cases retain unknown, vanished-blocker
and freshly executable alternative controls. Work quotas and time limits
are unchanged. This does not solve general moving global negative closure.

Stale evidence, live-target identity, manual mission, native friendly-fire,
actual ammo debit, route resumption, target death and burst-tail protections
must remain asserted. A replacement test that checks only an order label or
weakens an unrelated native condition is not an acceptable migration.

## Validation entrances

Run each file in an isolated interpreter with `tools/run_test_suite.py`, then
the complete client and launcher inventories. Keep the individual logs and
summary records, including failures and skips; an earlier integration run is
not the final frozen-tree result.

```
python tools/check_shared_vehicle_control.py --check
python tools/run_test_suite.py --jobs 4 --logs build/client-final
python tools/run_test_suite.py --directory launcher/tests --jobs 2 --logs build/launcher-final
python2.7 tests/test_player_embedded_contract.py -v
```

The native traffic include changed. Rebuild the host extension for actual
Python/native parity and rebuild the shipping Windows x86 `.pyd`. A green
reference-only test or an old binary is not evidence that the new enemy roster
will run in the game. `tools/verify_native_payload.py` binds the shipped PE to
all current C++/header/include/build inputs. After downloading the CI artifact,
verify its digest, inspect the runnable launcher layout and nested client
archive, then run `tools/verify_release0100_code.py` under actual Python 2.7
against the packaged mod to compare every client code object with this tree.

Actual CPython 2.7.18 compatibility tests do not execute BigWorld's embedded
2.7.7, its native terrain or the exact Chinese HD 0.9.22.0.1 #1513 game loop.
The user still accepts AT7/STB1 opening routes, wall/front-vehicle scenarios,
green-aim firing, HE-to-next-load transitions, stationary BOT turret motion,
manual intervention, sound and frame pacing in the native client. Those
observations are not replaced by CI or package identity checks.
