# Shared automatic control handoff — 2026-11-09

> **November 10 control-offset correction:** the eight-second penetration
> search and the independent BOT gun-angle position finder described in this
> historical handoff have now been removed. The single-sample native firing-
> position recovery, immediate eligible HE fallback and finite route-release
> contracts are recorded in
> `shared-control-offset-audit-20261110.md`. This newer record controls where
> the historical descriptions below conflict; final package identity must
> still be verified from the newly pushed PR/CI run.

## Audit correction: read before the historical migration record

The `be5bf798` delivery passed its recorded CI/package checks but did **not**
complete the requested controller migration. The surviving director/fallback,
private mission state machine, macro current-target ownership and physical
recovery's raw-order lookup are completed/removed by this continuation. The full
audit and the phase-one/phase-two distinction are documented in
`shared-control-audit-completion-20261109.md`; that record supersedes earlier
completion language below. Historic green test counts are not final-tree proof.

The current bindings both inherit `MissionControl` and `CombatControl`.
`BattleRoster` only initializes vehicles/routes; it cannot issue runtime orders.
`SharedOrderPlanning` handles absent orders with the one shared planner or
explicit non-firing pending. `BattleDirector`, adapter `plan_order/decide`,
`_target_assignments` and `_assign_targets` no longer exist.

Ordinary acquisition includes all currently observed valid living contacts;
role-based `_engagement_range` and `no_local_lane` do not filter that domain.
Closest first and exact-distance lower-armor tie-breaking are initial hints,
not another current-target owner. Real mounted maximum distance is carried from
the native ballistic solution to the final distance guard for ordinary guns and
SPGs. Actual unreachable targets still request normal firing-position recovery.
Macro hints cannot cancel its marker or restart its deadline.

Before first-edge admission, the same selected target/shell/sample is refreshed
at the final physical pose with at most one ballistic prediction. No new native
world/armor queries, re-ranking or weakened pose fence are introduced by that
refresh. Actual center/scattered-path/armor/HE proof and native ammo debit remain
inside the original common transaction.

A completed HE comparison which already produced an executable aim also owns
its uncommitted first-trigger intention. A new, higher-damage contact or NEXT
result cannot preempt it while that same current point remains valid. Every
continuation still revalidates actual geometry and the selected point's source,
target and affected-lane fence; unrelated competitors cannot cancel execution
by moving inside a native callback. Full-domain fences remain on initial and
next-trigger ranking. The phase stores identity, not proof. Death, true blocking, mechanical/identity
changes, loading and recovery retire it. The first real commit clears it, burst
tails cannot recreate it, and the next trigger completes a new comparison.
Initial full-domain ranking is never replaced by first-contact firing.

The common `EvaluationBudget` holds only scheduling tokens, not actor state:
per outer physical-control callback, background work has eight candidate slots
in total (at most two per actor) and a maximum of one actor starts an atomic
speculative slice. Late physical substeps cannot refill it. Current foreground
review and actual firing proof retain their existing limits and validation.
Deferred work remains pending, never a negative armor certificate or fake zero
HE damage. HE surface rays are counted separately from armor batches; candidate
limits do not imply the same number of primitive collision calls.

Player diagnostics now report `shared_single_source` and profile the
`player_shared_control` stage. The final external handoff and PR identify the
exact pushed commit, CI run, downloaded artifact and audit results; those cannot
be known or asserted merely by committing this source document.

## Delivery and controlling requirement

- Repository: `colorfulmeans/wot-0.9.22-offline-battles`.
- Earlier partial migration base: `ddf411763e677cc99cf5938aa281d29d579ef9e6`.
- This continuation's audit base: `be5bf7981d9685ed7c5e211ccbd8f4d18756ee10`.
- Earlier integration branch: `fix/shared-control-phase1` (both phases integrated).
- November 10 continuation: `fix/pr119-shared-control-resume`, based on the
  two already-pushed phases and the recovered `4e9f5f6c` correction.
