# Shared combat concurrency and work-budget evidence

## Reproduction commands

Run from the repository root with Python 3:

```sh
PYTHONPATH=tests python -m unittest test_report_141918_control_regression test_shared_multi_bot_combat test_shared_evaluation_budget -v
python tools/check_shared_multi_bot_combat.py --actors 29 --frames 60 --warmup 10 --schedule stress20 --output verification/combat-stress20.json
python tools/check_shared_multi_bot_combat.py --actors 29 --frames 60 --warmup 10 --schedule worker10 --output verification/combat-worker10.json
```

The measurement tool exits nonzero for an unmatched ammunition debit, missing
actual launch in the engagement case, combat evaluation in the no-enemy case,
per-actor candidate overrun, more than eight actual background candidates per
callback, multiple atomic actors in one callback, missing actor service, or
starvation of the fixed live roster. It does not impose a wall-time threshold.

Arguments are `--actors` (6 through 29; default 29), `--frames` (at least 20;
default 60), `--warmup` (default 10), `--schedule` (`stress20` or `worker10`),
and optional `--output`. Without `--output`, the full JSON is printed. A short
case result is printed to stderr. Both schedules run the same no-enemy control
followed by a mixed AP/HE engagement, without concurrent cases in the process.

`stress20` invokes a complete authority slice with control refresh every
0.05 seconds. It is an intentionally stronger 20 Hz control load, retained for
the before/after comparison. `worker10` enters the actual `BotRuntime.update`
with `WORKER_CONTROL_SECONDS = 0.10`, using 0.10-second callbacks. This tests
the production fixed-control scheduling branch. The fixture still uses the
Python reference physical integration, rather than the native simulation
extension. The JSON records that distinction and the actual gun class.

## What the concurrent fixture executes

All actors belong to one `BotRuntime`, with opposing teams and multiple live
targets. Orders come from the real shared `BotPlanner`; each actor has its own
`BotControlBinding`, `AttackPolicy`, `NativeAttackEvaluator`, `TriggerAdmission`,
`_BotGunState` and `_BotAmmoState`. The default `BotAdapter` and `LocalDriver`
consume the orders. Native worker triggers, magazine changes, reload clocks,
scatter, committed launch records and ammunition debits execute production code.

The external native boundaries are analytic: a flat support graph, known visible
contacts, component boxes, rendered matrices, and optional world boxes. The
fixture does not prescribe a policy winner, a successful armor result, a ready
trigger, or a fire command. It does not integrate launched projectiles into
damage, death or the map world. A launch is counted only after the real native
worker commit and is checked against the exact ammunition decrement.

The six-actor regression includes two HE-only actors which begin facing their
nearest strategic contact. The native damage ranking chooses a different live
target, so these vehicles must turn naturally. They are not pre-aligned to the
winning native candidate. All six must commit at least two launches, with both
AP and HE present, independent one- and two-round magazines, real reloads, and
unchanged authored routes. Each committed proof's raw source pose must exactly
equal the physical source pose. The serialized origin is compared using the
production `projectile_wire.round_scalar` quantizer.

Separate concurrent cases establish these boundaries:

- One actor's real low-penetration ammunition closes a current all-target armor
  failure proof and runs its full eight-second search clock while the other
  five continue firing with their own clocks unset. Budget-pending evidence
  cannot start that clock.
- A real analytic native wall prevents one damaged actor's firing lane from
  closing. This remains unresolved geometry and never becomes all-enemy armor
  failure. Other actors continue committing launches.
- A physical source translation between successful preparation and final
  validation rejects only that actor's commit, with no debit. Other actors
  continue firing. The exact native pose fence remains in effect.

### Atomic time fixtures and the eight-second logic test

The private eight-second-clock test controls only actor11's atomic elapsed-time
source. It holds that virtual clock steady while the real native evaluator
closes the complete domain: three enemies with nine AP points each, plus the
ordinary HE trial unless that real single-point trial has already failed.
The test requires every remaining domain point to have an actual clear,
reachable negative armor proof, with no unobserved, projected or pending row.
The production 8 ms limit and the candidate/world/armor count limits are not
changed. The subsequent search deadline still uses the real simulation clock
and lasts the full eight seconds. All five peers retain their ordinary wall
clocks, native triggers and ammunition accounting.

A paired concurrent test calls actor11's original native evaluator first, then
advances only that actor's virtual atomic clock by 9 ms. Actual world and
component queries must have occurred. The unchanged 8 ms limit must leave the
partially reviewed domain incomplete with `atomic_frame_budget_exhausted`, no
eight-second search start and no ammunition debit, while peers keep firing.
That unresolved condition is checked across more than eight simulation seconds.

