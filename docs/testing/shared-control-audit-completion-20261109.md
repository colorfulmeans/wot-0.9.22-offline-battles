# PR119 shared-control audit and completion — 2026-11-09

## Authority and evidence

This audit supersedes the completion claims in the earlier handoff where they
conflict. The controlling instruction is the user's full conversation supplied
on 2026-11-09: first share the existing player controller, then remove obsolete
policy in that one implementation. An earlier requirement for independent
player copies is no longer authoritative. Tests must execute current production
paths, not preserve a retired controller to satisfy old assertions.

The audit starts from `be5bf7981d9685ed7c5e211ccbd8f4d18756ee10` on PR119,
`fix/elite-premium-ammo-reviewed-guns`. The two uploaded history files are
byte-identical. They explicitly identify conflict between macro target choice
and the new aiming policy, and require deleting the old selection/preemption
entrances rather than adding target timers or compensating steering rules.

The uploaded `wot-error-report-20261109-141918-b5be9be97cb1(1).zip` has SHA256
`f41ee02b4ffef147cc787cded6514a7b6be1e21e9d28277431d3cc0a26bbb052`.
Its build is `colorfulmeans-42567988322-1`, associated with commit
`59930fccaecb9635fcb81f289cd3eb4f45367a5f`, not the later `be5bf798` package.
It cannot establish that a later change ran in that recorded game.

## What the audit found

| Earlier claim or proposed action | Evidence and disposition |
| --- | --- |
| One complete controller already owned both actors | Incomplete: `BattleDirector`, `BotAdapter.plan_order/decide` and the runtime missing-order fallback still existed; the foreground task state machine was still private. Complete sharing before policy cleanup. |
| Removing weighted scores eliminated the target conflict | Incomplete: a macro order's target/mode could still change `CombatStop` permission and make `AttackPolicy` discard a different, valid native target. Delete the competing state/ownership path, not only scoring formulas. |
| Restore `no_local_lane` exclusion and a two-second yield rule | Incorrect audit proposal. It contradicted the supplied history and would restore old interference with the complete armor domain. All of this uncommitted proposal was exactly withdrawn; it is not a runtime option. |
| Roll back all previous changes because the handoff overclaimed completion | Not justified. Shared combat, native binding, artificial gunnery removal, configuration preservation and HE fixes are independently useful authorized work. Retain them and repair the missing integrations. |
| Treat corpse proximity as proof of an invalid enemy selection | Not supported. The report contains real corpse-lane blocks, but no evidence that the corpse itself was selected as a living enemy. Preserve corpse collision and separate it from armor failure. |
| Interpret a passing physical/compatibility gate as complete combat acceptance | Not justified. Each gate proves its stated boundary. Multi-actor combat, target ownership, native first-edge admission, actual loading and work budgets require their own exercised tests. |

Recorded target disagreement includes macro target `14 -> 11` while the new
policy changes `14 -> 6` at the same source position, and macro target `13`
while the policy uses `1`. The reload-dependent old hull-angle change is a
secondary chain in the same report, not a substitute for the selection conflict.

A deterministic production-path reproduction at the audit base makes the
ownership defect explicit: macro A is initially at 50 m with nominal armor
10000; native aiming selects reachable, penetrable B at `(30, 0, 100)`. Moving
only A to 360 m changes its macro mode from `engage` to `advance` against a
340 m macro range. Neither the source nor B moves. Nevertheless the next native
policy result becomes `wait/current_shot_navigation_owned`, clears B and loses
stopping permission. The completion regression must preserve B in this case,
while still invalidating an actually blocked, dead, unreachable or changed B.

## Phase 1 checkpoint: complete the shared source

- `MissionControl` contains the moved foreground task state machine: explicit
  tasks, implicit capture, arrival observation, terminal states, retry, task
  projection, and final command guarding. `FullPlayerRuntime` and
  `BotControlBinding` inherit that same class with independent actor state.
- `HaltObservation` uses one physical rest law. Bindings provide their actual
  motion/support observations, never a manufactured settled result.
- `BattleRoster` retains only vehicle/profile and initial route-catalog setup.
  It has no contact memory, target selector, route cursor or runtime order API.
  Regular battles still apply the authored Default initial allocation.
- `BattleDirector`, `BotAdapter.plan_order`, and `BotAdapter.decide` are deleted.
  The physical adapter only executes an already selected common order.
- A missing published order invokes the same `BotPlanner` implementation through
  `SharedOrderPlanning`, with round-local state and observer/radio-scoped facts.
  Existing published orders are not replaced by this recovery path. Missing
  actor/manifest data yields explicit non-firing pending; a missing physical
  adapter fails explicitly. There is no old-engine fallback.
- Whole-roster fallback planning and contact materialization retain the existing
  one-Hz strategic cadence. Each actor's current observation is retained between
  builds; there is no per-actor per-frame full-roster rebuild or native ray pass.
- Prior director tests are migrated to real roster setup, real shared planning,
  and real `decide_with_order`. Their fixture helpers format data only.

Two existing command contracts remain distinct inputs to shared implementations:
server radio commands retain their server TTL/base-defense lease, while explicit
controller missions retain their foreground completion/holding contract. Forcing
one into the other during migration would silently change task semantics. Both
actor bindings can execute `MissionControl`; both consume the same `BotPlanner`
for network commands. Repeated local mission IDs are scoped by recipient actor.

This checkpoint does not claim that phase 2 target ownership is already fixed.
The behavioral cleanup is reviewed in the following commit, not hidden inside
the equivalence migration.

## Verification interpretation

The phase-1 shared ownership gate exercises 65 tests, including actual common
mission methods, actor state separation, missing-order recovery and the absence
of old runtime entrances. The three focused runtime/mission/planning files also
execute the moved paths. The lane-service one-key-per-pair test now supplies
explicit neutral shared orders so that it still measures observation work,
not an additional legitimate rear-approach cache read from a real missing-order
plan. Its per-pair native-call assertions were not weakened.

Actual CPython 2.7 checks are separate from host Python 3 tests. The shipping
world-query pipeline compares all ten physical scenarios with 29 actors and
three native/reference/reuse arms, including collision and committed effects.
It does not measure targeting performance or game FPS.

The standalone `check_native_simulation_motion.py` comparison also exposed an
existing mismatch in the old uninstalled persistent `NativeMotion` owner:
`movement/settlement/11/after_contacts[2]` is `-3.553239443760413` versus
`-3.511759622394048`. The identical mismatch occurs at unmodified `be5bf798`
and this checkpoint. Shipping `NativeSimulation` deliberately installs only
the current control and weapon owners and leaves `motion = None`; the current
Python physical owner with native world-query frontiers passes its own ten-case
comparison. This unrelated old-owner failure is recorded, not hidden, repaired
by changing current physics, or counted as a passing acceptance gate.

## Completion record

Phase-2 changes, exact final tests, CI, package identity and remaining real-game
acceptance limits are recorded in the final shared-control handoff. A prior green
CI run or an older package is never substituted for final-tree verification.
