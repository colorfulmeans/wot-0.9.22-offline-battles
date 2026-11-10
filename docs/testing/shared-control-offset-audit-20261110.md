# PR119 control-offset correction — November 10, 2026

## Live-report continuation: implemented and locally verified

The user's `wot-error-report-20261110-184606-069fba6421d8.zip` rejects the
in-battle completeness of the previous delivery. Its installed and bundled
build is `colorfulmeans-42796652971-1`, the actual `2f8db7b6` PR head, not an
older package. The current continuation starts from that exact remote commit.
The prior verification results below remain historical evidence, not proof
that the reported control and HE failures are fixed.

The reviewed report and production-order reproductions identify three issues:

- An unchecked blocked-point recovery can first take the hull, face the
  enemy, fail and release the route. A route-only yaw change can then admit
  the same failure again. Opening-route controls alternate between opposing
  turns even though the original driver and route laws were not edited.
- A valid limited-traverse native hull lay can be replaced by a candidate-less
  stationary-review wait. Exact physical-source changes invalidate evidence;
  review then freezes the admitted hull instead of continuing the same lay.
- Loaded ordinary HE contact review receives only the budget left by repeated
  penetration review. Current-source jitter can retire background contacts
  before consumption; even a completed historical coverage count is not a
  current executable contact.

The user has now authorized implementation, independent review, original-PR
update and a fresh Windows test package after reading the handoffs and dialog.
The controlling rules are:

1. Loaded HE reviews current HE penetration, then its legal HE fallback,
   before AP and higher-penetration alternatives. Ordinary HE penetration and
   fallback share one stable sample per target. Whitelisted full-validation
   HE keeps its existing point domain. Non-HE selections use the ordinary
   HE-penetration, AP, higher-penetration, final-HE-fallback ranking even when
   the physically loaded shell is the higher-penetration one.
2. Validation order does not grant a new unloading authority. Current valid
   rounds/cassettes and accepted trigger tails retain their existing ownership;
   independently reviewed NEXT chooses the subsequent load. Loaded HE cannot
   be discarded just because a different shell has a better NEXT plan.
3. A proved legal current ordinary-HE contact can execute without waiting for
   unvisited or pending competitors. Completed usable candidates remain
   damage-ranked. This supersedes historical wording which makes a complete
   all-enemy HE comparison a prerequisite for ordinary CURRENT execution;
   it does not remove the independent NEXT or SPG validation requirements.
4. Scheduling progress and point intention survive exact proof refreshes.
   They are not negative-armour certificates, movement permission or fire
   permission. Current geometry, ammunition and native first-edge checks stay
   strict; work quotas and the penetration threshold are not increased.
5. Before initial recovery takes a route-owned hull, it needs a current
   executable point, a justified native stationary lay, or a concrete checked
   same-point recovery destination. The existing native siege mode-entry
   protocol remains a separate, narrow authorization; it cannot grant a shot
   or an unchecked relocation. A blocker or pending probe alone cannot stop
   or steer the vehicle. Relevant changes may schedule another check; only a
   newly proved action, not a yaw threshold, admits another episode.
6. An admitted same-point native lay continues through planning waits using
   the original live actuator and collision checks. Manual/task/capture
   restrictions, identity loss, actual completion and real lack of progress
   remain terminal boundaries. A stale steering value is not replayed.
7. Friendly line obstruction joins the same point-bound recovery. Its old
   independent side-choice, arrival-success and retry owner must not survive
   as a fallback. Physical ally collision and firing-safety checks remain.

No driver gain, steering speed, authored route, navigation law, damage model,
eight-second penetration search, extra controller, main merge, tag or release
is authorized. Modified regression expectations must name the superseding
rule; old-source failures and final-tree results are recorded separately.
Implementation and independent cross-module review are complete. The frozen
runtime passes the final local inventory below. The original PR's current
delivery section records the exact commit, same-commit CI outcome, artifact
identity and downloaded-package hashes; historical delivery entries below
must not be used as the evidence for this continuation.

### Implemented boundaries and review findings

- `CombatStop` separates an unadmitted inspection from actual motion
  ownership. The original route remains in control while future positions
  are being queried. A completed failed inspection cannot gain ownership
  merely because the normal driver changes yaw. A checked destination, a
  genuine newly opened same-point native lay, or another current legal point
  can create the next episode. The failure latch is not global to all targets.