This distinction addresses a test precondition exposed by the historical
`ace51653` full-suite CI run: a 28-candidate atomic review completed 15
candidates in 8.726 ms, correctly remained pending, and therefore could not
start the eight-second clock that the old test expected. A parallel host's
throughput is not a deterministic prerequisite for testing that clock's state
isolation. This is a test-fixture correction, not a production performance fix.
`shared_multi_bot_scene.py` and both 29-actor benchmark schedules retain the
actual wall clock; their measured deadlines and pending states are unchanged.

## Report regression and the discovered final-pose gap

The reduced player regression records report SHA256
`f41ee02b4ffef147cc787cded6514a7b6be1e21e9d28277431d3cc0a26bbb052`, build
`colorfulmeans-42567988322-1`, whose verified CI head is
`59930fccaecb9635fcb81f289cd3eb4f45367a5f`.

The report distinguishes old macro selection from native policy selection:
the macro changed 14 to 11 while the policy changed 14 to 6; another sequence
kept macro13 while the policy changed 1 back to 13. The later assigned angled
face versus reload movement-lease direct face is a demonstrated sub-chain,
not a replacement for that ownership conflict. Actor10/KV-2 really blocked
seven sampled earlier rays. The report does not prove a dead KV-2 was selected
as an enemy, and its sampled later clear rays cannot establish every missing
ray was clear.

`test_report_141918_control_regression.py` retains the reported player and
target14 positions, HE-only ammunition, target14, the actor10 wreck identity,
and the original route. It executes four real HE launches across at least
three actual reload completions. A controlled analytic wreck perturbation
blocks and then clears the lane; this is not a claim that the historical wreck
moved. Another case keeps a macro initial contact distinct from the valid HE
execution target while health and lane observations change.

The concurrent worker fixture additionally found a real final-pose gap:
the shared policy evaluated the source before this slice's motion integration,
then the worker reused that candidate after changing hull and gun pose.
`TriggerAdmission` correctly rejected `auto_source_pose_changed`. Turning HE
actors could remain unfired while the hull approached its intended angle.
The common trigger path now refreshes the same selected target/shell/sample
at the actual final pose and repeats the real admission proof. Neither the
exact fence nor the physics was relaxed. Both the natural-turn launch case
and the post-prepare rejection case pass.

## Work-budget contract

`vehicle_control/evaluation_budget.py` stores scheduling identities and tokens
only. No target, armor evidence, magazine, route, NEXT plan or search timestamp
is shared between actors.

Each physical owner opens one budget for an outer control callback. Multiple
late physics slices in that callback use the same token. A foreground runtime
opens its independent single-actor budget before its policy and then calls its
engine with that same frame identity. Repeated begin calls do not refill it.

Background exploration is limited to eight candidate evaluations for the
entire owner, with at most two for an actor. Pending requesters precede new
requests on later callbacks; with 29 continuously eligible actors, each gets
a background slot within eight callbacks. Death removes a requester and a
new low-id actor cannot jump the waiting queue. A denied actor returns before
constructing background jobs and preserves its evidence, point cursor, NEXT
and already-confirmed search clock.

Only one actor may open a new atomic pass in a callback. That includes the
speculative NEXT review at a trigger edge; denial of that optional review
does not deny the actual current-round firing proof. An actor cannot reopen
the pass to reset its native work/time caps. Its original atomic cadence,
negative-proof conditions and eight-second clock remain unchanged. Existing
same-snapshot HE continuation uses the remainder of the open pass.

Each actor's ordinary foreground allowance remains two candidates. Current
intent, real first-edge admission and the final exact physical validation
remain active independently of optional-work scheduling. Tests cover a real
late worker callback with multiple physics slices and the real independent
foreground policy plus its following engine update.

The eight-candidate limit is **not an eight-native-query limit**. One HE
candidate can perform many blast-surface component queries. Existing atomic
armor-batch accounting also does not count every HE surface ray as a separate
armor batch. The tool therefore reports actual component queries, world
queries, HE blast calls, HE surface component queries and candidate counts
separately; it does not imply that all native work has one primitive ceiling.

## Recorded quantitative runs

Each entry used 29 actors, 10 warmup callbacks and 60 measured callbacks, run
sequentially. The before fixture used the same 20 Hz authority input as the
after stress run. It predated the final-pose correction and optional-work
budget, so the timing change measures the combined corrected implementation;
it does not isolate the budget as the only causal change.

The before runtime source digest was
`fc3ee6666b36e935ff512cebfee0278553ce964cdda17611a589721d5e8bbee5`
on `be5bf798` plus the then-current ownership diff. The after digest was
`3a766eba882cef134a1d3d21f92cadb7d064e0904daf129d7f55633263db3562`
on `b39416e8` plus the budget changes. Each run verified its runtime digest
was unchanged between start and finish. These identify recorded intermediate
source states; the final integrated tree must be measured again when its
production source changes.