- Review/delivery branch: `fix/elite-premium-ammo-reviewed-guns`, PR #119.
- The delivered implementation is the commit containing this handoff. The final
  response and PR record its exact pushed SHA and CI/artifact identity.
- This is a review/test build, not a merge into `main`, tag or published release.
- Target remains CN HD 0.9.22.0.1 #1513, x86 embedded CPython 2.7.7. Packaging uses
  the pinned compatible CPython 2.7.18, not the host Python 3 test interpreter.

The user's required order is authoritative: first move the current player
automatic controller into the single implementation used by players and Bots,
removing the duplicate implementations; then remove obsolete lower-level policy
and difficulty effects. Do not restore the earlier requirement for independent
player copies, original Bot policy, or pointer-selected legacy fallbacks.

## Single implementation and ownership

The live code is under
`src/res/scripts/client/gui/mods/offline_lan_0922/vehicle_control/`.

| Owner | Current responsibility |
| --- | --- |
| `combat_control.py` | Common combat admission, current/future ammunition decisions, firing-position handoff, siege readiness and aim-stall observation |
| `attack_policy.py` | Per-actor penetration/HE evidence, stable current intention, bounded review, 8-second all-failure search and NEXT load evidence |
| `trigger_admission.py` | Common current native first-edge proof; no second ammunition debit owner |
| `strategy.py`, route task/recovery modules | The same strategy types imported by the server and foreground controller |
| `geometry.py`, `engine_control.py` | Single geometry and common control implementations; no shadow copies on BattleRuntime |
| `actor_observation.py`, `bot_binding.py`, `player_binding.py` | Actor-specific native observations and input/physical publication boundaries |
| `full_runtime.py` | Foreground lifecycle, manual input and local task adapter, inheriting common combat behavior |
| Existing worker gun, motion and projectile owners | Actual physical simulation, loading/debit, committed trigger tails and retry/ACK bookkeeping |

Every actor has independent policy, target, ammunition planning, lifecycle and
geometry state. The foreground never controls a worker actor or borrows a worker
decision. The worker adapter reads its own entity, gun, team and mode; it does
not read the observer Avatar's mode or crew.

Deleted implementation paths include the entire `player_control` tree, its
`copied` subtree, the four standalone `server_*` strategy/route copies, and the
copy generator/checker. The new checker verifies actual class/method identity,
absence of alternate imports, retained physical contracts and actor isolation.
It does not compare two copies and excuse differences.

## Confirmed behavior changes

1. **Ordinary acquisition:** choose the closest live observed enemy. Only an
   exactly equal distance uses lower nominal armor as a tie-breaker. Point-level
   penetration validation still decides whether and where the vehicle may fire;
   nominal armor never becomes launch permission.
2. **Current target stability:** a valid penetrating current target/point stays
   selected while its observation remains usable. NEXT load planning, a new
   attacker, a human identity, or an old weighted score cannot steal it. A real
   death, pose/ammunition change, blocked lane or loss of reachability still
   invalidates the relevant proof. Committing a shot retains intention, not a
   reusable launch receipt.
3. **SPG acquisition:** compare the actually loaded HE's expected damage at
   targets with completed reachable native arcs and clear full-path ally/wreck
   checks. The terminal incidence/contact estimate is used, not nominal shell
   damage or a straight line-of-sight proxy. Re-ranking after final review cannot
   retain a candidate whose refreshed damage is now lower. No automatic HE switch
   is introduced. A committed trigger keeps its frozen target.
4. **Difficulty cleanup:** remove artificial reaction time, aim patience,
   convergence/scatter acceptance factors, aim-point offsets and lead error,
   plus rating-based weakpoint/ammunition capability gates. Remove attacker
   retaliation, player priority, target-score/focus quotas and tactical hull
   angling. The historical `bot_gunnery` module now contains fitting presets,
   not an alternative gunner policy.