- An admitted pivot retains its exact target and point through planning
  waits. Both the contact ID and the aim/face point are rebound before the
  ordinary live-target overlay, eliminating a second target's opposing turn.
  Physical progress, rotation refusal, task cancellation, target loss and
  current gun identity remain live boundaries. Missing geometry does not
  replay an old steering value, and continuing a pivot never grants fire.
- Current ordinary HE's qualified local contact work uses the existing
  foreground or same atomic slice before unrelated unknown penetration work.
  Historical damage hints are rechecked exactly. A high-damage hint whose
  current check is pending can yield to a current executable contact without
  converting the pending target into a zero-damage or armour-failed result.
  A newly proved current HE penetration still precedes an uncommitted fallback.
- Finite inspection progress is no longer keyed to the raw source position.
  Exact source poses still revoke all old positive and negative physical
  evidence. Future-position chord work freezes one explicit hypothetical
  source pose for the same destination, shell, target and point; it is never
  a current firing proof. Changed target/component/domain/lane observations
  restart it. Cancellation or replacement during the final native callback
  cannot publish the old plan or destroy a replacement task.
- Friendly obstruction uses the same selected-point task. The independent
  friendly side-choice, retry timer and arrival-success owner, its consumers,
  and the obsolete gun-angle adjustment/rejection store are deleted rather
  than left as fallbacks. Native ally collision and final shot-lane refusal
  remain. BOT death retires its shared control binding while preserving
  already committed launch records; object identity protects a replacement
  binding from an old close callback.
- The integration run caught and repaired a siege-mode admission regression
  introduced by narrowing ordinary recovery ownership. Clear native mode
  admission and explicit attack authority use the existing request/echo
  protocol. A cold wall or single-feature controller cannot acquire a new
  hull/mode permission. Existing siege and full-controller assertions are
  retained. Reload/switch intents are not reinterpreted as failed hydraulic
  geometry or a reason to discard an accepted movement task.

### Regression provenance and scope

New files cover policy scheduling, actual native future-ray work, shared
recovery liveness, BOT friendly recovery/lifecycle, and the reported opening
route plus loaded-HE execution chain. The latter uses the real shared policy,
driver, native evaluator adapter, trigger admission and ammunition accounting
with controlled native observations and deterministic query cost. Its HE
regression reached an actual committed shot and exactly one round deduction,
not merely an `aim` decision. This is still not a Windows #1513 playtest.

Pre-fix failures were retained for HE budget starvation, source-jitter review,
native lay loss during planning waits, unchecked cold recovery, pending
high-damage hints, future-ray progress, final-callback task cancellation,
target/sample mismatch and source-BOT death. A first draft of the live HE
fixture reused the source entity ID for an enemy; that fixture error was
corrected before the valid no-shot baseline was recorded and is not claimed
as a production defect.

Existing tests were migrated only where their expectations required retired
friendly APIs or admitted unchecked blockers/yaw-only retries. The new
expectations require unchanged actual route inputs until a checked goal.
Stationary-domain tests first establish a legitimate current-point combat
stop before testing a planning wait; they no longer depend on freezing an
already admitted pivot. Their negative-domain and no-fire assertions remain.
The original HE damage-ranking, penetration threshold, NEXT unknown-domain,
siege and controller tests are not weakened to hide failures.

The source diff leaves `ai/driver.py`, `ai/navigation.py`, `ai/traffic.py`,
`tank_collision.py` and `vehicle_control/route_tasks.py` unchanged. The only
`native_motion_core.py` change removes a write to the deleted friendly store.
No new test skip, query-budget increase, steering gain, collision bypass,
early current-HE unload, eight-second search or second recovery owner is added.

### Final local verification

Python 3.11.9 used the CI-pinned Pillow 12.3.0, NumPy 2.3.5, ModernGL 5.12.0
and glcontext 3.0.0 dependencies. The final complete run started after all
production and regression edits were frozen, and each test file ran in its own
interpreter to prevent native test doubles leaking between files.