| Measured case | Mean wall ms/callback | Mean CPU ms/callback | Wall p95 ms | Actual launches |
| --- | ---: | ---: | ---: | ---: |
| Before, 20 Hz, no enemies | 22.832 | 22.831 | 29.525 | 0 |
| Before, 20 Hz, engagement | 366.113 | 366.093 | 467.329 | 41 AP, 0 HE |
| After, 20 Hz, no enemies | 24.789 | 24.790 | 29.904 | 0 |
| After, 20 Hz, engagement | 251.334 | 251.302 | 356.083 | 42 AP, 5 HE |
| After, real 10 Hz branch, no enemies | 27.036 | 27.023 | 35.730 | 0 |
| After, real 10 Hz branch, engagement | 247.647 | 247.337 | 353.056 | 70 AP, 2 HE |

| Engagement work in 60 measured callbacks | Before 20 Hz | After 20 Hz | After 10 Hz |
| --- | ---: | ---: | ---: |
| Candidate evaluations | 5,062 | 2,224 | 2,488 |
| Background candidates | 3,480 | 480 | 480 |
| Peak background candidates/callback | 58 | 8 | 8 |
| Armor collision batches | 3,669 | 1,697 | 1,934 |
| World queries | 5,925 | 2,601 | 2,754 |
| Component `localHitTest` calls | 358,192 | 218,004 | 193,612 |
| Of those, HE blast-surface component calls | not separately instrumented | 199,264 | 173,512 |

All 29 after-run actors received background service, and at most one actor
performed atomic evaluations in a callback. Including warmup, the after 20 Hz
case committed 66 launches from 24 actors; the real 10 Hz case committed 100
from 21 actors. This is not a claim that every actor fired within those finite
windows. JSON retains every actor's remaining ammunition, target, last refusal,
route, actual query counts and service information.

The same-input engagement mean wall time decreased about 31.4%. The no-enemy
mean increased about 2 ms in that sample. These are analytic Python workload
measurements on the test host. Native collision mesh, BigWorld main-thread,
rendering, network and GPU costs remain unmeasured. These values cannot be
converted into a supported game FPS claim. A short instrumented profile found
HE blast-surface evaluation to be the largest measured collision-work consumer;
profile overhead changes timings and is not included in the table above.

CI should gate exact candidate counts, fairness, source-scoped proof and
ammunition accounting. It should retain wall/CPU results for comparison, while
leaving unstable machine-speed thresholds out of pass/fail decisions.

## Previous integrated-source verification (ace51653, intermediate)

After the friendly-reposition target handoff and remaining production changes
were integrated, both schedules were measured again with the same 29-actor,
10-warmup/60-measured inputs. Both reports identify runtime SHA256
`e3a981f4eea1cf325b95b9a58187ba172ac012a90f3ace37e85340871b043e80`,
with fixture SHA256
`84687c5718217cf0a4d469f8e469e224ec7e4e093ba368b2a4f31fb6f28be591`.
The runtime source was unchanged from start to finish in each run. This is the
integrated working-tree content measured before the `ace51653` repository
commit. It predates the subsequent current-HE intent-preservation correction
and is retained as an intermediate result, alongside the earlier A/B history.

| Ace intermediate measured case | Mean wall ms/callback | Mean CPU ms/callback | Wall p95 ms | Actual launches |
| --- | ---: | ---: | ---: | ---: |
| Ace, 20 Hz, no enemies | 28.002 | 27.943 | 35.278 | 0 |
| Ace, 20 Hz, engagement | 287.576 | 287.491 | 380.146 | 42 AP, 5 HE |
| Ace, real 10 Hz branch, no enemies | 28.833 | 28.821 | 38.888 | 0 |
| Ace, real 10 Hz branch, engagement | 227.973 | 227.880 | 278.742 | 70 AP, 2 HE |

| Ace engagement work in 60 measured callbacks | Ace 20 Hz | Ace 10 Hz |
| --- | ---: | ---: |
| Candidate evaluations | 2,226 | 2,489 |
| Background candidates | 480 | 480 |
| Peak background candidates/callback | 8 | 8 |
| Armor collision batches | 1,698 | 1,937 |
| World queries | 2,603 | 2,757 |
| Component `localHitTest` calls | 218,428 | 194,504 |
| Of those, HE blast-surface component calls | 199,688 | 174,340 |
| Maximum consecutive background-wait callbacks | 7 | 7 |
| Actors receiving background service | 29 | 29 |
| Maximum atomic actors/callback | 1 | 1 |

Including warmup, ace 20 Hz committed 66 launches from 24 actors; ace 10 Hz
committed 100 from 21 actors. Exact ammo accounting and all candidate/fairness
gates passed. The ace same-input 20 Hz engagement mean is about 21.5% below
the original before run; its no-enemy mean is about 5.2 ms higher. The prior
31.4% value describes the earlier intermediate measurement, not this ace result.
The varying absolute timings reinforce the use of exact work counts and
correctness as CI gates, without claiming a stable game-FPS result.

