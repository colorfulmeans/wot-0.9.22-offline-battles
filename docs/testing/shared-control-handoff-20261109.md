# Shared automatic control handoff — 2026-11-09

## Delivery and controlling requirement

- Repository: `colorfulmeans/wot-0.9.22-offline-battles`.
- Implementation base: `ddf411763e677cc99cf5938aa281d29d579ef9e6`.
- Local work branch: `fix/shared-vehicle-control`.
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

Final host commands (CPython 3.12; each test file runs in its own interpreter):

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

## Remaining delivery and Windows acceptance

The host does not contain the exact Windows BigWorld client, CPython 2.7,
MinGW, Wine or Docker. Host Python tests cannot establish embedded-runtime
compatibility, x86 native module identity, real actuator timing or gameplay FPS.
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