| Gate | Observed result |
| --- | --- |
| Complete client inventory | 529/529 files passed; 10,721 reported tests, including 9 existing environment/resource skips |
| Complete launcher inventory | 49/49 files passed; 1,328 reported tests, with 170 recorded platform/display/resource skips |
| Shared-control ownership checker | 89 tests passed |
| Client source syntax under local Python 3.11 | All 262 modules compile; this is not the Python 2.7 package gate |
| 29-actor analytic shared-control workload | Completed; no-enemy case: 0 launches; mixed AP/HE case: 62 measured launches and 633 armour batches |
| Whitespace/integration diff | `git diff --check` passed; no remaining unstaged runtime edit |

The 29-actor workload recorded an unchanged runtime fingerprint before and
after execution across the 261 files in `offline_lan_0922`:
`afed59ce20df6639c5f44b34ce751ed1f0377443412df474fbc3840ec571db38`.
Its geometry is analytic and its timing is not a Windows-client FPS estimate.
Focused test totals overlap the full inventory and are not added to it.

The unchanged CI workflow must still compile and test with real Python 2.7,
rebuild the shipping x86 native module, compare every packaged client code
object with the same checkout, and build/run the extracted Windows launcher.
Delivery additionally compares the downloaded launcher's bundled Python
sources, build identity and nested client/wotmod bytes with that same run.
The exact post-build attestation belongs in the current PR delivery section,
so this handoff does not invent a future run ID or self-referential commit SHA.

### Native acceptance still required

Use the fresh artifact identified in the PR, not the rejected
`colorfulmeans-42796652971-1` package. The user's next playtest should check:

1. The same AT7 opening route with drive and fire enabled: no unchecked
   enemy inspection may alternate opposing chassis turns with navigation.
2. A target outside the actual gun arc: the original native hull actuator
   should continue the same accepted point through policy review waits.
3. Loaded ordinary HE: a legal current contact should reach an actual shot,
   while NEXT remains independent and does not unload the current cassette.
4. Current high-penetration ammunition: subsequent loading follows verified
   HE-penetration/AP/high-penetration order, not permanent loaded-shell bias.
5. World/friendly obstruction and arrival: retain the same point, revalidate
   at the actual destination, and return the original route on finite failure.
6. Capture/manual/return-base and target death: old movement/gun intentions
   must end without cancelling already committed projectile records.

No new exact Windows #1513 battle or subjective steering smoothness is claimed
by the local tests. Report the installed build identity with any remaining
opening-route, HE, recovery, turret-continuity or frame-pacing failure.

## Historical delivery record

## Authority and starting point

This continuation starts at the original open PR #119 head `d149aadc`, not
the older `D149AD` comparison as a new fork. The user's November 10 review
separates two previously conflated mechanisms:

- the eight-second search *after negative penetration review*; and
- the independent BOT `_gun_angle_order` which tried forward/reverse positions
  around eight **metres** away without proving the gun's selected aim point
  from those positions.

The old eight-second improvement search is removed, including its policy
action, eligibility, timestamps, movement proposals and shared-control special
cases. This is not a zero-second timer. Neither the existing native hull-turn
actuator nor the ordinary route/traffic/ground/collision laws are deleted.
The earlier `shared-he-recovery-contract-20261110.md` and November 9 handoffs
remain historical records; their claims that this eight-second search remains
active are superseded by this review.

## One aim-point owner and physical handoff

`AttackPolicy` chooses the current target, shell, mode and sample. When a
currently reviewed penetration/HE sample is physically blocked or outside
the installed gun's arc, `CombatStop` carries that **same** candidate into one
finite physical recovery episode. It does not ask another module to find a
generic nearby shooting position or reselect an aim point on arrival.

1. An actually executable stationary native hull/hydraulic lay takes priority
   over translation. Stationary review and its pending observations do not
   manufacture a new destination.
2. A genuinely blocked same-point candidate can request projected positions.
   Each position must pass normal navigation checks and the native evaluator's
   future line of sight for the **same shell, target and sample**. Partial
   native queries remain pending; a destination preview never grants fire.
3. The ordinary physical driver executes only the checked destination. The
   phase survives unrelated new candidates and macro target hints. The gun
   target and drive target are both rebound to the phase's original target.
4. Reaching the destination only requests current-pose revalidation. The
   original actual barrel, lane, armour/HE and trigger-admission checks remain
   separate. A recent planned solution cannot stand in for a launch proof.