The historical JSON/log basenames are `multi-bot-combat-final-stress20` and
`multi-bot-combat-final-worker10`. They include individual actor ammunition,
targets/refusals, source identities and the complete per-channel query counts.
The historical 10 Hz report completed at 2026-11-09 15:40:23 UTC.

The full-suite HE ranking test was also updated to match the budget contract.
A test which explicitly sets `background_budget = 0` now first verifies that
CURRENT remains executable while NEXT remains unobserved. On a later serviced
frame the completed NEXT proof still excludes the final loaded cassette.
A second regression supplies no primed NEXT facts: four lower-id peers first
exhaust the eight-candidate quota, then the queued actor obtains its reserved
service and completes all eight alternate-shell proof rows, selecting the
highest observed HE damage. Both cases retain the complete comparison and
do not require atomic passes or a relaxed failure criterion. The HE ranking
file now runs 21 passing tests.

## HE-corrected source verification

After the current-HE intent-preservation correction, the two 29-actor schedules
were run sequentially again in an agreed quiet CPU window, with 10 warmup and
60 measured callbacks each. Runtime SHA256 is
`acbefb3060ed968656c0381578b39134b9c42cd2cd7add7a8a6bc0ec227874bb`
across 261 files, measured on `74989811` plus the pending production correction.
Both reports have identical before/after source identities, and the unchanged
fixture SHA256 is
`84687c5718217cf0a4d469f8e469e224ec7e4e093ba368b2a4f31fb6f28be591`.
These benchmark processes use actual wall clocks for every actor; the controlled
atomic clocks described in the unit-test section are not installed here.

| HE-corrected measured case | Mean wall ms/callback | Mean CPU ms/callback | Wall p95 ms | Actual launches |
| --- | ---: | ---: | ---: | ---: |
| 20 Hz, no enemies | 26.961 | 26.952 | 34.721 | 0 |
| 20 Hz, engagement | 255.416 | 255.379 | 310.762 | 42 AP, 5 HE |
| Real 10 Hz branch, no enemies | 29.959 | 29.923 | 40.591 | 0 |
| Real 10 Hz branch, engagement | 249.158 | 248.876 | 348.367 | 70 AP, 2 HE |

| Engagement work in 60 measured callbacks | HE-corrected 20 Hz | HE-corrected 10 Hz |
| --- | ---: | ---: |
| Candidate evaluations | 2,222 | 2,481 |
| Peak candidate evaluations/callback | 47 | 57 |
| Foreground candidates | 1,717 | 1,935 |
| Background candidates | 480 | 480 |
| Peak background candidates/callback | 8 | 8 |
| Atomic candidates | 25 | 66 |
| Armor collision batches | 1,698 | 1,930 |
| World queries | 2,602 | 2,751 |
| Peak world queries/callback | 62 | 81 |
| Component `localHitTest` calls | 218,064 | 192,920 |
| Peak component calls/callback | 4,924 | 4,408 |
| HE blast evaluations | 1,165 | 1,050 |
| Peak HE blast evaluations/callback | 26 | 24 |
| Of component calls, HE blast-surface calls | 199,308 | 172,840 |
| Peak HE blast-surface component calls/callback | 4,592 | 4,148 |
| HE blast-surface world calls in the analytic fixture | 0 | 0 |
| Maximum consecutive background-wait callbacks | 7 | 7 |
| Actors receiving background service | 29 | 29 |
| Maximum atomic actors/callback | 1 | 1 |

Both no-enemy cases have zero combat candidates, armor batches, world/component
queries and launches. The engagement cases retain the original per-actor caps
and pass exact native launch/ammunition accounting. Including warmup, 20 Hz
committed 66 launches from 24 actors, and 10 Hz committed 100 from 21 actors.
The finite windows do not establish that all 29 actors fired. Every actor's
remaining ammunition, current target/refusal, route and individual query counts
remain available in the JSON.

The same-input 20 Hz engagement mean is about 30.2% below the original before
sample; the no-enemy mean is about 4.1 ms higher. The 10 Hz engagement mean is
higher than the preceding ace sample despite slightly fewer measured queries.
These single-host results describe analytic Python work with real wall-time
deadlines, not isolated causal measurements of the last patch or a supported
BigWorld FPS target. The exact background limit is eight candidates, not eight
HE rays or component queries; the much larger component counts above preserve
that distinction.

The new basenames are `multi-bot-combat-he-final-stress20` and
`multi-bot-combat-he-final-worker10`, each with JSON and log output. They do not
overwrite the ace measurements. The reports completed at 2026-11-09 16:18:39 UTC
and 16:19:08 UTC, respectively, before the quiet CPU window was released.