5. **Actual configuration retained:** stock/intermediate/full modules, true crew
   training and skills, equipment and associated directives, consumables, outfit,
   slot overrides and room fitting distributions remain. Difficulty is therefore
   not reduced to crew percentage alone. Actual dispersion, convergence, turret
   speed, reload and predictive ballistics still follow the installed vehicle.
6. **HE ranking completed before use:** a first zero/low-damage contact cannot win
   while later eligible points remain unvisited. Budget-pending observations are
   not "unknown but completed" or zero damage. A genuinely observed unavailable
   contact does not become an armor-failure proof. For the loaded HE round, a
   finite pass retains only ranking observations across normal target motion;
   the highest-ranked key must still obtain a current, executable native row.
   A 54/63-point moving domain therefore need not fit into one frame to make
   progress. These hints contain no trajectory, armor result or fire authority,
   and are not read by NEXT or the eight-second negative proof. They are scoped
   to the actual shell/entity/sample identity and renewed after a physical
   trigger. A reentrant invalidation cannot publish the unfinished frame's hints.
   This is the best contact from a bounded observation pass with a fresh winner,
   not a claim that every moving competitor was measured at one instant.
   Once that first pass is complete, an unfinished recheck of an old high-ranked
   point yields its turn to other already-ranked points. Those points still need
   current executable rows; the pending point is neither assigned zero damage
   nor permanently excluded. Completing the finite recheck queue permits retry.
   Negative proof and HE review may use the remaining original atomic budget;
   there is no second budget reset or increased limit to force completion.
7. **NEXT remains independent:** compare all eligible HE points and retain their
   comparison evidence, not only the winner. A changed losing candidate or newly
   added target/ammunition domain expires the old ranking. The last mounted
   cassette is excluded from the next full load when no replacement stock exists.
8. **Existing ammunition rules preserved:** the 65% penetration admission,
   ordinary-HE one-point penetration trial and exact HESH exceptions, current
   cassette ownership, trigger grouping and per-shot native proofs remain. The
   eight-second search is still for completed all-enemy penetration failure.
   Friendly/wreck/world obstruction and mechanical limits go to shooting-position
   recovery rather than becoming fictitious armor failures.

## Integration defects fixed during verification

- SPG shared acquisition now receives each enabled control refresh instead of
  being accidentally limited by the ordinary strategic cache. Work remains
  bounded per control step; non-control physical slices add no extra review.
- Bots now feed native aim progress to the same existing stalled-lay detector.
  Genuine aiming progress, movement and alignment reset it; an unchanged,
  non-converging aim can reach the common recovery instead of waiting forever.
- One common loading-completion observation releases `_loading_switch` for both
  bindings, including loading completion immediately followed by a real shot.
  It does not create a new reload clock or debit ammunition.
- End-of-round snapshots close actor controllers and discard their pending
  first-edge proofs; actor/generation replacement cannot retain another life.
- Once a first shot is actually committed, first publication and retransmission
  use its frozen launch record even if the source entity is unloaded. Repeated
  publication and duplicate ACKs do not re-sample dispersion or debit ammo again.
- Bot-only search/readiness overrides were deleted. Native mode observation is
  an I/O interface; navigation/search permission and mode readiness use the exact
  same common methods on both bindings.
- The Windows server freezer explicitly includes `decimal`, required by the
  shared strategy's Python 2/3 half-even rounding helper.
- The native-motion comparison fixture now fixes only its initial allocation
  randomness, without changing the production random generator or the standard
  library generator. Previously 19 of 29 actors started on different routes
  between comparison arms. All initial actor states and routes must now match
  before any native slice is compared; exception cleanup restores the fixture's
  original random reference.

## Routes, removal and rollback boundaries