5. Finite destination exhaustion or a six-second lack of physical progress
   retires the combat movement lease, clears its stopping/turning instructions
   and returns the authored task order. The same failed pose cannot acquire
   the identical task every callback; material source/target motion or fresh
   executable native evidence can open a new episode.

`bot_runtime._gun_angle_order` and its obsolete combat-order call are removed.
The original rear-laying contact and movement safety mechanisms are retained
where they still have independent physical uses. The common combat lease
prevents a separate rear pursuit from co-owning movement.

Capture/parking/explicit travel keep their original translation authority.
An already-occupied capture position may turn a limited gun in place only
after a valid native primary-target laying proposal. A wall-blocked capture
hint cannot steal that hull turn. Mission cancellation clears retained gun
intentions before the next cached physical slice.

## Ammunition and trigger ownership

- With a complete negative penetration review, an available HE fallback is
  considered **immediately**, without an eight-second motion search. A
  verified penetrating shell still fires normally; unknown geometry never
  certifies negative armour.
- Ordinary HE applies its one-point-per-enemy penetration trial to fallback
  contact comparison as well. Only whitelisted high-penetration HE/HESH retains
  full weak-point validation.
- The physically loaded HE round/clip can execute a verified legal current
  contact even when a different enemy remains under review. Independently
  completed `NEXT` evidence selects only the subsequent load; it cannot
  unload or preempt an already admitted current HE trigger.
- HE contact failure may terminate the engagement only after actual complete
  native no-contact evidence; world/friendly blocks and unknown geometry are
  not fabricated no-contact certificates. Actual zero-damage contact remains
  a legal result.
- Retained gun intention only preserves *which point to re-aim at*. Every
  physical first trigger still needs a fresh actual-pose, actual-lane and
  ammunition proof. Dead/despawned targets cannot remain in cached aim input.
- The first-trigger native `auto_world_blocked` receipt now identifies whether
  the hit was on the actual **centre** barrel path or the **scattered** path.
  A centre-path or confirmed wreck obstruction invalidates that point's
  present lane and may request recovery. One scattered ray striking nearby
  geometry refuses that particular trigger with no debit, but does not turn
  an otherwise clear centre point into an automatic movement task. Its next
  trigger still repeats the entire native admission; no shot proof is cached.

## Verification boundaries

Host CPython tests exercise the real shared source with native-observation
fixtures, not Windows BigWorld itself. The frozen local source passed:

- Complete client test inventory: **524/524 files**, **10,666** executed
  methods (**10,657 passed; 9 skipped; 0 failures**).
- Complete launcher inventory: **49/49 files**, **1,328** executed methods
  (**1,158 passed; 170 host/platform skips; 0 failures**).
- The earlier separate `test_player_*.py` pass: **882/882** tests (before
  the additional scatter-refusal regression was added).
- `test_shared_*.py`: **277/277** tests.
- `tools/check_shared_vehicle_control.py --check`: **89/89** tests.
- Capture/contact handoff: **11/11** tests; complete navigation receipts:
  **22/22** tests.
- The 29-actor real worker-scheduling analytic workload committed **101**
  measured launches with exactly matched ammunition debits and no background
  work-quota violations. Its mixed-control CPU mean was **119.320 ms** per
  analytic 100 ms callback on this host; this is not game FPS or a guaranteed
  performance gain. The benchmark now reports the actual point recovery and
  HE fallback state instead of reading the deleted search timer.

The first full client run produced two *environment* errors: the partial
Git clone lacked historical `19d79b1` map blobs referenced by the unchanged
Great Wall and tactical-route tests. Fetching all 42 map blobs restored their
actual historical fixtures. Direct reruns passed **2/2** and **20/20** tests,
respectively. The subsequent full **524/524** source-tree run passed with no
changes to those tests or the routes. The first errors are preserved in the
local logs; they are not reported as a production navigation defect or hidden
from the verification history.

### First GitHub CI caught a real HE scheduling fault

