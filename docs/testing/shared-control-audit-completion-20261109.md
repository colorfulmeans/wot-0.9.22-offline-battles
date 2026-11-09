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

## Phase 2: one execution owner and retained physical gates

The common `AttackPolicy` now owns the current target and recovery intention.
`CombatStop` resolves that intention before accepting a macro order, and its
consumer uses the returned order. Changing only a macro hint or its mode cannot
discard another still-valid native target. A changed/dead/blocked target, a real
new policy intention, and an explicit task still receive normal revalidation or
handoff; target stability is not a substitute for a current firing proof.

The competing `_target_assignments`, `_assign_targets`, and target-record
maintenance are deleted. `_initial_target_hints` is stateless: all currently
observed eligible living contacts, nearest first, exact-distance tie broken by
lower known nominal armor. Missing armor remains unknown, not manufactured zero.
No role-based engagement radius or `no_local_lane` exclusion shrinks this domain.
The remaining role radius participates only in task ETA/progress estimates.

Two real ballistic counterexamples prevent a renamed heuristic from returning:
an ordinary gun can actually launch at 400 m with mounted maximum 500 m despite
its profile value 340 m, and a native SPG HE arc can launch at 1500 m with mounted
maximum 3000 m despite a role value 1250 m. The same scenarios with actual maximum
350 m and 1400 m respectively cannot launch or debit ammunition. Ordinary true
range obstruction requests firing-position recovery, not an armor-negative
certificate or an eight-second timer.

The downstream friendly-reposition consumer also used to reread the raw macro
order after `BotControlBinding.refine_order`. In the real six-actor fixture,
actor 11 selected enemy 14, actor 12 obstructed its lane, and another living
heavily armored enemy 15 moved closer. The old consumer canceled recovery 14 on
every frame because the initial hint became 15. It now requires the resolved
order explicitly. Four regressions cover stable marker/start/deadline/destination
across hint changes, actual native target replacement, explicit hold takeover,
and actual target death. No timer or steering compensation was added.

Before the first trigger edge, the selected target/shell/sample is refreshed at
the final physical pose with at most one ballistic prediction. This does not
rerank targets, spend another world/armor search, or weaken precise source,
target, weapon, ammo, clip and scene fences. The unchanged current-center and
scattered-ray admission still reject an unlaid gun or a pose change after prepare.
Already committed physical trigger tails retain their original accounting.

Common `EvaluationBudget` limits optional all-actor work to eight background
candidates per outer physical callback, at most two per actor, and one newly
opened atomic actor. Persistent fair queues, dead-actor pruning and callback
identity prevent starvation and quota renewal across late physical substeps.
Current foreground work and actual firing proof retain their existing gates.
Deferred work creates neither false negative evidence nor a fake eight-second
clock. `shared-combat-concurrency-20261109.md` records actual measurements and
their limits; eight candidates does not mean eight primitive HE surface queries.

## Migrated verification contracts

The full suite is rerun against the new source, not made green by retaining old
entrances. Obsolete macro target locks and role-range cutoffs are replaced by
initial-hint assertions plus real native execution/invalidity tests. The prior
HE handoff case incorrectly called 340 m a real weapon range and required the
better HE target to remain unconsumable; its replacement proves that the better
current HE target is selected, actually launched, and charged once while NEXT
retains its separate AP plan. Real driver-margin refusal remains a separate
positive-evidence/no-launch regression.

Native capability fixtures now override `decide_with_order`, not deleted
`decide`. Head-on and GC fixtures publish an actual canonical `alive` value;
strict production wire validation, physical shove assertions and zero-cycle GC
checks remain unchanged. Burst tests assert the new exact rejection stage and
receipts rather than requiring a later stale-pose reason, while preserving all
committed tails and no-next-trigger/no-extra-debit assertions. Budget tests
explicitly separate a deferred NEXT comparison from actual zero-damage evidence
and exercise fair service on the following callback.

## Completion record

Phase-2 changes, exact final tests, CI, package identity and remaining real-game
acceptance limits are recorded in the final shared-control handoff. A prior green
CI run or an older package is never substituted for final-tree verification.
