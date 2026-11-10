# PR119 control-offset correction — November 10, 2026

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

The GitHub Actions BOT group, full client suite, actual Python 2.7 compiler,
Windows launcher packaging and user in-game regression remain separate final
gates. Neither a host pass nor a future-path probe proves an actual game shot,
frame-time improvement, or fixed live AT7/STB1 presentation. The final PR
record must cite a specific new pushed SHA, completed CI run and downloaded
Windows artifact; the prior `d149aadc` package is **not** this correction.