Run [42786557537](https://github.com/colorfulmeans/wot-0.9.22-offline-battles/actions/runs/42786557537)
on head `e222f7b3` completed navigation, native geometry, Windows server/editor
and BOT regression jobs successfully, but its 524-file client job found three
failures in `test_shared_current_he_execution.py` (one failed test file;
the other 523 passed). Its Windows launcher job was consequently skipped;
**no Windows launcher artifact from that run is a valid delivery.**

The CI runner's slower 8 ms native observation slice finished the lower-damage
HE target 14 while the also-negative-armour target 2's higher-damage contact
still had a real `atomic_frame_budget_exhausted` receipt. The policy published
an irrevocable CURRENT aim lock on target 14 before the second comparator
could obtain its fair callback. The outcome is reproducible locally with a
virtual atomic clock that consumes precisely the original wall-clock budget.
This is a genuine first-trigger ranking defect, not a missing fixture, CI
network error, or reason to weaken the three existing expectations.

The follow-up fix postpones **only that first lock** while a currently
penetration-qualified competitor has an explicitly native-budget-exhausted
HE comparison. Its unfinished query must receive an ordinary future slice;
there is no replacement movement timer, extra quota or assumed damage.
A competitor that truly returns `pending`, disappears, changes pose or lacks
positive penetration-failure qualification must not hold an independently
executable loaded HE hostage. Existing tests asserting those distinctions
remain unchanged and pass. New
`test_expensive_second_he_contact_cannot_lock_a_lower_damage_first_target`
forces the budget-expiration schedule without sleeping or stubbing the actual
evaluator. The 23-file shared-control test inventory passed after this fix;
the exact CI Python 3.11.9 dependency set then passed the **entire 524/524**
client file inventory: **10,667** methods, **10,658 passed, 9 skipped, 0
failures**. The standalone 89/89 shared-owner checker also passed. Two fresh
29-BOT worker10 native analytic schedules passed their original quota and
ammunition constraints with respectively **100** and **101** launches and no
background quota overruns; those variable wall-limited counts are not FPS.
The fresh Windows Python 2.7 build and exact downloaded launcher remain
separate CI gates.

### Follow-up CI package and same-run download correction

The corrected head `c75908f4` passed the complete
[Tests run 42792625606](https://github.com/colorfulmeans/wot-0.9.22-offline-battles/actions/runs/42792625606)
client job: 524/524 files, 10,667 methods with 9 skips, plus 49/49 launcher
files, 1,328 methods with 170 platform skips. Navigation, native geometry,
Windows server/editor and the Windows first-chance exception probe passed.
The actual Python 2.7 bytecode and native x86 source stamp were built and
checked in that run. The separately scheduled BOT regression job **failed one
of the 15 cases** in `test_shared_current_he_execution.py`: the expensive
second HE contact was skipped entirely when the atomic frame budget elapsed
immediately after evaluating the first contact. A lower-damage first target
could thus be prematurely locked. Both an explicitly budget-exhausted second
row and a wholly unvisited qualified second contact now defer the first lock
until their expected-damage results can be compared. Dedicated virtual-clock
regressions cover both shapes without increasing the per-frame budget or
relaxing the existing highest-damage HE assertion. The follow-up CI run, not
this failed run, must demonstrate BOT success.

Its Windows launcher was built and **uploaded successfully** as artifact
`13752143372`, 68,578,817 bytes, SHA-256
`d0463d89141ba954c9628a292b34af2d26f537d158906c2b9726439281737fa1`.
An independent download of those exact bytes passed outer ZIP CRC, the x64
launcher PE identity, all **265** bundled server/shared-control Python source
comparisons, the nested client ZIP and `.wotmod` CRCs, shipping x86 native
source stamp, starter equality and replay reader identity. This validates
contents, not execution of the Windows GUI on Linux.

The final Windows job nevertheless failed **after upload**: an immediate
`actions/download-artifact@v4` REST artifact-ID lookup returned `Not Found`
for its freshly uploaded ID. Consequently its downloaded-executable server
smoke step did not run, and that CI run is not reported as all green. The
follow-up workflow uses the documented same-run artifact **name** download
without cross-run `github-token`/REST-ID lookup, retaining the exact
one-extraction Windows server-startup assertion. No shipping gameplay source
or client tests were relaxed for this workflow repair; a new CI result must
pass before the package is considered fully delivered.

The GitHub Actions BOT group, full client suite, actual Python 2.7 compiler,
Windows launcher packaging and user in-game regression remain separate final
gates. Neither a host pass nor a future-path probe proves an actual game shot,
frame-time improvement, or fixed live AT7/STB1 presentation. The final PR
record must cite a specific new pushed SHA, completed CI run and downloaded
Windows artifact; the prior `d149aadc` package is **not** this correction.