The October hand-authored Default remains the sole default route authority. Its
data and the current physical navigation grids are not redrawn for this change.
Negative map coordinates remain valid. Current named user route edits, real
waypoint skipping, collision avoidance and physical recovery remain supported.
Do not reintroduce August AI routes, special-case workarounds for those routes,
cover peek, tactical retreat, crossfire withdrawal or old flanking behavior.

The build cleanup physically deletes 18 historical source-rewrite/pinned-package
tools, 15 dedicated workflows and 42 encoded patch fragments. Some had restored
whole old Bot trees or copied a September client ZIP over current staged output.
See `shared-control-build-retirement-20261109.md` and the explicit absence test.
Current native/mesh tools and current-source standard builds remain.

No rollback alias, retired-source fallback, disabled alternative implementation,
or old-package build option is retained. Normal Git history is not rewritten;
any subsequent functional rollback must keep this single-source architecture
and the owner-reviewed Default rather than rebuilding a retired implementation.
User saves, backups and custom fitting/route data are not deleted.

## Report evidence and its limits

The supplied `wot-error-report-20261109-141918-b5be9be97cb1.zip` contains stationary
target switches (including 14 to 6 and 13 to 1 to 13) and later alternating hull
control near the reported wreck. The sampled candidate list does not include the
dead KV-2, so this report does not establish that the corpse itself was selected.
The sampled recent-hit state is empty and health remains full: attacker
retaliation is an obsolete conflict removed by request, not a demonstrated cause
of that exact captured event. The old player path already bypassed some artificial
aim bias; its removal is not retroactive proof that bias caused this report.

## Verification record

Original shared-tree host commands (CPython 3.12; each test file runs in its own interpreter):

```bash
PYTHONDONTWRITEBYTECODE=1 python tools/run_test_suite.py --jobs 4 \
  --logs /workspace/scratch/31313bfc39b8/verification/release-client
PYTHONDONTWRITEBYTECODE=1 python tools/run_test_suite.py \
  --directory launcher/tests --jobs 4 \
  --logs /workspace/scratch/31313bfc39b8/verification/release-launcher
PYTHONDONTWRITEBYTECODE=1 python tools/check_shared_vehicle_control.py --check
git diff --cached --check
```

The full client run completed all 503 files without failures: 10,444 test cases,
including 9 explicitly reported skips for unavailable Python 2.7, pinned #1513
resources, the optional native extension or Windows fixtures. The launcher run
completed all 49 files without failures: 1,325 test cases, including 170
environment-dependent skips (including actual Tk display tests). The
single-source ownership/integration checker passed all 46 cases, including its
rerun after final whitespace cleanup. The staged whitespace/error check passed.
No skipped test is counted as native or graphical acceptance. Earlier partial
runs are diagnostic evidence only, not substitutes for these final runs.

Current regression families include shared-owner identity/absence, real
BotRuntime first-edge debit/publication/ACK, foreground manual isolation, SPG
arc/HE selection, complete current/NEXT HE ranking, ordinary-HE and magazine
rules, siege/limited-traverse control, route authority and unchanged physical
collision/support/navigation fixtures. Old fixture imports and mocks now bind
the shared module where production actually executes. Native geometric and
ammo assertions are not replaced with always-successful decision stubs.

The CURRENT HE suite additionally covers 54/63 moving points, stale high-ranked
contacts becoming blocked or disappearing, repeated pending rechecks, new
targets/sample layouts, entity/collision-component replacement, physical trigger
tails and post-trigger renewal. It verifies current rows and unchanged per-frame
budgets, not just an `aim` action label. NEXT and eight-second authority remain
absent when only these positive ranking hints exist.

A large continuously moving **full-validation HE/HESH** negative domain remains
distinct from ordinary-HE contact ranking. In the 63-point negative fixture the
bounded slice cannot certify every failing plate at once, so it correctly uses
`firing_position / global_snapshot_budget_pending`, with no eight-second timer
or fallback permission. A later valid positive point can still be selected.
The current-HE ranking fix must not turn old hints into a negative certificate.

## Resumed delivery fixes

The first remote shared-control commit, `4ca0c85a`, has exactly the same tree
as the original local `55b1c732` (`a3f24a3891d9ec4df1d530ae220b6dbfca4cb30b`).
Its first CI run exposed two checks that the original host-only run could not
exercise: a Python 2 cold-import cycle and an obsolete thirteen-row Windows
editor smoke expectation. Neither failure is represented as a successful build.

- `SharedEngineControl` no longer imports its partially defined `BotRuntime`
  owner while the physical class is importing its base. The method that needs
  physical timing constants imports their one existing owner at execution time.
  No constants, control algorithm or legacy implementation were copied.
  Three cold-import tests cover both production import orders and explicitly
  reject the reverse import during base-class definition, including on Python 3.
- Loading-time single-shot replacement admission now uses the current candidate
  and native observation fences instead of a second whitelist of policy reason
  strings. The old whitelist omitted `ordinary_he_point_failed`, delaying a
  verified replacement until loading finished. Single-shot/burst restrictions,
  manual input ownership, current inventory, first-edge ownership and the
  once-per-load guard remain. A new real evaluator-to-input-to-shot regression
  fails on the previous code with `reload_time == 0` at the actual input boundary,
  then passes with a still-active load and exactly one replacement AP shot.
  It checks the native input moment, not merely the start of the control tick.
- The Windows editor smoke is migrated to the eight retained configuration
  fields and their actual independent override/source semantics. Retired policy
  fields are not restored to satisfy the old row count.

Resume checks independently read every completed original test log. The 46-case
shared checker and 145 affected combat/binding/HE cases passed, followed by 71
ammunition, reload and actor-binding cases including the new input regression.
The official CPython `v2.7.18` source was built locally for actual interpreter
verification: all 22 embedded-contract tests passed without skips. The original
failing ground check also passed 73,016 comparisons using that interpreter and
the native extension rebuilt from the current C++ sources. All 27 native CI
checks subsequently passed locally, including 7,008,996 control comparisons
with maximum difference 0.0. The updated preview checks completed 20 host test
cases (12 passed, 8 explicitly skipped for the unavailable Tk display); the
actual Windows widget smoke remains a final CI gate. Final CI and artifact
identities are recorded in the delivery report and PR; these targeted checks
do not substitute for the final same-source Windows build.

## Remaining delivery and Windows acceptance

The resumed Linux host has a locally built CPython 2.7.18 but does not contain
the exact Windows BigWorld client, MinGW, Wine or Docker. Linux interpreter and
native checks cannot establish Windows x86 payload identity, real actuator
timing or gameplay FPS.
The standard PR CI builds the current native module, compiles the client with
Python 2.7, validates staged bytecode/package identity, then builds and checks
the Windows launcher/server artifact. Do not repackage an old executable or
native payload and label it as a fresh test build.

On the exact delivered build, test both player automatic control and Bots:

- A stationary penetrable target remains selected through ordinary shots and
  reloads unless actual evidence changes; an incoming attacker does not steal it.
- HE-only operation beside the KV-2 wreck does not enter obsolete hull angling,
  attack the wreck, or confuse a blocked lane with failed enemy armor.
- Ordinary, magazine and machinegun triggers keep actual ammunition/tails and
  correct current-versus-next choices; repeated loading cycles can switch again.
- Casemate/limited-traverse and siege vehicles stop/lay/recover coherently.
- Artillery chooses a reachable high-potential HE target without forced ammo
  switching, repeated pre-shot target thrashing or unbounded review work.
- Multiple Bots use their own gun/crew/mode state; ending/restarting a round or
  taking manual control does not leave an old controller driving another life.
- The launcher shows and uses the October Default in normal and test scenes.

Collect the coherent launcher, server, foreground and hidden-worker logs for any
remaining failure. Container regression passes do not replace this play test.
